"""Shared, exact-label Partner Center form and Overview navigation engine.

The engine operates on ordinary Playwright ``Page`` objects, so the same code
can drive a local mock and an authenticated Edge CDP session. It never handles
authentication. Writes require a product/Draft/section-scoped approval record.
The proven Packages uploader remains the sole live package upload adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlsplit


OVERVIEW_URL = "https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview"
PARTNER_HOST = "partner.microsoft.com"
SUPPORTED_KINDS = {
    "text", "textarea", "number", "price", "price_tier", "select", "radio", "checkbox",
    "regions", "checkbox_group", "image", "package",
}


class StoreUiHold(RuntimeError):
    """A changed, ambiguous, unapproved or unverified UI must stop safely."""

    def __init__(self, message: str, *, write_started: bool = False):
        super().__init__(message)
        self.write_started = write_started


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str
    label: str
    value: Any
    options: tuple[str, ...] = ()
    saved_labels: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FieldSpec":
        if not isinstance(value, dict):
            raise StoreUiHold("each field must be an object")
        key, kind, label = (str(value.get(k) or "").strip() for k in ("key", "kind", "label"))
        if not key or kind not in SUPPORTED_KINDS or not label:
            raise StoreUiHold("field key, supported kind, and exact accessible label are required")
        options = value.get("options", [])
        saved = value.get("saved_labels", [])
        if not isinstance(options, list) or any(not isinstance(x, str) or not x for x in options):
            raise StoreUiHold(f"{key}: options must be exact non-empty labels")
        if not isinstance(saved, list) or any(not isinstance(x, str) or not x for x in saved):
            raise StoreUiHold(f"{key}: saved_labels must be exact visible labels")
        return cls(key, kind, label, value.get("value"), tuple(options), tuple(saved))


def validate_section_approval(approval: dict[str, Any], *, product_id: str,
                              submission_id: str, section: str) -> None:
    """Require an explicit approval bound to the exact target and section."""
    if not isinstance(approval, dict) or approval.get("approved") is not True:
        raise StoreUiHold("section approval is missing or not approved")
    exact = {
        "product_id": product_id,
        "submission_id": submission_id,
        "approval_ref": approval.get("approval_ref"),
        "approved_by": approval.get("approved_by"),
        "approved_at": approval.get("approved_at"),
    }
    if approval.get("product_id") != product_id or approval.get("submission_id") != submission_id:
        raise StoreUiHold("approval Product ID or Draft ID does not match the configured target")
    for key in ("approval_ref", "approved_by", "approved_at"):
        if not isinstance(exact[key], str) or not exact[key].strip():
            raise StoreUiHold(f"approval is missing {key}")
    sections = approval.get("sections")
    if not isinstance(sections, list) or section not in sections:
        raise StoreUiHold(f"approval does not authorize section {section}")


def _unique(locator: Any, description: str) -> Any:
    count = locator.count()
    if count != 1:
        raise StoreUiHold(f"expected exactly one {description}; found {count}")
    return locator


def _label(page: Any, text: str) -> Any:
    return _unique(page.get_by_label(text, exact=True), f"label {text!r}")


def _decimal(value: Any, key: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise StoreUiHold(f"{key}: value must be a finite numeric value") from None
    if not number.is_finite():
        raise StoreUiHold(f"{key}: value must be finite")
    return format(number, "f")


def _file_paths(value: Any, key: str, kind: str) -> list[Path]:
    raw = value if isinstance(value, list) else [value]
    if not raw or any(not isinstance(item, (str, os.PathLike)) for item in raw):
        raise StoreUiHold(f"{key}: file value must be a path or list of paths")
    paths = [Path(item).expanduser().resolve(strict=True) for item in raw]
    if any(not path.is_file() for path in paths):
        raise StoreUiHold(f"{key}: every selected file must be a regular file")
    if kind == "image":
        for path in paths:
            extension = path.suffix.lower()
            with path.open("rb") as stream:
                header = stream.read(12)
            valid = (extension == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n")) or (
                extension in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff")) or (
                extension == ".webp" and header.startswith(b"RIFF") and header[8:12] == b"WEBP")
            if not valid:
                raise StoreUiHold(f"{key}: image extension/signature mismatch or unsupported image format")
    if kind == "package" and (len(paths) != 1 or paths[0].suffix.lower() != ".msix"):
        raise StoreUiHold(f"{key}: package field requires exactly one .msix")
    return paths


def read_field(page: Any, spec: FieldSpec, *, after_reload: bool = False) -> Any:
    """Read a control value, using visible saved labels for uploaded files."""
    if spec.kind in {"text", "textarea", "number", "price", "price_tier", "select"}:
        control = _label(page, spec.label)
        if spec.kind in {"select", "price_tier"}:
            return control.locator("option:checked").get_attribute("value") or ""
        return control.input_value()
    if spec.kind == "checkbox":
        return _label(page, spec.label).is_checked()
    if spec.kind == "radio":
        selected = []
        for option in spec.options:
            candidate = _label(page, option)
            if candidate.is_checked():
                selected.append(option)
        if len(selected) > 1:
            raise StoreUiHold(f"{spec.key}: multiple radio options are checked")
        return selected[0] if selected else ""
    if spec.kind == "regions":
        control = _label(page, spec.label)
        return control.locator("option:checked").evaluate_all("nodes => nodes.map(n => n.value)")
    if spec.kind == "checkbox_group":
        selected = []
        for option in spec.options:
            if _label(page, option).is_checked():
                selected.append(option)
        return selected
    if spec.kind in {"image", "package"}:
        if after_reload:
            labels = spec.saved_labels or tuple(Path(p).name for p in _file_paths(spec.value, spec.key, spec.kind))
            for name in labels:
                if page.get_by_text(name, exact=True).count() != 1:
                    raise StoreUiHold(f"{spec.key}: saved file label {name!r} was not retained after reload")
            return list(labels)
        control = _label(page, spec.label)
        return control.evaluate("node => Array.from(node.files || []).map(file => file.name)")
    raise StoreUiHold(f"{spec.key}: unsupported field kind")


def apply_field(page: Any, spec: FieldSpec) -> None:
    """Perform a real Playwright input action on exactly one labeled control."""
    if spec.kind in {"text", "textarea"}:
        if not isinstance(spec.value, str):
            raise StoreUiHold(f"{spec.key}: text value must be a string")
        _label(page, spec.label).fill(spec.value)
    elif spec.kind in {"number", "price"}:
        _label(page, spec.label).fill(_decimal(spec.value, spec.key))
    elif spec.kind in {"select", "price_tier"}:
        if not isinstance(spec.value, str) or not spec.value:
            raise StoreUiHold(f"{spec.key}: select value must be an exact option value")
        control = _label(page, spec.label)
        if control.locator(f"option[value={_css_string(spec.value)}]").count() != 1:
            raise StoreUiHold(f"{spec.key}: exact select option is absent or ambiguous")
        control.select_option(value=spec.value)
    elif spec.kind == "radio":
        if spec.value not in spec.options or len(set(spec.options)) != len(spec.options):
            raise StoreUiHold(f"{spec.key}: radio value must be one unique declared option")
        radio = _label(page, str(spec.value))
        if not radio.is_checked():
            radio.check()
    elif spec.kind == "checkbox":
        if type(spec.value) is not bool:
            raise StoreUiHold(f"{spec.key}: checkbox value must be boolean")
        control = _label(page, spec.label)
        if control.is_checked() != spec.value:
            (control.check if spec.value else control.uncheck)()
    elif spec.kind == "regions":
        if not isinstance(spec.value, list) or any(not isinstance(x, str) for x in spec.value):
            raise StoreUiHold(f"{spec.key}: regions must be a list of exact option values")
        if len(set(spec.value)) != len(spec.value):
            raise StoreUiHold(f"{spec.key}: duplicate region values are not allowed")
        control = _label(page, spec.label)
        available = control.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
        if any(value not in available for value in spec.value):
            raise StoreUiHold(f"{spec.key}: one or more exact region values are unavailable")
        control.select_option(value=spec.value)
    elif spec.kind == "checkbox_group":
        if not isinstance(spec.value, list) or any(x not in spec.options for x in spec.value):
            raise StoreUiHold(f"{spec.key}: group values must be drawn from exact declared options")
        if len(set(spec.options)) != len(spec.options):
            raise StoreUiHold(f"{spec.key}: duplicate declared options")
        for option in spec.options:
            control = _label(page, option)
            checked = option in spec.value
            if control.is_checked() != checked:
                (control.check if checked else control.uncheck)()
    elif spec.kind in {"image", "package"}:
        paths = _file_paths(spec.value, spec.key, spec.kind)
        _label(page, spec.label).set_input_files([str(path) for path in paths])
    else:
        raise StoreUiHold(f"{spec.key}: unsupported field kind")


def validate_field_before_write(page: Any, spec: FieldSpec) -> Any:
    """Check labels, values, and file bytes before changing any control."""
    current = read_field(page, spec)
    if spec.kind in {"text", "textarea"} and not isinstance(spec.value, str):
        raise StoreUiHold(f"{spec.key}: text value must be a string")
    if spec.kind in {"number", "price"}:
        _decimal(spec.value, spec.key)
    if spec.kind in {"select", "price_tier"}:
        if not isinstance(spec.value, str) or not spec.value:
            raise StoreUiHold(f"{spec.key}: select value must be an exact option value")
        control = _label(page, spec.label)
        if control.locator(f"option[value={_css_string(spec.value)}]").count() != 1:
            raise StoreUiHold(f"{spec.key}: exact select option is absent or ambiguous")
    if spec.kind == "radio" and (spec.value not in spec.options or len(set(spec.options)) != len(spec.options)):
        raise StoreUiHold(f"{spec.key}: radio value must be one unique declared option")
    if spec.kind == "checkbox" and type(spec.value) is not bool:
        raise StoreUiHold(f"{spec.key}: checkbox value must be boolean")
    if spec.kind == "regions":
        if not isinstance(spec.value, list) or any(not isinstance(x, str) for x in spec.value) or len(set(spec.value)) != len(spec.value):
            raise StoreUiHold(f"{spec.key}: regions must be a unique list of exact option values")
        control = _label(page, spec.label)
        available = control.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
        if any(value not in available for value in spec.value):
            raise StoreUiHold(f"{spec.key}: one or more exact region values are unavailable")
    if spec.kind == "checkbox_group":
        if not isinstance(spec.value, list) or any(x not in spec.options for x in spec.value) or len(set(spec.options)) != len(spec.options):
            raise StoreUiHold(f"{spec.key}: group values must be unique declared options")
        for option in spec.options:
            _label(page, option)
    if spec.kind in {"image", "package"}:
        _file_paths(spec.value, spec.key, spec.kind)
    return current


def _css_string(value: str) -> str:
    """Quote a string for a CSS attribute selector without fuzzy matching."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def apply_save_reload_reconcile(page: Any, fields: Iterable[FieldSpec | dict[str, Any]], *,
                                save_label: str = "Save") -> dict[str, Any]:
    """Edit the form, save, reload, and require every value to remain exact."""
    specs = [item if isinstance(item, FieldSpec) else FieldSpec.from_dict(item) for item in fields]
    if not specs or len({x.key for x in specs}) != len(specs):
        raise StoreUiHold("form must contain fields with unique keys")
    save = _unique(page.get_by_role("button", name=save_label, exact=True), f"Save button {save_label!r}")
    # Validate every locator and value before the first input action. An
    # invalid later field therefore cannot leave an earlier field half-edited.
    before = {spec.key: validate_field_before_write(page, spec) for spec in specs}
    for spec in specs:
        apply_field(page, spec)
    if not save.is_enabled():
        raise StoreUiHold("Save button is disabled after applying requested values")
    current_url = page.url
    try:
        save.click()
        page.wait_for_load_state("domcontentloaded")
        page.reload(wait_until="domcontentloaded")
    except Exception as exc:
        raise StoreUiHold("Save/reload outcome is unknown; read-only reconciliation is required before retry",
                          write_started=True) from exc
    if page.url != current_url:
        raise StoreUiHold("form URL changed unexpectedly during Save/reload", write_started=True)
    after: dict[str, Any] = {}
    try:
        for spec in specs:
            after[spec.key] = read_field(page, spec, after_reload=spec.kind in {"image", "package"})
            expected = ([Path(p).name for p in _file_paths(spec.value, spec.key, spec.kind)]
                        if spec.kind in {"image", "package"} else spec.value)
            if spec.kind in {"number", "price"}:
                expected = _decimal(spec.value, spec.key)
                try:
                    actual_matches = Decimal(str(after[spec.key])) == Decimal(expected)
                except InvalidOperation:
                    actual_matches = False
            elif spec.kind in {"checkbox_group", "regions"}:
                actual_matches = set(after[spec.key]) == set(expected)
            elif spec.kind in {"image", "package"}:
                actual_matches = after[spec.key] == (list(spec.saved_labels) or expected)
            else:
                actual_matches = after[spec.key] == expected
            if not actual_matches:
                raise StoreUiHold(f"{spec.key}: post-reload value did not match the requested value")
    except StoreUiHold as exc:
        raise StoreUiHold(str(exc), write_started=True) from exc
    except Exception as exc:
        raise StoreUiHold("post-Save field reconciliation failed; do not retry until state is read again",
                          write_started=True) from exc
    return {"status": "SAVED_AND_RECONCILED", "url": current_url,
            "before": before, "after_reload": after, "writes_performed": True}


