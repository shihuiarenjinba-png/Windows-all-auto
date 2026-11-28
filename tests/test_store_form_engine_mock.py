from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import base64
from pathlib import Path
import tempfile
from threading import Thread
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Local integration is also run with the pinned uploader venv.
    sync_playwright = None

from uploader.store_form_engine import (
    OverviewNavigator,
    StoreUiHold,
    apply_live_section,
    apply_save_reload_reconcile,
    validate_section_approval,
)


PRODUCT_ID = "TEST-PRODUCT-1"
DRAFT_ID = "TEST-DRAFT-9"
NAME = "Synthetic QA Utility"
SECTIONS = {
    "properties": {"Properties": [('select', 'Category', ['utility', 'productivity']),
                                   ('number', 'Maximum rows', []),
                                   ('checkbox', 'Network access', [])]},
    "store-listings": {"Store listings": [('text', 'App name', []),
                                           ('textarea', 'Short description', []),
                                           ('textarea', 'Features', []),
                                           ('textarea', 'Search keywords', []),
                                           ('image', 'Screenshot', [])]},
    "pricing-availability": {"Pricing and availability": [('price', 'Base price', []),
                                                            ('price_tier', 'Price tier', ['tier-360', 'tier-500']),
                                                            ('select', 'Currency', ['JPY', 'USD']),
                                                            ('radio', 'Pricing model', ['Free', 'Paid']),
                                                            ('regions', 'Markets', ['JP', 'US', 'GB'])]},
    "age-ratings": {"Age ratings": [('radio', 'Age rating', ['Everyone', 'Teen']),
                                     ('checkbox_group', 'Declarations', ['Violence', 'User content'])]},
    "packages": {"Packages": [('package', 'Package', [])]},
}


def html_page(path: str) -> str:
    root = f"/dashboard/products/{PRODUCT_ID}"
    if path == "/overview":
        return f'''<!doctype html><h1>Apps and games</h1>
        <a href="{root}/overview">{NAME}</a>'''
    if path == f"{root}/overview":
        links = "".join(f'<a href="{root}/submissions/{DRAFT_ID}/{slug}">{list(content)[0]}</a>'
                        for slug, content in SECTIONS.items())
        return f'<!doctype html><h1>{NAME}</h1>{links}'
    for slug, content in SECTIONS.items():
        if path.endswith("/" + slug):
            title = list(content)[0]
            fields = []
            for kind, label, options in list(content.values())[0]:
                field_id = label.lower().replace(" ", "-")
                if kind in {"text", "textarea", "number", "price"}:
                    tag = "textarea" if kind == "textarea" else "input"
                    typ = ' type="number"' if kind in {"number", "price"} else (' type="text"' if kind == "text" else "")
                    fields.append(f'<label for="{field_id}">{label}</label><{tag} id="{field_id}"{typ}></{tag}>')
                elif kind in {"select", "price_tier", "regions"}:
                    multiple = " multiple" if kind == "regions" else ""
                    choices = "".join(f'<option value="{item}">{item}</option>' for item in options)
                    fields.append(f'<label for="{field_id}">{label}</label><select id="{field_id}"{multiple}>{choices}</select>')
                elif kind == "radio":
                    choices = "".join(f'<label><input type="radio" name="{field_id}" value="{item}">{item}</label>' for item in options)
                    fields.append(f'<fieldset><legend>{label}</legend>{choices}</fieldset>')
                elif kind == "checkbox_group":
                    choices = "".join(f'<label><input type="checkbox" name="{field_id}" value="{item}">{item}</label>' for item in options)
                    fields.append(f'<fieldset><legend>{label}</legend>{choices}</fieldset>')
                elif kind == "checkbox":
                    fields.append(f'<label><input type="checkbox" id="{field_id}">{label}</label>')
                else:
                    fields.append(f'<label for="{field_id}">{label}</label><input id="{field_id}" type="file"><output id="saved-{field_id}"></output>')
            script = '''<script>
            const section=__SECTION__, storageKey='mock:'+section;
            function persist(){
              const saved={};
              for (const el of document.querySelectorAll('input,textarea,select')) {
                const key=el.id || el.name;
                if(el.type==='file') { const names=Array.from(el.files).map(f=>f.name); saved[key]=names; const out=document.getElementById('saved-'+key); if(out) out.textContent=names.join(','); }
                else if(el.type==='checkbox' && el.id) saved[key]=el.checked;
                else if(el.type==='checkbox') { if(!Array.isArray(saved[key])) saved[key]=[]; if(el.checked) saved[key].push(el.value); }
                else if(el.type==='radio') { if(el.checked) saved[key]=el.value; }
                else if(el.multiple) saved[key]=Array.from(el.selectedOptions).map(x=>x.value);
                else if(el.tagName==='SELECT' || el.type==='number' || el.type==='text' || el.tagName==='TEXTAREA') saved[key]=el.value;
              }
              localStorage.setItem(storageKey,JSON.stringify(saved));
            }
            function restore(){
              const saved=JSON.parse(localStorage.getItem(storageKey)||'{}');
              for(const el of document.querySelectorAll('input,textarea,select')) {
                const key=el.id||el.name, value=saved[key]; if(value===undefined) continue;
                if(el.type==='file') { const out=document.getElementById('saved-'+key); if(out) out.textContent=value.join(','); }
                else if(el.type==='checkbox' && el.id) el.checked=value;
                else if(el.type==='checkbox') el.checked=value.includes(el.value);
                else if(el.type==='radio') el.checked=el.value===value;
                else if(el.multiple) for(const o of el.options) o.selected=value.includes(o.value);
                else el.value=value;
              }
            }
            document.addEventListener('DOMContentLoaded',()=>{restore();document.getElementById('save').addEventListener('click',persist);});
            </script>'''.replace("__SECTION__", json.dumps(slug))
            return f'<!doctype html><h1>{title}</h1><form>{"".join(fields)}<button id="save" type="button">Save</button></form>{script}'
    return "<!doctype html><h1>Not found</h1>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = html_page(self.path.split("?", 1)[0]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@unittest.skipIf(sync_playwright is None, "Playwright is installed in the uploader venv, not the base test interpreter")
