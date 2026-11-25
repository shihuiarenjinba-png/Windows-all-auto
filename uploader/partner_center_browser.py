"""Reuse the previously exercised authenticated-browser MSIX Packages route.

This module deliberately has no controls for starting a submission,
certification, pricing, markets, or publishing.
"""
from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen
import re
import json

from uploader.core import UploadError, VerifiedJob
from uploader.receipts import receipt_matches_job

PARTNER_ORIGIN = "https://partner.microsoft.com"
PARTNER_HOST = "partner.microsoft.com"
FILE_INPUT = "input[name='fileuploader'][type='file'][multiple]"
WARNING_SELECTOR = ".alert.alert-warning .alert-string"
ERROR_SELECTOR = ".alert.alert-danger .alert-string"
PACKAGE_NAME_SELECTOR = "table.package-table .package-name .text-base"
PACKAGES_COMPLETE = "a[name='packages'][aria-label='Packages Status:  - Complete']"


def safe_page_metadata(page: Any) -> dict[str, str]:
    """Expose only a bounded title and HTTPS hostname/path; never query/fragment."""
    try:
        parsed = urlsplit(str(page.url))
        hostname = (parsed.hostname or "").lower()
        scheme = parsed.scheme.lower()
        parts = []
        for segment in parsed.path.split("/"):
            if re.search(r"(?i)(token|session|auth|credential|secret)", segment):
                segment = "<redacted>"
            elif len(segment) >= 24 and not segment.isdigit() and re.fullmatch(r"[A-Za-z0-9_-]+", segment):
                segment = "<redacted>"
            parts.append(segment)
        path = "/".join(parts)[:512]
    except Exception:
        hostname, scheme, path = "", "", ""
    try:
        title = str(page.title())
    except Exception:
        title = ""
    title = re.sub(r"https?://\S+", "<url>", title, flags=re.I)
    title = re.sub(r"(?i)(token|session|code|auth)[=: ]+[^\s&]+", r"\1=<redacted>", title)
    title = " ".join(title.split())[:120]
    return {"title": title, "scheme": scheme, "hostname": hostname, "path": path}


def select_partner_center_page(pages: list[Any], config: dict[str, Any]) -> tuple[Any, str, list[dict[str, str]]]:
    """Select one page by exact DCA Draft, then exact Product, then sole PC page."""
    product_id = str(config.get("product_id", ""))
    submission_id = str(config.get("submission_id", ""))
    if not product_id or not submission_id:
        raise UploadError("INVALID_JOB", "Product ID and existing Draft ID are required for browser selection")
    draft_path = f"/en-us/dashboard/products/{product_id}/submissions/{submission_id}/packages"
    product_prefix = f"/en-us/dashboard/products/{product_id}/"
    partner_pages: list[tuple[Any, dict[str, str]]] = []
    for page in pages:
        meta = safe_page_metadata(page)
        if meta["scheme"] == "https" and meta["hostname"] == PARTNER_HOST:
            partner_pages.append((page, meta))
    exact = [(page, meta) for page, meta in partner_pages if meta["path"].rstrip("/") == draft_path]
    if len(exact) > 1:
        raise UploadError("PARTNER_CENTER_TAB_AMBIGUOUS", f"Multiple exact DCA Draft tabs matched; candidates={_safe_candidates([m for _, m in exact])}")
    if exact:
        return exact[0][0], "READY_EXACT_DRAFT_TAB", [m for _, m in partner_pages]
    product = [(page, meta) for page, meta in partner_pages if meta["path"].startswith(product_prefix)]
    if len(product) > 1:
        raise UploadError("PARTNER_CENTER_TAB_AMBIGUOUS", f"Multiple DCA Product tabs matched; candidates={_safe_candidates([m for _, m in product])}")
    if product:
        return product[0][0], "READY_UNIQUE_PRODUCT_TAB", [m for _, m in partner_pages]
    if len(partner_pages) == 1:
        return partner_pages[0][0], "READY_UNIQUE_PARTNER_CENTER_TAB", [m for _, m in partner_pages]
    if not partner_pages:
        raise UploadError("HOLD_NO_MATCHING_PRODUCT_TAB", "No HTTPS Partner Center page is open for the configured DCA Product/Draft")
    raise UploadError("HOLD_NO_MATCHING_PRODUCT_TAB", f"No DCA Product/Draft tab matched; Partner Center pages={_safe_candidates([m for _, m in partner_pages])}")


