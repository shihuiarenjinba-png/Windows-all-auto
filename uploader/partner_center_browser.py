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
import hashlib

from uploader.core import UploadError, VerifiedJob, read_msix_manifest_metadata
from uploader.device_families import STORE_DEVICE_FAMILY_LABELS
from uploader.receipts import receipt_matches_job
from uploader.store_form_engine import OverviewNavigator, StoreUiHold

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


def _page_has_signed_in_session(page: Any) -> bool:
    """Read-only, conservative check used only to distinguish exact duplicate tabs."""
    try:
        meta = safe_page_metadata(page)
        if meta["scheme"] != "https" or meta["hostname"] != PARTNER_HOST:
            return False
        if any(part in meta["path"].casefold() for part in ("login", "signin")):
            return False
        return page.locator("input[type='password']").count() == 0
    except Exception:
        return False


def _duplicate_target_signature(page: Any, meta: dict[str, str], config: dict[str, Any]) -> str | None:
    """Return a private digest only when duplicate tabs expose the same complete target view."""
    try:
        body = page.locator("body").inner_text()
    except Exception:
        return None
    normalized = " ".join(str(body).split())
    product_name = str(config.get("product_name", "")).strip()
    if not normalized or (product_name and product_name.casefold() not in (meta["title"] + " " + normalized).casefold()):
        return None
    signature_input = "\n".join((meta["scheme"], meta["hostname"], meta["path"], meta["title"], normalized))
    return hashlib.sha256(signature_input.encode("utf-8")).hexdigest()


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
        # Prefer the sole exact-route tab with a live signed-in session.
        # If several exact-route tabs remain, collapse them only when their
        # visible target-page content is identical. No tab is closed or mutated.
        signed_in = [(page, meta) for page, meta in exact if _page_has_signed_in_session(page)]
        if len(signed_in) == 1:
            return signed_in[0][0], "READY_EXACT_DRAFT_TAB", [m for _, m in partner_pages]
        comparable = signed_in if signed_in else exact
        signatures = [_duplicate_target_signature(page, meta, config) for page, meta in comparable]
        if signatures and signatures[0] is not None and all(sig == signatures[0] for sig in signatures):
            return comparable[0][0], "READY_EXACT_DRAFT_TAB", [m for _, m in partner_pages]
        raise UploadError("PARTNER_CENTER_TAB_AMBIGUOUS", f"Multiple exact DCA Draft tabs are not demonstrably equivalent; candidates={_safe_candidates([m for _, m in exact])}")
    if exact:
        return exact[0][0], "READY_EXACT_DRAFT_TAB", [m for _, m in partner_pages]
    overview_path = "/en-us/dashboard/apps-and-games/overview"
    overview = [(page, meta) for page, meta in partner_pages if meta["path"].rstrip("/") == overview_path]
    if len(overview) > 1:
        raise UploadError("PARTNER_CENTER_TAB_AMBIGUOUS", "Multiple Apps and games Overview tabs matched")
    if overview:
        return overview[0][0], "READY_APPS_GAMES_OVERVIEW", [m for _, m in partner_pages]
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
        # Do not hard-reload a route that is already open in the authenticated
        # Partner Center tab. Same-route reloads are unnecessary and can send
        # an otherwise-rendered page through Microsoft sign-out redirects.
        try:
            current = urlsplit(str(self.page.url))
            target = urlsplit(url)
            same_route = (
                current.scheme.lower() == target.scheme.lower()
                and current.netloc.lower() == target.netloc.lower()
                and current.path.rstrip("/") == target.path.rstrip("/")
            )
        except Exception:
            same_route = False
        if same_route:
            self._assert_session()
            return
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._assert_session()

    def _exact_text(self, value: str, label: str) -> Any:
        return self._one(self.page.get_by_text(value, exact=True), label)

    def _assert_product_name(self, section: str) -> None:
        """Accept the configured product as a complete heading/title segment.

        Partner Center currently renders the Identity heading as
        '<product name> | Product identity' and the document title as
        'Product identity | <product name> | Partner Center'. The product
        name is still bound to the exact Product ID, Package Identity and
        Publisher checks performed by _assert_target.
        """
        product_name = str(self.config["product_name"]).strip()
        exact_count = self.page.get_by_text(product_name, exact=True).count()
        if exact_count == 1:
            return

        try:
            headings = self.page.locator(
                "h1, h2, [role='heading']"
            ).all_text_contents()[:10]
        except Exception:
            headings = []
        try:
            title = self.page.title()
        except Exception:
            title = ""

        def has_product_segment(value: Any) -> bool:
            segments = [
                re.sub(r"\s+", " ", part).strip()
                for part in re.split(r"[|｜]", str(value))
            ]
            return product_name in segments

        if any(has_product_segment(value) for value in headings) or has_product_segment(title):
            return

        raise UploadError(
            "PARTNER_CENTER_UI_CHANGED",
            f"Expected configured Product name in {section} heading/title; "
            f"exact text count={exact_count}",
        )

    def _click_product_navigation_link(self, name: str, expected_path: str, label: str) -> None:
        link = self._one(self.page.get_by_role("link", name=name, exact=True), label)
        href = str(link.get_attribute("href") or "")
        parsed = urlsplit(href)
        if parsed.hostname not in {None, PARTNER_HOST} or parsed.path.rstrip("/") != expected_path.rstrip("/"):
            raise UploadError("PARTNER_CENTER_UI_CHANGED", f"{label} is not bound to the expected product route")
        link.click()
        self.page.wait_for_load_state("domcontentloaded")
        current = safe_page_metadata(self.page)
        if (current["scheme"] != "https" or current["hostname"] != PARTNER_HOST
                or current["path"].rstrip("/") != expected_path.rstrip("/")):
            raise UploadError("PARTNER_CENTER_UI_CHANGED", f"{label} navigation did not reach its exact route")

    def _assert_target(self, product_id: str, submission_id: str) -> str:
        if not product_id or not submission_id:
            raise UploadError("INVALID_JOB", "Product ID and existing Submission ID are required")
        path = f"/en-us/dashboard/products/{product_id}/submissions/{submission_id}"
        packages_url = f"{PARTNER_ORIGIN}{path}/packages"
        # Every operation starts at the ordinary Apps and games Overview and
        # clicks the exact Product ID row before inspecting product/Draft data.
        try:
            navigator = OverviewNavigator(self.page)
            navigator.open_overview()
            navigator.select_product(product_id=product_id, product_name=self.config["product_name"])
        except StoreUiHold as exc:
            raise UploadError("PARTNER_CENTER_UI_CHANGED", str(exc)) from exc
        self._assert_product_name("Overview")
        # Follow the visible Product Identity navigation link from the selected
        # Overview; never depend on a constructed Identity deep link.
        identity_path = f"/en-us/dashboard/products/{product_id}/identity"
        self._click_product_navigation_link("Product Identity", identity_path, "Product Identity link")
        self._assert_product_name("Identity")
        self._exact_text(product_id, "configured Store ID")
        self._exact_text(self.config["identity_name"], "configured Package Identity")
        self._exact_text(self.config["publisher"], "configured Publisher")
        overview_path = f"/en-us/dashboard/products/{product_id}/overview"
        self._click_product_navigation_link("Application overview", overview_path, "Application overview link")
        packages_link = self._one(self.page.locator("a[href$='/packages']"), "Overview Packages link")
        href = packages_link.get_attribute("href") or ""
        if f"/products/{product_id}/submissions/{submission_id}/packages" not in href:
            raise UploadError("SUBMISSION_MISMATCH", "Overview Packages link does not target the configured existing Draft")
        packages_link.click()
        self.page.wait_for_load_state("domcontentloaded")
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

    def _apply_approved_device_families(self, job: VerifiedJob,
                                        package_path: Path) -> dict[str, Any]:
        """Apply only product/Draft-scoped, owner-approved Store device families."""
        settings = self.config.get("device_family_settings")
        approval = settings.get("approval") if isinstance(settings, dict) else None
        if not isinstance(settings, dict) or settings.get("status") != "OWNER_APPROVED" or not isinstance(approval, dict):
            raise UploadError("DEVICE_FAMILY_APPROVAL_REQUIRED", "No persisted owner approval for Store device-family selection")
        if approval.get("product_id") != job.product_id or approval.get("submission_id") != job.submission_id:
            raise UploadError("DEVICE_FAMILY_APPROVAL_MISMATCH", "Device-family approval is bound to a different Product or Draft")
        if any(not isinstance(approval.get(key), str) or not approval[key].strip()
               for key in ("approval_ref", "approved_by", "approved_at")):
            raise UploadError("DEVICE_FAMILY_APPROVAL_INVALID", "Device-family approval reference, owner, and date are required")

        manifest = read_msix_manifest_metadata(package_path)
        manifest_targets = settings.get("manifest_target_device_families")
        if (not isinstance(manifest_targets, list) or
                sorted(set(manifest_targets)) != manifest["target_device_families"]):
            raise UploadError("DEVICE_FAMILY_MANIFEST_MISMATCH", "Persisted target families do not match this exact MSIX Manifest")
        expected_store_labels = settings.get("approved_store_device_families")
        if (not isinstance(expected_store_labels, list) or not expected_store_labels or
                len(set(expected_store_labels)) != len(expected_store_labels)):
            raise UploadError("DEVICE_FAMILY_APPROVAL_INVALID", "Approved Store device-family list is missing or duplicated")
        target_labels = {STORE_DEVICE_FAMILY_LABELS.get(target) for target in manifest_targets}
        if None in target_labels or not set(expected_store_labels).issubset(target_labels):
            raise UploadError("DEVICE_FAMILY_MANIFEST_MISMATCH", "Approved Store device-family choices exceed the exact Manifest targets")

        all_labels = list(STORE_DEVICE_FAMILY_LABELS.values())
        controls: dict[str, Any] = {}
        for label in all_labels:
            control = self.page.get_by_role("checkbox", name=label, exact=True)
            if control.count() != 1 or not control.is_enabled():
                raise UploadError("PARTNER_CENTER_UI_CHANGED", f"Expected one enabled device-family checkbox for {label}")
            controls[label] = control
        current = {label for label, control in controls.items() if control.is_checked()}
        unapproved_checked = current.difference(expected_store_labels)
        if unapproved_checked:
            raise UploadError("DEVICE_FAMILY_STATE_MISMATCH", "Partner Center has checked device families outside the approved profile")

        changed: list[str] = []
        for label in expected_store_labels:
            control = controls[label]
            if not control.is_checked():
                control.click()
                if not control.is_checked():
                    raise UploadError("DEVICE_FAMILY_SELECTION_UNCONFIRMED", f"Approved device-family selection did not hold: {label}")
                changed.append(label)
        return {"approved_store_device_families": sorted(expected_store_labels),
                "manifest_target_device_families": manifest_targets,
                "device_family_approval_ref": approval["approval_ref"],
                "changed_device_family_checkboxes": changed}

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
        device_family_result = self._apply_approved_device_families(job, package_path)
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

        # Recheck the persisted owner selection after package analysis.
        for label in device_family_result["approved_store_device_families"]:
            if not self.page.get_by_role("checkbox", name=label, exact=True).is_checked():
                raise UploadError("DEVICE_FAMILY_MISMATCH", "An approved Windows device family became unchecked during package analysis")
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
            "device_family_selection": device_family_result,
            "warnings": warnings,
            "errors": [],
            "certification_executed": False,
            "publish_executed": False,
        }

    def _verify_overview(self, job: VerifiedJob) -> None:
        # Reconcile from the Apps and games Overview entry and select the exact
        # product row again after Save.
        try:
            navigator = OverviewNavigator(self.page)
            navigator.open_overview()
            navigator.select_product(product_id=job.product_id, product_name=self.config["product_name"])
        except StoreUiHold as exc:
            raise UploadError("PARTNER_CENTER_UI_CHANGED", str(exc)) from exc
        meta = safe_page_metadata(self.page)
        expected_path = f"/en-us/dashboard/products/{job.product_id}/overview"
        if meta["scheme"] != "https" or meta["hostname"] != PARTNER_HOST or meta["path"].rstrip("/") != expected_path:
            raise UploadError("PRODUCT_MISMATCH", "Save did not return to the configured product Overview")
        self._assert_product_name("Overview")
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
        try:
            navigator = OverviewNavigator(self.page)
            navigator.open_overview()
            navigator.select_product(product_id=job.product_id, product_name=self.config["product_name"])
        except StoreUiHold as exc:
            raise UploadError("PARTNER_CENTER_UI_CHANGED", str(exc)) from exc
        self._assert_product_name("Overview")
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
            exact_path = f"/en-us/dashboard/products/{self.config.get('product_id', '')}/submissions/{self.config.get('submission_id', '')}/packages"
            equivalent_duplicates = sum(
                1 for candidate in pages
                if safe_page_metadata(candidate)["scheme"] == "https"
                and safe_page_metadata(candidate)["hostname"] == PARTNER_HOST
                and safe_page_metadata(candidate)["path"].rstrip("/") == exact_path
            )
            resolution = None
            if equivalent_duplicates > 1:
                resolution = "Duplicate exact-Draft tabs were resolved using read-only session checks; when multiple signed-in tabs remained, visible page content also had to match. One tab was selected without closing or changing either tab."
            base.update({"status": status, "selected_page": safe_page_metadata(selected),
                         "candidate_partner_center_pages": candidates,
                         "exact_draft_tab_count": equivalent_duplicates})
            if resolution:
                base["selection_resolution"] = resolution
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