class StoreFormEngineMockIntegrationTests(unittest.TestCase):
    def test_full_mock_store_flow_inputs_saves_reloads_and_reconciles(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        draft = {"approved": True, "product_id": PRODUCT_ID, "submission_id": DRAFT_ID,
                 "sections": list(SECTIONS), "approval_ref": "MOCK-TEST-ONLY",
                 "approved_by": "test", "approved_at": "2026-11-28T00:00:00Z"}
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                image = root / "screenshot.png"
                image.write_bytes(base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jHU8AAAAASUVORK5CYII="
                ))
                package = root / "candidate.msix"
                package.write_bytes(b"synthetic-msix")
                plans = [
                    ("properties", [
                        {"key": "category", "kind": "select", "label": "Category", "value": "utility"},
                        {"key": "max_rows", "kind": "number", "label": "Maximum rows", "value": 1000},
                        {"key": "network", "kind": "checkbox", "label": "Network access", "value": True},
                    ]),
                    ("store-listings", [
                        {"key": "name", "kind": "text", "label": "App name", "value": NAME},
                        {"key": "short", "kind": "textarea", "label": "Short description", "value": "Local-only mock listing"},
                        {"key": "features", "kind": "textarea", "label": "Features", "value": "CSV review\nLocal report"},
                        {"key": "keywords", "kind": "textarea", "label": "Search keywords", "value": "audit, schema, CSV"},
                        {"key": "shot", "kind": "image", "label": "Screenshot", "value": str(image), "saved_labels": [image.name]},
                    ]),
                    ("pricing-availability", [
                        {"key": "price", "kind": "price", "label": "Base price", "value": 360},
                        {"key": "price_tier", "kind": "price_tier", "label": "Price tier", "value": "tier-360"},
                        {"key": "currency", "kind": "select", "label": "Currency", "value": "JPY"},
                        {"key": "model", "kind": "radio", "label": "Pricing model", "options": ["Free", "Paid"], "value": "Paid"},
                        {"key": "markets", "kind": "regions", "label": "Markets", "value": ["JP", "US"]},
                    ]),
                    ("age-ratings", [
                        {"key": "age", "kind": "radio", "label": "Age rating", "options": ["Everyone", "Teen"], "value": "Everyone"},
                        {"key": "declarations", "kind": "checkbox_group", "label": "Declarations", "options": ["Violence", "User content"], "value": ["User content"]},
                    ]),
                    ("packages", [
                        {"key": "package", "kind": "package", "label": "Package", "value": str(package), "saved_labels": [package.name]},
                    ]),
                ]
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(base + "/overview")
                    navigator = OverviewNavigator(page, overview_url=base + "/overview", allowed_host="127.0.0.1")
                    navigator.select_product(product_id=PRODUCT_ID, product_name=NAME)
                    navigator.open_section(product_id=PRODUCT_ID, submission_id=DRAFT_ID,
                                           section="properties", descriptor={"verified": True,
                                                                            "link_name": "Properties",
                                                                            "path_token": "/properties"})
                    with self.assertRaises(StoreUiHold):
                        apply_save_reload_reconcile(page, [
                            {"key": "first", "kind": "select", "label": "Category", "value": "productivity"},
                            {"key": "missing", "kind": "text", "label": "Unmapped control", "value": "should not be typed"},
                        ])
                    self.assertEqual(page.get_by_label("Category", exact=True).input_value(), "utility")
                    verified = []
                    for slug, fields in plans:
                        navigator.open_overview()
                        navigator.select_product(product_id=PRODUCT_ID, product_name=NAME)
                        section_name = next(iter(SECTIONS[slug]))
                        navigator.open_section(product_id=PRODUCT_ID, submission_id=DRAFT_ID,
                                               section=slug, descriptor={"verified": True,
                                                                        "link_name": section_name,
                                                                        "path_token": "/" + slug})
                        validate_section_approval(draft, product_id=PRODUCT_ID,
                                                  submission_id=DRAFT_ID, section=slug)
                        result = apply_save_reload_reconcile(page, fields)
                        self.assertEqual(result["status"], "SAVED_AND_RECONCILED")
                        verified.append(result["after_reload"])
                    browser.close()
                self.assertEqual(len(verified), 5)
                self.assertEqual(verified[0], {"category": "utility", "max_rows": "1000", "network": True})
                self.assertEqual(verified[1]["shot"], [image.name])
                self.assertEqual(verified[2]["price"], "360")
                self.assertEqual(verified[2]["price_tier"], "tier-360")
                self.assertEqual(set(verified[2]["markets"]), {"JP", "US"})
                self.assertEqual(verified[3]["declarations"], ["User content"])
                self.assertEqual(verified[4]["package"], [package.name])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_unverified_ui_map_and_mismatched_approval_stop_before_form_write(self):
        with self.assertRaisesRegex(StoreUiHold, "approval Product ID or Draft ID"):
            validate_section_approval({"approved": True, "product_id": "wrong", "submission_id": DRAFT_ID,
                                       "sections": ["properties"], "approval_ref": "x",
                                       "approved_by": "test", "approved_at": "today"},
                                      product_id=PRODUCT_ID, submission_id=DRAFT_ID, section="properties")

    def test_real_partner_center_adapter_rejects_unverified_map_before_cdp(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "uploader" / "config" /
                             "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        ui_map = json.loads((Path(__file__).resolve().parents[1] / "uploader" / "config" /
                             "store_ui_maps" / "msix_pwa_app.v1.json").read_text(encoding="utf-8"))
        approval = {"approved": True, "product_id": config["product_id"],
                    "submission_id": config["submission_id"], "sections": ["properties"],
                    "approval_ref": "mock-only", "approved_by": "test", "approved_at": "today"}
        with self.assertRaisesRegex(StoreUiHold, "no action-time verified UI map"):
            apply_live_section(config=config, section="properties", fields=[], approval=approval,
                               ui_map=ui_map, cdp_endpoint="not-even-parsed")


if __name__ == "__main__":
    unittest.main()
