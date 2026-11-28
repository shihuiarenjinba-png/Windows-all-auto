"""Read-only local, ledger, artifact, and Partner Center status collection."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from uploader.core import UploadError, verify_file
from uploader.partner_center_browser import FILE_INPUT
from .store_workflow import _load_job


SECTION_ROUTES = {
    "pricing_availability": ("Pricing and availability", "/availability"),
    "properties": ("Properties", "/properties"),
    "age_ratings": ("Age ratings", "/ageratings"),
    "packages": ("Packages", "/packages"),
    "store_listings": ("Store listings", "/managelanguages"),
    "submission_options": ("Submission Options", "/options"),
}


def _utc_timestamp(path: Path, field: str) -> str | None:
    try:
        stamp = path.stat().st_ctime if field == "created" else path.stat().st_mtime
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    except OSError:
        return None


def _search_roots(repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("STORE_PACKAGE_CACHE_ROOT")
    if configured:
        roots.append(Path(configured).expanduser())
    roots.append(repo_root / ".store-artifacts")
    roots.append(Path.home() / "Desktop" / "portfolio-audit" / "_runtime" / "store-fleet-sync")
    for ancestor in (repo_root, *repo_root.parents):
        candidate = ancestor / "_runtime" / "store-fleet-sync"
        if candidate.is_dir():
            roots.append(candidate)
    unique: list[Path] = []
    seen: set[str] = set()
    for item in roots:
        resolved = item.expanduser().resolve()
        if str(resolved).casefold() not in seen and resolved.is_dir():
            seen.add(str(resolved).casefold())
            unique.append(resolved)
    return unique


def _local_package(config: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    filename = Path(str(config["path"])).name
    candidates: set[Path] = set()
    configured_path = repo_root / str(config["path"])
    if configured_path.is_file() and not configured_path.is_symlink():
        candidates.add(configured_path.resolve())
    roots = _search_roots(repo_root)
    for root in roots:
        for path in root.rglob(filename):
            if path.is_symlink():
                continue
            if path.is_file():
                resolved = path.resolve()
                if root == resolved or root in resolved.parents:
                    candidates.add(resolved)
    ordered = sorted(candidates)
    if len(ordered) > 1:
        return {"status": "DUPLICATE_CANDIDATES", "expected_file_name": filename,
                "candidate_count": len(ordered),
                "candidates": [str(p) for p in ordered], "search_roots": [str(p) for p in roots]}
    if not ordered:
        return {"status": "NOT_FOUND", "expected_file_name": filename,
                "candidate_count": 0, "search_roots": [str(p) for p in roots]}
    path = ordered[0]
    try:
        job = verify_file(config, path, expected_sha256=config.get("expected_sha256"),
                          max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        with ZipFile(path) as package:
            entries = set(package.namelist())
            signature = "SIGNED_BLOCK_PRESENT" if "AppxSignature.p7x" in entries else "UNSIGNED"
        return {"status": "EXACT_PACKAGE_VERIFIED", "path": str(path),
                "file_name": job.file_name, "size_bytes": job.size,
                "created_at_utc": _utc_timestamp(path, "created"),
                "modified_at_utc": _utc_timestamp(path, "modified"),
                "sha256": job.sha256,
                "sha256_matches_expected": job.sha256.lower() == str(config["expected_sha256"]).lower(),
                "identity": job.identity_name, "publisher": job.publisher,
                "version": job.version, "architecture": job.architecture,
                "signature_state": signature, "manifest_verified": True,
                "search_roots": [str(p) for p in roots]}
    except (OSError, BadZipFile, UploadError, KeyError) as exc:
        return {"status": "PACKAGE_HOLD", "path": str(path),
                "error_type": type(exc).__name__, "error": str(exc)[:500],
                "search_roots": [str(p) for p in roots]}


def _ledger_roots(repo_root: Path) -> list[Path]:
    from .state_paths import state_root
    root = state_root(repo_root)
    return [root] if root.is_dir() else []


def _upload_history(config: dict[str, Any], repo_root: Path, product: str) -> dict[str, Any]:
    product_id, submission_id = config["product_id"], config["submission_id"]
    summaries: list[dict[str, Any]] = []
    db_rows: list[dict[str, Any]] = []
    for root in _ledger_roots(repo_root):
        product_dir = root / product
        db = product_dir / "ledger.sqlite3"
        if db.is_file():
            try:
                conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=2)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only=ON")
                tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "uploads" in tables:
                    for row in conn.execute(
                        "SELECT product_id,submission_id,package_file_name,sha256,status,attempts,error_code "
                        "FROM uploads WHERE product_id=? AND submission_id=?",
                        (product_id, submission_id),
                    ):
                        db_rows.append({"ledger_path": str(db), **dict(row)})
                conn.close()
            except sqlite3.Error as exc:
                db_rows.append({"ledger_path": str(db), "status": "LEDGER_READ_ERROR",
                                "error_type": type(exc).__name__})
        for path in product_dir.rglob("*.json") if product_dir.is_dir() else ():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("product_id") != product_id or data.get("submission_id") != submission_id:
                continue
            summaries.append({"receipt_path": str(path), "receipt_id": data.get("receipt_id") or path.stem,
                              "file_name": data.get("package_file_name"), "sha256": data.get("sha256"),
                              "result": data.get("result"),
                              "partner_center_confirmation": data.get("partner_center_confirmation"),
                              "executed_at": data.get("executed_at"),
                              "error_code": (data.get("details") or {}).get("error_code")})
    unique_receipts: dict[str, dict[str, Any]] = {}
    for receipt in summaries:
        unique_receipts.setdefault(str(receipt.get("receipt_id") or receipt.get("receipt_path")), receipt)
    summaries = list(unique_receipts.values())
    successful = [x for x in summaries if str(x.get("result", "")).upper() in {"SUCCESS", "SUCCEEDED", "PACKAGE_SAVED"}
                  and x.get("partner_center_confirmation") in {"CONFIRMED", "SAVED_AND_RELOADED", "PACKAGE_SAVED"}]
    upload_started_codes = {"UPLOAD_RESULT_UNKNOWN", "PARTNER_CENTER_VALIDATION_FAILED", "UNKNOWN_WARNING",
                            "PACKAGE_METADATA_MISMATCH", "PACKAGE_SAVED", "SUCCESS"}
    start_evidence = [x for x in summaries if str(x.get("error_code", "")).upper() in upload_started_codes
                      or str(x.get("result", "")).upper() in {"SUCCESS", "SUCCEEDED", "PACKAGE_SAVED"}]
    return {"status": "RECONCILE_REQUIRED" if successful else "NO_CONFIRMED_UPLOAD",
            "durable_receipt_count": len(summaries), "durable_receipts": summaries,
            "sqlite_rows": db_rows,
            "successful_receipt_count": len(successful),
            "upload_started_evidence_count": len(start_evidence),
            "partner_center_save_confirmed": bool(successful),
            "ledger_roots": [str(p) for p in _ledger_roots(repo_root)]}


def _artifact_status(config: dict[str, Any]) -> dict[str, Any]:
    repo = config.get("repository")
    artifact_id = config.get("artifact_id")
    if not repo or not artifact_id:
        return {"status": "NOT_CONFIGURED"}
    token = os.environ.get("GH_READ_TOKEN") or os.environ.get("GITHUB_TOKEN")
    request = Request(f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}",
                      headers={"Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        run = data.get("workflow_run") or {}
        return {"status": "AVAILABLE" if not data.get("expired") else "EXPIRED",
                "artifact_id": data.get("id"), "name": data.get("name"),
                "size_in_bytes": data.get("size_in_bytes"), "expired": data.get("expired"),
                "created_at": data.get("created_at"), "expires_at": data.get("expires_at"),
                "digest": data.get("digest"), "run_id": run.get("id"),
                "source_sha": run.get("head_sha"), "source_ref": run.get("head_branch")}
    except HTTPError as exc:
        return {"status": "AUTH_REQUIRED" if exc.code in {401, 403} else
                "NOT_FOUND_OR_NOT_VISIBLE" if exc.code == 404 else "API_ERROR",
                "http_status": exc.code, "artifact_id": artifact_id}
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"status": "API_UNAVAILABLE", "error_type": type(exc).__name__,
                "artifact_id": artifact_id}


def _main_content(page: Any) -> Any:
    for selector in ("[id='3ppmaincontent']", "main", "[role=main]"):
        candidate = page.locator(selector)
        if candidate.count() == 1:
            return candidate
    return page.locator("body")


def _field_states(page: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    content = _main_content(page)
    for element in content.locator("input,textarea,select").all():
        try:
            if not element.is_visible():
                continue
            kind = (element.get_attribute("type") or
                    element.evaluate("e => e.tagName.toLowerCase()"))
            if kind == "hidden":
                continue
            label = element.get_attribute("aria-label") or ""
            ident = element.get_attribute("id")
            if not label and ident:
                label_node = page.locator(f'label[for="{ident}"]')
                if label_node.count() == 1:
                    label = label_node.inner_text(timeout=500)
            if not label:
                label = element.evaluate("e => e.labels ? Array.from(e.labels).map(x => x.innerText).join(' ') : (e.closest('label')?.innerText || '')")
            label = label or element.get_attribute("name") or element.get_attribute("placeholder") or ""
            label = " ".join(label.split())[:100] or "UNLABELED_CONTROL"
            if kind in {"checkbox", "radio"}:
                checked = element.is_checked()
                state = "INPUTTED" if checked else "EMPTY"
            elif kind == "file":
                state = "INPUTTED" if element.evaluate("e => e.files.length > 0") else "EMPTY"
            elif kind == "select":
                selected_nodes = element.locator("option:checked")
                selected = selected_nodes.count()
                state = "INPUTTED" if selected else "EMPTY"
            else:
                state = "INPUTTED" if element.input_value().strip() else "EMPTY"
            field = {"label": label, "kind": kind, "state": state}
            if kind == "select" and selected:
                field["selected_options"] = [" ".join(x.split())[:120]
                                             for x in selected_nodes.all_text_contents()]
            elif kind in {"checkbox", "radio"}:
                field["checked"] = checked
                field["option_value"] = (element.get_attribute("value") or "")[:120]
            elif kind == "file":
                field["selected_file_count"] = element.evaluate("e => e.files.length")
            elif state == "INPUTTED":
                value = element.input_value()
                if re.search(r"(?i)(password|token|secret|credential)", label):
                    field["value_state"] = "REDACTED_SENSITIVE_LABEL"
                else:
                    field["value"] = value[:1200]
            result.append(field)
        except Exception:
            result.append({"label": "UNREADABLE_CONTROL", "state": "UNVERIFIED"})
    return result


def _read_section(page: Any, section: str, href: str,
                  product_id: str, submission_id: str) -> dict[str, Any]:
    token = SECTION_ROUTES[section][1]
    link = page.locator(f"a[href*='{submission_id}'][href*='{token}']")
    if link.count() != 1:
        return {"status": "LINK_AMBIGUOUS", "link_count": link.count()}
    observed_href = link.get_attribute("href") or ""
    if product_id not in observed_href or submission_id not in observed_href or token not in observed_href:
        return {"status": "LINK_TARGET_MISMATCH"}
    observed_name = (link.get_attribute("aria-label") or " ".join(link.inner_text().split()))[:120]
    link.click()
    page.wait_for_load_state("domcontentloaded", timeout=30_000)
    page.wait_for_url(lambda url: token in urlsplit(url).path,
                      timeout=15_000)
    parsed = urlsplit(page.url)
    if product_id not in parsed.path or submission_id not in parsed.path:
        return {"status": "ROUTE_MISMATCH"}
    body = _main_content(page).inner_text(timeout=10_000)
    labels = [x.strip() for x in body.splitlines() if x.strip()]
    relevant = [x[:180] for x in labels if any(t in x.casefold() for t in
                ("complete", "not started", "draft", "warning", "error", "validated", "upload at least"))]
    save_count = page.get_by_role("button", name=re.compile(r"^save( draft)?$", re.I)).count()
    state_text = " ".join(relevant).casefold()
    completion = ("COMPLETE" if "complete" in state_text else
                  "NOT_STARTED" if "not started" in state_text else "NOT_DISPLAYED")
    save_state = "UNKNOWN" if save_count else "NO_SAVE_BUTTON_VISIBLE"
    dirty = "UNKNOWN"
    if re.search(r"unsaved changes|changes not saved|未保存の変更|変更が保存されていません", body, re.I):
        dirty = "UNSAVED_CHANGES_VISIBLE"
    return {"status": "READ_ONLY_OBSERVED", "route": parsed.path,
            "link_label": observed_name,
            "completion": completion, "save_state": save_state, "dirty_state": dirty,
            "visible_warning_or_status": relevant[:30], "fields": _field_states(page),
            "main_image_count": _main_content(page).locator("img").count()}


def _partner_center(config: dict[str, Any], cdp_endpoint: str | None) -> dict[str, Any]:
    from .cdp_discovery import resolve_local_edge_cdp
    discovery = resolve_local_edge_cdp(cdp_endpoint)
    endpoint = discovery.endpoint
    if not endpoint:
        return {"status": discovery.status, "discovery": "known_loopback_edge_port_9223",
                "writes_performed": False}
    parsed_endpoint = urlsplit(endpoint)
    if (parsed_endpoint.scheme != "http" or
            (parsed_endpoint.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"} or
            parsed_endpoint.username or parsed_endpoint.password or parsed_endpoint.query or
            parsed_endpoint.fragment or parsed_endpoint.path not in {"", "/"}):
        return {"status": "CDP_ENDPOINT_REJECTED", "writes_performed": False}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "PLAYWRIGHT_UNAVAILABLE", "writes_performed": False}
    pid, draft = str(config["product_id"]), str(config["submission_id"])
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(endpoint, timeout=8_000)
            contexts = list(browser.contexts)
            matching = [(ctx, page) for ctx in contexts for page in ctx.pages
                        if urlsplit(page.url).hostname == "partner.microsoft.com"
                        and pid in urlsplit(page.url).path]
            draft_tabs = [(ctx, page) for ctx, page in matching if draft in urlsplit(page.url).path]
            output: dict[str, Any] = {"cdp_connected": True, "discovery": discovery.status,
                                      "browser": discovery.browser, "context_count": len(contexts),
                                      "product_tab_count": len(matching),
                                      "exact_draft_tab_count": len(draft_tabs),
                                      "writes_performed": False}
            if len(contexts) != 1:
                output.update({"status": "CONTEXT_AMBIGUOUS", "sections": {}})
            elif not draft_tabs:
                output.update({"status": "EXACT_DRAFT_TAB_NOT_OPEN", "sections": {}})
            else:
                visible: list[dict[str, Any]] = []
                section_links: dict[str, str] = {}
                for _, page in draft_tabs:
                    path = urlsplit(page.url).path
                    title = page.title()
                    if str(config["product_name"]).casefold() not in title.casefold():
                        visible.append({"route": path, "status": "PRODUCT_NAME_MISMATCH"})
                        continue
                    if not path.endswith("/packages"):
                        visible.append({"route": path, "title": title,
                                        "status": "READ_ONLY_CURRENT_TAB"})
                        continue
                    body = page.locator("body").inner_text(timeout=8_000)
                    rows = [" ".join(x.split()) for x in
                            page.locator("table tbody tr").all_text_contents() if x.strip()]
                    for key, (_, token) in SECTION_ROUTES.items():
                        anchors = page.locator(f"a[href*='/submissions/{draft}{token}']")
                        if anchors.count() == 1:
                            section_links[key] = anchors.first.get_attribute("href") or ""
                    warning = "You must upload at least one package" in body
                    visible.append({"route": path, "title": title,
                                    "package_rows": rows, "package_row_count": len(rows),
                                    "empty_package_warning": warning,
                                    "file_input_count": page.locator("input[type=file]").count(),
                                    "verified_package_file_input_selector": FILE_INPUT,
                                    "verified_package_file_input_match_count": page.locator(FILE_INPUT).count(),
                                    "save_button_count": page.get_by_role("button", name="Save", exact=True).count(),
                                    "device_family_checks": page.locator("input[type=checkbox]").evaluate_all(
                                        "els => els.map(e=>({label:e.labels?.[0]?.innerText||'',checked:e.checked}))"),
                                    "read_only": True})
                output["visible_draft_pages"] = visible
                output["section_links_observed"] = section_links
                if len(draft_tabs) != 1:
                    output.update({"status": "TAB_AMBIGUOUS", "sections": {
                        key: {"status": "NOT_INSPECTED_TAB_AMBIGUOUS"} for key in SECTION_ROUTES}})
                else:
                    # Survey using a disposable tab so the user's current tab and
                    # any unsaved browser state are never navigated or reloaded.
                    ctx, source = draft_tabs[0]
                    survey: dict[str, Any] = {}
                    temp = None
                    before = sum(len(c.pages) for c in contexts)
                    try:
                        if not urlsplit(source.url).path.rstrip("/").endswith("/packages") or not section_links:
                            raise RuntimeError("exact Packages page links are not available for the read-only survey")
                        temp = ctx.new_page()
                        temp.goto("https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview",
                                  wait_until="domcontentloaded", timeout=30_000)
                        product_links = temp.locator(f"a[href*='/dashboard/products/{pid}/']")
                        for _ in range(20):
                            candidates = []
                            for i in range(product_links.count()):
                                link = product_links.nth(i)
                                name = " ".join(link.inner_text().split())
                                if name == str(config["product_name"]):
                                    candidates.append(link)
                            if len(candidates) == 1:
                                break
                            temp.wait_for_timeout(300)
                        if len(candidates) != 1:
                            raise RuntimeError("Overview exact product name/ID link is missing or ambiguous")
                        candidates[0].click()
                        temp.wait_for_load_state("domcontentloaded", timeout=30_000)
                        temp.wait_for_url(lambda url: pid in urlsplit(url).path,
                                          timeout=15_000)
                        if pid not in urlsplit(temp.url).path:
                            raise RuntimeError("Overview product link did not resolve to the exact Product ID")
                        overview_text = temp.locator("body").inner_text(timeout=10_000)
                        overview_lines = [line.strip() for line in overview_text.splitlines() if line.strip()]
                        status_lines = [line[:180] for line in overview_lines if any(term in line.casefold()
                                        for term in ("submission", "in draft", "pending", "under review",
                                                     "certification", "published", "complete", "not started"))]
                        lower_overview = " ".join(status_lines).casefold()
                        submission_status = ("PUBLISHED" if "published" in lower_overview else
                                             "IN_REVIEW" if "under review" in lower_overview or "pending" in lower_overview else
                                             "IN_DRAFT" if "in draft" in lower_overview else "NOT_DISPLAYED")
                        output["submission_overview"] = {
                            "route": urlsplit(temp.url).path, "title": temp.title(),
                            "status": submission_status, "visible_status_lines": status_lines[:30],
                            "submission_history_links": [
                                {"text": " ".join(a.inner_text().split())[:100],
                                 "href_path": urlsplit(a.get_attribute("href") or "").path}
                                for a in temp.locator("a[href*='/submission']").all()
                                if pid in (a.get_attribute("href") or "")],
                        }
                        # The Draft URL itself is already open and verified in
                        # the source tab; use that exact existing route in the
                        # disposable tab, then follow its actual section links.
                        temp.goto(source.url, wait_until="domcontentloaded", timeout=30_000)
                        for key in section_links:
                            temp.locator(f"a[href*='{draft}'][href*='{SECTION_ROUTES[key][1]}']").first.wait_for(
                                state="attached", timeout=15_000)
                        output["survey_packages_route"] = urlsplit(temp.url).path
                        output["survey_menu_link_count"] = temp.locator(
                            f"a[href*='/submissions/{draft}/']").count()
                        for key, href in section_links.items():
                            try:
                                survey[key] = _read_section(temp, key, href, pid, draft)
                                # Return to the known existing Packages page in
                                # the temporary tab to reach the next observed link.
                                if key != list(section_links)[-1]:
                                    temp.goto(source.url, wait_until="domcontentloaded", timeout=30_000)
                                    for pending_key in section_links:
                                        temp.locator(f"a[href*='{draft}'][href*='{SECTION_ROUTES[pending_key][1]}']").first.wait_for(
                                            state="attached", timeout=15_000)
                            except Exception as exc:
                                survey[key] = {"status": "READ_ONLY_INSPECTION_FAILED",
                                               "error_type": type(exc).__name__}
                        output.update({"status": "READ_ONLY_OBSERVED", "sections": survey})
                    except Exception as exc:
                        output.update({"status": "READ_ONLY_SURVEY_HOLD",
                                       "sections": survey,
                                       "survey_error_type": type(exc).__name__,
                                       "survey_error": str(exc)[:300]})
                    finally:
                        if temp is not None:
                            try:
                                temp.close()
                            except Exception:
                                pass
                            after = sum(len(c.pages) for c in contexts)
                            output["temporary_tab_cleanup"] = "CLOSED" if after == before else "UNKNOWN"
            return output
    except Exception as exc:
        return {"status": "CDP_READ_FAILED", "error_type": type(exc).__name__,
                "writes_performed": False}


def collect_store_status(*, product: str, config_root: Path, repo_root: Path,
                         cdp_endpoint: str | None = None) -> dict[str, Any]:
    config, config_path = _load_job(product, config_root)
    local = _local_package(config, repo_root.resolve())
    history = _upload_history(config, repo_root.resolve(), product)
    partner = _partner_center(config, cdp_endpoint)
    package_rows = [row for page in partner.get("visible_draft_pages", [])
                    for row in page.get("package_rows", [])]
    visible_files = [row for row in package_rows if Path(str(config["path"])).name in row]
    if history["successful_receipt_count"] and not visible_files:
        reconciliation = "RECONCILE_REQUIRED"
    elif partner.get("status") in {"TAB_AMBIGUOUS", "CONTEXT_AMBIGUOUS"}:
        reconciliation = "RECONCILE_REQUIRED"
    elif any(page.get("empty_package_warning") for page in partner.get("visible_draft_pages", [])):
        reconciliation = "PARTNER_CENTER_PACKAGE_ABSENT"
    elif visible_files:
        reconciliation = "FILENAME_VISIBLE_SHA_NOT_INDEPENDENTLY_VERIFIED"
    else:
        reconciliation = "NO_PACKAGE_ROW_OBSERVED"
    return {
        "schema_version": "all-auto-store-status/1",
        "run_id": uuid4().hex,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "product_key": product,
        "profile": {"path": str(config_path), "product_name": config["product_name"],
                    "product_id": config["product_id"], "submission_id": config["submission_id"],
                    "source_ref": config["ref"], "artifact_id": config.get("artifact_id"),
                    "expected_file_name": Path(config["path"]).name,
                    "expected_sha256": config.get("expected_sha256")},
        "local_package": local,
        "github_artifact": _artifact_status(config),
        "partner_center": partner,
        "submission_state": (partner.get("submission_overview", {}).get("status") or
                             "NOT_EXPOSED_OR_NOT_INSPECTED"),
        "upload_history": history,
        "package_reconciliation": reconciliation,
        "certification_submitted": False,
        "published": False,
        "writes_performed": False,
    }