def _safe_candidates(items: list[dict[str, str]]) -> str:
    return str([{k: v for k, v in item.items() if k in {"title", "hostname", "path"}} for item in items])


class PartnerCenterBrowserPort:
    def __init__(self, page: Any, config: dict[str, Any], *, timeout_seconds: int = 900):
        self.page = page
        self.config = config
        self.timeout_seconds = timeout_seconds

    def _one(self, locator: Any, label: str) -> Any:
        count = locator.count()
        if count != 1:
            raise UploadError("PARTNER_CENTER_UI_CHANGED", f"Expected exactly one {label}; found {count}")
        return locator

    def _assert_session(self) -> None:
        meta = safe_page_metadata(self.page)
        if meta["scheme"] != "https" or meta["hostname"] != PARTNER_HOST or any(part in meta["path"].casefold() for part in ("login", "signin")):
            raise UploadError("AUTH_FAILED", "Authenticated Partner Center browser session is unavailable")
        if self.page.locator("input[type='password']").count():
            raise UploadError("AUTH_FAILED", "Partner Center is requesting sign-in")

    def preflight_target(self, job: VerifiedJob, *, recovery_required: bool = False) -> dict[str, Any]:
        """Read-only route checks performed before a package attempt is reserved."""
        packages_url = self._assert_target(job.product_id, job.submission_id)
        meta = safe_page_metadata(self.page)
        expected_path = f"/en-us/dashboard/products/{job.product_id}/submissions/{job.submission_id}/packages"
        if meta["scheme"] != "https" or meta["hostname"] != PARTNER_HOST or meta["path"].rstrip("/") != expected_path:
            raise UploadError("SUBMISSION_MISMATCH", "Preflight did not resolve to the exact configured DCA Draft Packages route")
        rows = sorted(text.strip() for text in self.page.locator(PACKAGE_NAME_SELECTOR).all_text_contents() if text.strip())
        expected_rows = sorted(self.config.get("expected_existing_package_names", []))
        recoverable_rows = sorted([*expected_rows, job.file_name])
        if rows != expected_rows and not (recovery_required and rows == recoverable_rows):
            raise UploadError("RECONCILE_REQUIRED", "Existing Draft package rows do not match the configured empty/replacement baseline")
        return {"status": "READY_EXACT_DRAFT_TAB", "product_id": job.product_id,
                "submission_id": job.submission_id, "hostname": meta["hostname"], "path": meta["path"],
                "existing_package_rows": rows, "read_only": True, "file_selected": False, "save_clicked": False,
                "packages_url": packages_url}

    def _goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._assert_session()

    def _exact_text(self, value: str, label: str) -> Any:
        return self._one(self.page.get_by_text(value, exact=True), label)

    def _assert_target(self, product_id: str, submission_id: str) -> str:
        if not product_id or not submission_id:
            raise UploadError("INVALID_JOB", "Product ID and existing Submission ID are required")
        path = f"/en-us/dashboard/products/{product_id}/submissions/{submission_id}"
        packages_url = f"{PARTNER_ORIGIN}{path}/packages"
        identity_url = f"{PARTNER_ORIGIN}/en-us/dashboard/products/{product_id}/identity"
        self._goto(identity_url)
        self._exact_text(self.config["product_name"], "configured Product name")
        self._exact_text(product_id, "configured Store ID")
        self._exact_text(self.config["identity_name"], "configured Package Identity")
        self._exact_text(self.config["publisher"], "configured Publisher")
        self._goto(packages_url)
        page_meta = safe_page_metadata(self.page)
        expected_path = f"/en-us/dashboard/products/{product_id}/submissions/{submission_id}/packages"
        if page_meta["scheme"] != "https" or page_meta["hostname"] != PARTNER_HOST or page_meta["path"].rstrip("/") != expected_path:
            raise UploadError("SUBMISSION_MISMATCH", "Partner Center did not open the configured existing Draft")
        self._one(self.page.get_by_role("link", name=self.config["product_name"], exact=True), "configured product breadcrumb")
        # Product and Draft are bound by the exact route; no Start/Create action is present here.
        return packages_url

    def _read_validation(self, job: VerifiedJob) -> tuple[str, list[str], list[str]]:
        errors = [text.strip() for text in self.page.locator(ERROR_SELECTOR).all_text_contents() if text.strip()]
        if errors:
            return "ERROR", [], errors
        warnings = [text.strip() for text in self.page.locator(WARNING_SELECTOR).all_text_contents() if text.strip()]
        known = self.config.get("known_warnings", [])
        if any(text not in known for text in warnings):
            return "UNKNOWN_WARNING", warnings, []
        filename_matches = self.page.locator(PACKAGE_NAME_SELECTOR).all_text_contents()
        rows = [text.strip() for text in filename_matches if text.strip()]
        if job.file_name not in rows:
            return "ANALYZING", warnings, []
        table_text = " ".join(self.page.locator("table.package-table").all_text_contents())
        expected_tokens = (job.version, job.architecture.upper())
        if any(token.casefold() not in table_text.casefold() for token in expected_tokens):
            return "PACKAGE_METADATA_MISMATCH", warnings, []
        if warnings:
            return "WARNING", warnings, []
        if "validated" in table_text.casefold() or self.page.get_by_text("Validated", exact=True).count():
            return "VALIDATED", [], []
        return "ANALYZING", [], []

    def upload_save_and_reconcile(self, job: VerifiedJob, package_path: Path) -> dict[str, Any]:
        packages_url = self._assert_target(job.product_id, job.submission_id)
        existing_rows = [x.strip() for x in self.page.locator(PACKAGE_NAME_SELECTOR).all_text_contents() if x.strip()]
        expected_old = sorted(self.config.get("expected_existing_package_names", []))
        exact_inflight = sorted([*expected_old, job.file_name])
        if tuple(sorted(existing_rows)) not in {tuple(expected_old), tuple(exact_inflight)}:
            raise UploadError("RECONCILE_REQUIRED", "Draft already contains a package row; refusing a duplicate upload")
        already_uploaded = job.file_name in existing_rows
        if already_uploaded:
            raise UploadError("RECONCILE_REQUIRED", "Partner Center already shows this filename; require the prior SHA-bound receipt before any Save")
        uploader = self._one(self.page.locator(FILE_INPUT), "verified MSIX file input")
        try:
            uploader.set_input_files(str(package_path.resolve()))
        except Exception as exc:
            raise UploadError("UPLOAD_RESULT_UNKNOWN", "File selection/upload outcome is ambiguous; reconcile before retry") from exc

        deadline = monotonic() + self.timeout_seconds
        transitions: list[str] = ["PACKAGE_UPLOAD_REQUIRED"]
        if already_uploaded:
            transitions.append("PACKAGE_UPLOAD_RECONCILED_PRESENT")
        while monotonic() < deadline:
            self._assert_session()
            if self.page.get_by_text("Uploading", exact=True).count():
                if "PACKAGE_UPLOAD_IN_PROGRESS" not in transitions:
                    transitions.append("PACKAGE_UPLOAD_IN_PROGRESS")
            if self.page.get_by_text("Analyzing package", exact=True).count():
                if "PACKAGE_ANALYZING" not in transitions:
                    transitions.append("PACKAGE_ANALYZING")
            state, warnings, errors = self._read_validation(job)
            if state == "ANALYZING":
                self.page.wait_for_timeout(500)
                continue
            if state == "ERROR":
                raise UploadError("PARTNER_CENTER_VALIDATION_FAILED", "; ".join(errors))
            if state == "UNKNOWN_WARNING":
                raise UploadError("UNKNOWN_WARNING", "; ".join(warnings))
            if state == "PACKAGE_METADATA_MISMATCH":
                raise UploadError("PACKAGE_METADATA_MISMATCH", "Partner Center parsed a different version or architecture")
            if state not in {"WARNING", "VALIDATED"}:
                self.page.wait_for_timeout(500)
                continue
            if warnings:
                if "PACKAGE_WARNING_REVIEW" not in transitions:
                    transitions.append("PACKAGE_WARNING_REVIEW")
            transitions.append("PACKAGE_SAVE_REQUIRED")
            break
        else:
            raise UploadError("UPLOAD_RESULT_UNKNOWN", "Partner Center package analysis timed out; reconcile before retry")

        # Desktop was automatically selected in the proven App route; confirm it without changing it.
        desktop = self.page.get_by_role("checkbox", name="Windows 10/11 Desktop", exact=True)
        if desktop.count() != 1 or not desktop.is_checked():
            raise UploadError("DEVICE_FAMILY_MISMATCH", "Expected Windows Desktop checkbox is missing or unchecked")
        save = self._one(self.page.get_by_role("button", name="Save", exact=True), "Packages Save button")
        if not save.is_enabled():
            raise UploadError("PARTNER_CENTER_UI_CHANGED", "Packages Save is not enabled")
        try:
            save.click(timeout=30_000)
            self._assert_session()
            self._one(self.page.locator(PACKAGES_COMPLETE), "Packages Complete status").wait_for(state="visible", timeout=60_000)
        except Exception as exc:
            raise UploadError("UPLOAD_RESULT_UNKNOWN", "Packages Save outcome is ambiguous; reconcile the same Draft") from exc

        self._verify_overview(job)
        self.page.reload(wait_until="domcontentloaded", timeout=60_000)
        self._assert_session()
        self._verify_overview(job)
        # The prior successful runs reopened Packages and verified retained package metadata.
        self._goto(packages_url)
        self._exact_text(job.file_name, "saved package filename")
        state, warnings, errors = self._read_validation(job)
        if errors or state not in {"WARNING", "VALIDATED"}:
            raise UploadError("UPLOAD_RESULT_UNCONFIRMED", "Reloaded Packages page did not retain validated package")
        return {
            "partner_center_confirmed": True,
            "method": "authenticated_playwright_cdp_existing_draft_packages",
            "product_id": job.product_id,
            "submission_id": job.submission_id,
            "package_file_name": job.file_name,
            "sha256": job.sha256,
            "partner_center_sha256": None,
            "partner_center_confirmation": "UI_VALIDATED_SHA_UNOBSERVABLE",
            "version": job.version,
            "architecture": job.architecture,
            "state_transitions": transitions + ["PACKAGES_SAVED", "OVERVIEW_RELOADED", "PACKAGES_REOPENED_RETAINED"],
            "package_validation": state,
            "warnings": warnings,
            "errors": [],
            "certification_executed": False,
            "publish_executed": False,
        }

    def _verify_overview(self, job: VerifiedJob) -> None:
        expected = f"{PARTNER_ORIGIN}/en-us/dashboard/products/{job.product_id}/overview"
        self._goto(expected)
        meta = safe_page_metadata(self.page)
        expected_path = f"/en-us/dashboard/products/{job.product_id}/overview"
        if meta["scheme"] != "https" or meta["hostname"] != PARTNER_HOST or meta["path"].rstrip("/") != expected_path:
            raise UploadError("PRODUCT_MISMATCH", "Save did not return to the configured product Overview")
        self._one(self.page.get_by_role("heading", name=job.product_name, exact=True), "configured product Overview heading")
        self._exact_text(job.file_name, "saved package filename on Overview")
        self._exact_text("Validated", "package validation state")
        packages = self._one(self.page.locator(PACKAGES_COMPLETE), "Packages Complete status")
        href = packages.get_attribute("href") or ""
        if f"/products/{job.product_id}/submissions/{job.submission_id}/packages" not in href:
            raise UploadError("SUBMISSION_MISMATCH", "Overview Packages section is bound to a different Draft")
        for old_name in self.config.get("expected_replaced_package_names", []):
            if self.page.get_by_text(old_name, exact=True).count():
                raise UploadError("OLD_PACKAGE_RETAINED", "Overview still contains an expected-to-replace older package")

    def reconcile_ambiguous_upload(self, job: VerifiedJob, package_path: Path,
                                   previous_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read Partner Center; filename/UI state alone cannot establish binary identity."""
        overview_url = f"{PARTNER_ORIGIN}/en-us/dashboard/products/{job.product_id}/overview"
        self._goto(overview_url)
        self._one(self.page.get_by_role("heading", name=job.product_name, exact=True), "configured product Overview heading")
        complete = self.page.locator(PACKAGES_COMPLETE)
        saved_name = self.page.get_by_text(job.file_name, exact=True)
        validated = self.page.get_by_text("Validated", exact=True)
        if complete.count() == 1 and saved_name.count() == 1 and validated.count() == 1:
            href = complete.get_attribute("href") or ""
            if f"/products/{job.product_id}/submissions/{job.submission_id}/packages" in href:
                if receipt_matches_job(previous_receipt, job):
                    return {"partner_center_confirmed": True, "reconciled_after_interruption": True,
                            "method": "authenticated_playwright_cdp_overview_reconcile",
                            "product_id": job.product_id, "submission_id": job.submission_id,
                            "package_file_name": job.file_name, "sha256": job.sha256,
                            "partner_center_sha256": None,
                            "partner_center_confirmation": "UI_VALIDATED_SHA_UNOBSERVABLE",
                            "prior_receipt_sha256_match": True,
                            "partner_center_validation": "Validated", "no_reupload": True}
                return {"safe_to_retry": False, "partner_center_confirmed": False,
                        "product_id": job.product_id, "submission_id": job.submission_id,
                        "package_file_name": job.file_name, "sha256": job.sha256,
                        "partner_center_sha256": None,
                        "reason": "UI filename and Validated state do not expose package SHA; matching prior receipt is missing"}
        packages_url = self._assert_target(job.product_id, job.submission_id)
        rows = sorted(x.strip() for x in self.page.locator(PACKAGE_NAME_SELECTOR).all_text_contents() if x.strip())
        expected_old = sorted(self.config.get("expected_existing_package_names", []))
        if rows == sorted([*expected_old, job.file_name]):
            return {"safe_to_retry": False, "partner_center_confirmed": False,
                    "product_id": job.product_id, "submission_id": job.submission_id,
                    "package_file_name": job.file_name, "sha256": job.sha256,
                    "partner_center_sha256": None,
                    "reason": "Package row exists but Overview did not prove saved state; UI cannot prove binary SHA"}
        if rows == expected_old:
            active = self.page.get_by_text("Uploading", exact=True).count() + self.page.get_by_text("Analyzing package", exact=True).count()
            if active == 0:
                return {"safe_to_retry": True, "same_product_and_draft": True,
                        "existing_rows_match_config": True, "upload_row_present": False,
                        "partner_center_confirmed": False}
        return {"safe_to_retry": False, "partner_center_confirmed": False,
                "product_id": job.product_id, "submission_id": job.submission_id,
                "package_rows": rows, "packages_url": packages_url,
                "reason": "Observed Partner Center state does not match a proven saved or not-written state"}


class PartnerCenterCDPConnection:
    """Attach to a remote browser that is already authenticated by its operator."""
    def __init__(self, cdp_url: str, config: dict[str, Any]):
        self.cdp_url = cdp_url
        self.config = config
        self.playwright = None
        self.browser = None
        self.port = None
        self.selection_status = None
        self.browser_version = "unknown"

    @staticmethod
    def _validate_loopback_endpoint(cdp_url: str) -> None:
        parsed = urlsplit(cdp_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise UploadError("CDP_ENDPOINT_NOT_LOOPBACK", "CDP must use HTTP on a loopback address")

    def _fetch_cdp_version(self) -> dict[str, Any]:
        endpoint = self.cdp_url.rstrip("/") + "/json/version"
        try:
            with urlopen(endpoint, timeout=3) as response:
                if response.status != 200:
                    raise UploadError("BROWSER_CONNECTION_FAILED", "Local Edge CDP version endpoint returned a non-success response")
                payload = json.loads(response.read(65536).decode("utf-8"))
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError("BROWSER_CONNECTION_FAILED", f"Local loopback CDP version endpoint is unavailable ({type(exc).__name__})") from exc
        if not isinstance(payload, dict) or not str(payload.get("Browser", "")).startswith("Edg/"):
            raise UploadError("BROWSER_NOT_EDGE", "The loopback CDP endpoint is not a Microsoft Edge browser")
        return payload

    def __enter__(self) -> PartnerCenterBrowserPort:
        self.attach()
        pages = [page for context in self.browser.contexts for page in context.pages]
        try:
            page, self.selection_status, _ = select_partner_center_page(pages, self.config)
            self.port = PartnerCenterBrowserPort(page, self.config)
            return self.port
        except Exception:
            self.__exit__(None, None, None)
            raise

    def attach(self) -> None:
        """Open the CDP transport only; page targets are never closed."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise UploadError("BROWSER_RUNTIME_MISSING", "Install the optional Playwright package") from exc
        self._validate_loopback_endpoint(self.cdp_url)
        version_payload = self._fetch_cdp_version()
        self.browser_version = str(version_payload.get("Browser", "unknown"))
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_url, timeout=5000)
        except Exception as exc:
            try:
                self.__exit__(None, None, None)
            except Exception:
                pass
            # Keep the useful Playwright/CDP exception while removing local
            # WebSocket endpoint identifiers and any query-string material.
            detail = f"{type(exc).__name__}: {exc}"
            if "ws://" in detail or "wss://" in detail:
                detail = detail.split("://", 1)[0] + "://<CDP WebSocket URL redacted>"
            detail = detail.replace(self.cdp_url, "<CDP endpoint>")
            detail = " ".join(detail.split())[:600]
            raise UploadError(
                "BROWSER_CONNECTION_FAILED",
                f"Could not attach to the configured authenticated browser session. Diagnostic: {detail}",
            ) from exc

    def doctor(self) -> dict[str, Any]:
        """Attach and inspect only; this method never navigates or mutates a page."""
        if self.browser is None:
            self.attach()
        contexts = list(self.browser.contexts)
        pages = [page for context in contexts for page in context.pages]
        partner_pages = [page for page in pages if (lambda m: m["scheme"] == "https" and m["hostname"] == PARTNER_HOST)(safe_page_metadata(page))]
        base = {"browser_version": self.browser_version,
                "cdp_connected": True, "context_count": len(contexts), "page_count": len(pages),
                "partner_center_page_count": len(partner_pages),
                "product_id": str(self.config.get("product_id", "")),
                "submission_id": str(self.config.get("submission_id", "")),
                "pages": [safe_page_metadata(page) for page in pages], "read_only": True,
                "navigation_performed": False, "clicks_performed": False, "save_performed": False}
        try:
            selected, status, candidates = select_partner_center_page(pages, self.config)
            base.update({"status": status, "selected_page": safe_page_metadata(selected),
                         "candidate_partner_center_pages": candidates})
            try:
                PartnerCenterBrowserPort(selected, self.config)._assert_session()
                base["authentication_state"] = "SIGNED_IN_SESSION_PRESENT"
            except UploadError as exc:
                base.update({"status": "HOLD_AUTH_REQUIRED", "authentication_state": "SIGN_IN_REQUIRED",
                             "error_code": exc.code, "diagnostic": str(exc)})
        except UploadError as exc:
            if exc.code.startswith("HOLD_"):
                hold_status = exc.code
            elif "Multiple exact DCA Draft tabs" in str(exc):
                hold_status = "HOLD_MULTIPLE_EXACT_DRAFT_TABS"
            elif "Multiple DCA Product tabs" in str(exc):
                hold_status = "HOLD_MULTIPLE_PRODUCT_TABS"
            else:
                hold_status = "HOLD_BROWSER_DIAGNOSTIC"
            base.update({"status": hold_status, "error_code": exc.code, "diagnostic": str(exc)})
        return base

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None