class OverviewNavigator:
    """Navigate from Apps and games Overview using exact product identity."""

    def __init__(self, page: Any, *, overview_url: str = OVERVIEW_URL,
                 allowed_host: str = PARTNER_HOST):
        self.page = page
        self.overview_url = overview_url
        self.allowed_host = allowed_host

    def open_overview(self) -> None:
        self.page.goto(self.overview_url, wait_until="domcontentloaded")
        parsed = urlsplit(self.page.url)
        expected = urlsplit(self.overview_url)
        if parsed.scheme not in {"https", "http"} or parsed.hostname != self.allowed_host or parsed.path.rstrip("/") != expected.path.rstrip("/"):
            raise StoreUiHold("Apps and games Overview navigation did not reach the expected page")
        if self.page.get_by_role("heading", name=re.compile(r"sign in|サインイン", re.I)).count():
            raise StoreUiHold("authentication is required; complete it manually in the browser")

    def select_product(self, *, product_id: str, product_name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", product_id) or not product_name.strip():
            raise StoreUiHold("exact product name and Product ID are required")
        links = self.page.locator(f"a[href*='/dashboard/products/{product_id}/']")
        link = _unique(links, f"Overview product link for Product ID {product_id}")
        lines = [line.strip() for line in link.inner_text().splitlines() if line.strip()]
        if product_name not in lines and link.get_attribute("aria-label") != product_name:
            raise StoreUiHold("Overview Product ID link text does not exactly match the configured product name")
        link.click()
        self.page.wait_for_load_state("domcontentloaded")
        parsed = urlsplit(self.page.url)
        if parsed.hostname != self.allowed_host or f"/dashboard/products/{product_id}/" not in parsed.path:
            raise StoreUiHold("product link did not resolve to the exact configured Product ID")

    def open_section(self, *, product_id: str, submission_id: str, section: str,
                     descriptor: dict[str, Any]) -> None:
        if descriptor.get("verified") is not True:
            raise StoreUiHold(f"section navigation is not verified for {section}")
        link_name = descriptor.get("link_name")
        path_token = descriptor.get("path_token")
        selector = descriptor.get("selector")
        if not isinstance(path_token, str) or not path_token or (not isinstance(link_name, str) and not isinstance(selector, str)):
            raise StoreUiHold(f"verified UI map is incomplete for {section}")
        link = (_unique(self.page.locator(selector), f"section selector {selector!r}")
                if isinstance(selector, str) else
                _unique(self.page.get_by_role("link", name=link_name, exact=True), f"section link {link_name!r}"))
        href = link.get_attribute("href") or ""
        if product_id not in href or submission_id not in href or path_token not in href:
            raise StoreUiHold("section link href is not bound to the exact Product, Draft, and section")
        link.click()
        self.page.wait_for_load_state("domcontentloaded")
        parsed = urlsplit(self.page.url)
        if parsed.hostname != self.allowed_host or product_id not in parsed.path or submission_id not in parsed.path or path_token not in parsed.path:
            raise StoreUiHold("section navigation postcondition did not match the verified UI map")


def validate_cdp_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise StoreUiHold("CDP endpoint must be a loopback address")


def apply_live_section(*, config: dict[str, Any], section: str,
                       fields: Iterable[FieldSpec | dict[str, Any]],
                       approval: dict[str, Any], ui_map: dict[str, Any],
                       cdp_endpoint: str | None = None) -> dict[str, Any]:
    """Apply one approved non-Package section through the existing Edge session.

    This is the real Playwright adapter. It starts at Apps and games Overview,
    binds the product by exact Product ID and name, follows a versioned verified
    section map, saves, reloads, and compares every requested value. Package
    uploads remain owned by the uploader's analysis/reconciliation workflow.
    """
    from uploader.partner_center_browser import PartnerCenterCDPConnection, safe_page_metadata

    product_id = str(config.get("product_id") or "")
    submission_id = str(config.get("submission_id") or "")
    if section == "packages":
        raise StoreUiHold("Packages is handled by uploader.run so Microsoft analysis and package receipts remain in force")
    validate_section_approval(approval, product_id=product_id,
                              submission_id=submission_id, section=section)
    sections = ui_map.get("sections") if isinstance(ui_map, dict) else None
    descriptor = sections.get(section) if isinstance(sections, dict) else None
    if not isinstance(descriptor, dict) or descriptor.get("verified") is not True:
        raise StoreUiHold(f"no action-time verified UI map for section {section}")
    if ui_map.get("schema_version") != 1 or ui_map.get("submission_route") != config.get("submission_route", "msix_pwa_app"):
        raise StoreUiHold("UI map schema or submission route does not match the configured product")
    validate_cdp_endpoint(cdp_endpoint or os.environ.get("PARTNER_CENTER_CDP_URL", ""))
    endpoint = cdp_endpoint or os.environ["PARTNER_CENTER_CDP_URL"]

    connection = PartnerCenterCDPConnection(endpoint, config)
    try:
        connection.attach()
        contexts = list(connection.browser.contexts)
        if len(contexts) != 1:
            raise StoreUiHold(f"expected one authenticated Edge browser context; found {len(contexts)}")
        pages = list(contexts[0].pages)
        partner_pages = [p for p in pages if safe_page_metadata(p)["hostname"] == PARTNER_HOST]
        if len(partner_pages) > 1:
            raise StoreUiHold("multiple Partner Center tabs are open; resolve the target tab ambiguity first")
        page = partner_pages[0] if partner_pages else contexts[0].new_page()
        navigator = OverviewNavigator(page)
        navigator.open_overview()
        navigator.select_product(product_id=product_id, product_name=str(config["product_name"]))
        product_name_count = page.get_by_text(str(config["product_name"]), exact=True).count()
        if product_name_count != 1:
            raise StoreUiHold("selected Product Overview did not show one exact product name")
        navigator.open_section(product_id=product_id, submission_id=submission_id,
                               section=section, descriptor=descriptor)
        expected_heading = descriptor.get("heading")
        if expected_heading:
            _unique(page.get_by_role("heading", name=expected_heading, exact=True),
                    f"section heading {expected_heading!r}")
        result = apply_save_reload_reconcile(page, fields, save_label=str(descriptor.get("save_label") or "Save"))
        result.update({"product_id": product_id, "submission_id": submission_id,
                       "section": section, "approval_ref": approval["approval_ref"],
                       "ui_map_version": ui_map.get("version"), "entry_route": "apps_and_games_overview",
                       "certification_executed": False, "publish_executed": False})
        return result
    except StoreUiHold:
        raise
    except Exception as exc:
        code = getattr(exc, "code", None)
        detail = f" ({code})" if isinstance(code, str) else ""
        raise StoreUiHold(f"Partner Center navigation/form adapter stopped safely{detail}; inspect current state before retry") from exc
    finally:
        connection.__exit__(None, None, None)
