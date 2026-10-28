"""Deterministic local Edge/Partner Center driver with no WebDriver or LLM.

Only a localhost Chrome DevTools Protocol endpoint is used.  The driver never
reads cookies, storage, request headers, raw HTML, passwords, MFA values, or
downloaded authentication material.  Diagnostic output is restricted to the
current URL/title and visible control labels.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time
from typing import Any
from urllib.parse import urlparse

import requests
import websocket


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CDP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"
PARTNER_HOST = "partner.microsoft.com"
PARTNER_PRODUCTS_URL = "https://partner.microsoft.com/dashboard/products"


class PartnerCenterHold(RuntimeError):
    pass


def _edge_path() -> Path:
    candidates = (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    )
    for path in candidates:
        if path.is_file():
            return path
    raise PartnerCenterHold("HOLD_LOCAL_PREREQUISITE: Microsoft Edge is missing")


def _get_json(path: str, timeout: float = 3.0) -> Any:
    response = requests.get(CDP_BASE + path, timeout=timeout)
    response.raise_for_status()
    return response.json()


def ensure_edge(*, launch: bool = True, timeout: float = 12.0) -> dict:
    """Return sanitized CDP version metadata, launching the existing profile.

    Edge is started with the user's normal Default profile.  No profile copy is
    made and no credential is entered by this process.  A login redirect is a
    HOLD handled by the caller.
    """
    try:
        version = _get_json("/json/version")
    except (requests.RequestException, ValueError):
        if not launch:
            raise PartnerCenterHold("HOLD_BROWSER_AUTOMATION_UNAVAILABLE")
        subprocess.Popen(
            [
                str(_edge_path()),
                f"--remote-debugging-port={CDP_PORT}",
                "--user-data-dir=" + str(
                    Path.home() / "AppData/Local/Microsoft/Edge/User Data"
                ),
                "--profile-directory=Default",
                "about:blank",
            ],
            close_fds=True,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                version = _get_json("/json/version")
                break
            except (requests.RequestException, ValueError):
                time.sleep(0.25)
        else:
            raise PartnerCenterHold("HOLD_BROWSER_AUTOMATION_UNAVAILABLE")
    browser = version.get("Browser")
    protocol = version.get("Protocol-Version")
    if not isinstance(browser, str) or not isinstance(protocol, str):
        raise PartnerCenterHold("HOLD_BROWSER_AUTOMATION_UNAVAILABLE")
    return {"browser": browser, "protocol_version": protocol}


@dataclass
class CdpPage:
    target_id: str
    socket: Any
    next_id: int = 0

    @classmethod
    def attach(cls) -> "CdpPage":
        targets = _get_json("/json")
        if not isinstance(targets, list):
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        pages = [x for x in targets if x.get("type") == "page"]
        preferred = [x for x in pages if urlparse(str(x.get("url", ""))).hostname == PARTNER_HOST]
        if not preferred:
            preferred = [x for x in pages if x.get("url") == "about:blank"]
        if not preferred:
            auth_hosts = {"login.microsoftonline.com", "login.live.com"}
            preferred = [x for x in pages
                         if urlparse(str(x.get("url", ""))).hostname in auth_hosts]
        if len(preferred) != 1:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        item = preferred[0]
        ws_url = item.get("webSocketDebuggerUrl")
        if not isinstance(ws_url, str) or not ws_url.startswith("ws://127.0.0.1:"):
            raise PartnerCenterHold("HOLD_BROWSER_AUTOMATION_UNAVAILABLE")
        try:
            sock = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
        except Exception as exc:
            raise PartnerCenterHold("HOLD_BROWSER_AUTOMATION_UNAVAILABLE") from exc
        return cls(str(item.get("id")), sock)

    def close(self) -> None:
        self.socket.close()

    def command(self, method: str, params: dict | None = None,
                timeout: float = 15.0) -> dict:
        self.next_id += 1
        command_id = self.next_id
        self.socket.settimeout(timeout)
        self.socket.send(json.dumps({
            "id": command_id, "method": method, "params": params or {},
        }))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") != command_id:
                continue
            if "error" in message:
                raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
            return message.get("result", {})

    def evaluate(self, expression: str) -> Any:
        result = self.command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": False,
        })
        value = result.get("result", {})
        if value.get("subtype") == "error" or "exceptionDetails" in result:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        return value.get("value")

    def navigate(self, url: str, timeout: float = 45.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != PARTNER_HOST:
            raise PartnerCenterHold("HOLD_BROWSER_NAVIGATION_REJECTED")
        self.command("Page.enable")
        self.command("Page.navigate", {"url": url})
        deadline = time.monotonic() + timeout
        last = None
        stable = 0
        while time.monotonic() < deadline:
            state = self.evaluate(
                "JSON.stringify({u:location.href,t:document.title,r:document.readyState})"
            )
            if isinstance(state, str):
                current = json.loads(state)
                if current == last and current.get("r") == "complete":
                    stable += 1
                    if stable >= 3:
                        return
                else:
                    stable = 0
                last = current
            time.sleep(0.5)
        raise PartnerCenterHold("HOLD_BROWSER_LOAD_TIMEOUT")

    def safe_snapshot(self) -> dict:
        """Return only non-secret control metadata; never HTML or page storage."""
        script = r"""
JSON.stringify((() => {
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim().slice(0, 160);
  const visible = element => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };
  const controls = [...document.querySelectorAll('button,a,input,select,[role="button"],[role="link"],[role="textbox"]')]
    .filter(visible)
    .slice(0, 120)
    .map((element, index) => ({
      index,
      tag: element.tagName.toLowerCase(),
      role: clean(element.getAttribute('role')),
      type: clean(element.getAttribute('type')),
      name: clean(element.getAttribute('aria-label') || element.innerText || element.value),
      placeholder: clean(element.getAttribute('placeholder')),
      href: element.tagName === 'A' ? clean(element.getAttribute('href')) : ''
    }));
  return {url: location.href, title: document.title, ready: document.readyState, controls};
})())
"""
        raw = self.evaluate(script)
        if not isinstance(raw, str):
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        snapshot = json.loads(raw)
        host = urlparse(str(snapshot.get("url", ""))).hostname
        if host != PARTNER_HOST:
            raise PartnerCenterHold("HOLD_PARTNER_CENTER_AUTH_REQUIRED")
        return snapshot

    def _visible_controls(self) -> list[dict]:
        snapshot = self.safe_snapshot()
        controls = snapshot.get("controls")
        if not isinstance(controls, list):
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        return controls

    def _wait_not_busy(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        stable = 0
        while time.monotonic() < deadline:
            value = self.evaluate(r"""
JSON.stringify((() => {
  const visible = e => {
    const s=getComputedStyle(e), r=e.getBoundingClientRect();
    return s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0;
  };
  const busy=[...document.querySelectorAll('[aria-busy="true"],[role="progressbar"],.spinner,.loading')].filter(visible).length;
  return {ready:document.readyState,busy};
})())
""")
            state = json.loads(value) if isinstance(value, str) else {}
            if state.get("ready") == "complete" and state.get("busy") == 0:
                stable += 1
                if stable >= 3:
                    return
            else:
                stable = 0
            time.sleep(0.4)
        raise PartnerCenterHold("HOLD_BROWSER_LOAD_TIMEOUT")

    def click_exact(self, names: list[str]) -> str:
        raw_names = json.dumps(names, ensure_ascii=False)
        script = r"""
JSON.stringify((() => {
  const wanted = __NAMES__;
  const clean = v => String(v || '').replace(/\s+/g,' ').trim();
  const visible = e => { const s=getComputedStyle(e),r=e.getBoundingClientRect(); return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0; };
  const items=[...document.querySelectorAll('button,a,[role="button"],[role="link"],input[type="button"],input[type="submit"]')]
    .filter(visible)
    .map(e => ({e,n:clean(e.getAttribute('aria-label')||e.innerText||e.value)}))
    .filter(x => wanted.includes(x.n));
  if(items.length!==1) return {ok:false,count:items.length,names:items.map(x=>x.n)};
  items[0].e.click();
  return {ok:true,name:items[0].n};
})())
""".replace("__NAMES__", raw_names)
        result = self.evaluate(script)
        parsed = json.loads(result) if isinstance(result, str) else {}
        if parsed.get("ok") is not True:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        return str(parsed["name"])

    def fill_textbox(self, hints: list[str], value: str) -> None:
        script = r"""
JSON.stringify((() => {
  const hints=__HINTS__.map(x=>x.toLowerCase());
  const value=__VALUE__;
  const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
  const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0&&!e.disabled;};
  const inputs=[...document.querySelectorAll('input:not([type]),input[type="text"],input[type="search"],textarea,[role="textbox"]')]
    .filter(visible)
    .filter(e=>{const label=clean(e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.name).toLowerCase();return hints.some(h=>label===h||label.includes(h));});
  if(inputs.length!==1) return {ok:false,count:inputs.length};
  const e=inputs[0]; e.focus();
  const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
  const setter=Object.getOwnPropertyDescriptor(proto,'value').set;
  setter.call(e,value);
  e.dispatchEvent(new Event('input',{bubbles:true}));
  e.dispatchEvent(new Event('change',{bubbles:true}));
  return {ok:e.value===value};
})())
""".replace("__HINTS__", json.dumps(hints, ensure_ascii=False)).replace(
            "__VALUE__", json.dumps(value, ensure_ascii=False)
        )
        result = self.evaluate(script)
        parsed = json.loads(result) if isinstance(result, str) else {}
        if parsed.get("ok") is not True:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")

    def press_enter(self) -> None:
        self.command("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": "Enter", "code": "Enter",
            "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
        })
        self.command("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": "Enter", "code": "Enter",
            "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
        })

    def exact_product_count(self, display_name: str) -> int:
        script = r"""
(() => {
  const wanted=__NAME__;
  const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
  const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
  const rows=[...document.querySelectorAll('tr,[role="row"],li,[role="listitem"]')].filter(visible);
  const matched=rows.filter(row=>clean(row.innerText).split(/\r?\n/).map(clean).includes(wanted));
  if(matched.length) return matched.length;
  return [...document.querySelectorAll('a,button,[role="link"]')].filter(visible).filter(e=>clean(e.innerText)===wanted).length;
})()
""".replace("__NAME__", json.dumps(display_name, ensure_ascii=False))
        count = self.evaluate(script)
        if type(count) is not int or count < 0:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        return count

    def search_product(self, display_name: str) -> int:
        self.navigate(PARTNER_PRODUCTS_URL)
        self.safe_snapshot()  # authentication/host gate
        self._wait_not_busy()
        self.fill_textbox(["search", "search products", "search by product name"], display_name)
        try:
            self.click_exact(["Search"])
        except PartnerCenterHold:
            self.press_enter()
        self._wait_not_busy()
        return self.exact_product_count(display_name)

    def _open_exact_product(self, display_name: str) -> None:
        self.click_exact([display_name])
        self._wait_not_busy()

    def _create_product(self, display_name: str) -> None:
        self.click_exact(["New product", "Create a new product", "+ New product"])
        self._wait_not_busy()
        self.click_exact(["MSIX or PWA app"])
        self._wait_not_busy()
        self.fill_textbox(["product name", "name", "reserve a name"], display_name)
        try:
            self.click_exact(["Check availability"])
            self._wait_not_busy()
        except PartnerCenterHold:
            pass
        body_state = self.evaluate(r"""
(() => {
 const text=String(document.body?.innerText||'').replace(/\s+/g,' ').toLowerCase();
 return {available:text.includes('available'),unavailable:text.includes('not available')||text.includes('unavailable')};
})()
""")
        if not isinstance(body_state, dict) or body_state.get("unavailable") is True:
            raise PartnerCenterHold("HOLD_NAME_UNAVAILABLE")
        if body_state.get("available") is not True:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        self.click_exact(["Reserve product name"])
        self._wait_not_busy(45)

    def _identity_values(self) -> dict:
        labels = {
            "store_id": ["Store ID"],
            "reserved_display_name": ["Reserved display name", "Reserved product name"],
            "identity_name": ["Package/Identity name", "Identity name", "Package identity name"],
            "publisher": ["Publisher"],
            "publisher_display_name": ["Publisher display name"],
            "package_family_name": ["Package family name", "PFN"],
            "package_sid": ["Package SID"],
        }
        script = r"""
JSON.stringify((() => {
 const labels=__LABELS__;
 const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
 const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
 const all=[...document.querySelectorAll('dt,th,td,div,span,p,label')].filter(visible);
 const read=(names) => {
   const hits=all.filter(e=>names.includes(clean(e.innerText||e.textContent)));
   const values=[];
   for(const label of hits){
     const candidates=[];
     if(label.tagName==='DT' && label.nextElementSibling) candidates.push(label.nextElementSibling);
     if(label.tagName==='TH' && label.parentElement) candidates.push(...label.parentElement.querySelectorAll('td'));
     if(label.nextElementSibling) candidates.push(label.nextElementSibling);
     if(label.parentElement){
       const children=[...label.parentElement.children];
       const index=children.indexOf(label); if(index>=0) candidates.push(...children.slice(index+1));
     }
     for(const c of candidates){const v=clean(c.innerText||c.textContent||c.value);if(v&&!names.includes(v)) values.push(v);}
   }
   return [...new Set(values)];
 };
 const output={}; for(const [key,names] of Object.entries(labels)) output[key]=read(names);
 return output;
})())
""".replace("__LABELS__", json.dumps(labels, ensure_ascii=False))
        raw = self.evaluate(script)
        values = json.loads(raw) if isinstance(raw, str) else {}
        result = {}
        for key in labels:
            candidates = values.get(key)
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise PartnerCenterHold("HOLD_IDENTITY_DETAILS_AMBIGUOUS")
            value = candidates[0]
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise PartnerCenterHold("HOLD_IDENTITY_DETAILS_AMBIGUOUS")
            result[key] = value.strip()
        return result

    def open_identity(self, display_name: str) -> dict:
        self._open_exact_product(display_name)
        self._wait_not_busy()
        try:
            self.click_exact(["View product identity", "Product identity"])
            self._wait_not_busy()
        except PartnerCenterHold:
            # Some Partner Center product pages expose Identity in navigation.
            self.click_exact(["Identity"])
            self._wait_not_busy()
        self.safe_snapshot()
        return self._identity_values()


@dataclass(frozen=True)
class IdentityObservation:
    target_id: str
    display_name: str
    creation_status: str
    initial_search_count: int
    identity: dict
    observed_url: str
    observed_title: str


class PartnerCenterDriver:
    def __init__(self) -> None:
        ensure_edge()
        self.page = CdpPage.attach()

    def close(self) -> None:
        self.page.close()

    def process(self, job: dict) -> tuple[dict, IdentityObservation]:
        name = str(job["display_name"])
        count = self.page.search_product(name)
        if count > 1:
            raise PartnerCenterHold("HOLD_DUPLICATE_PRODUCT")
        if count == 0:
            if job.get("allow_local_product_creation") is not True:
                raise PartnerCenterHold("HOLD_DUPLICATE_PRODUCT_CREATE_FORBIDDEN")
            self.page._create_product(name)
            after = self.page.search_product(name)
            if after != 1:
                raise PartnerCenterHold("HOLD_PRODUCT_CREATE_NOT_CONFIRMED")
            creation = "CREATED"
        else:
            creation = "REUSED_EXISTING"
        identity = self.page.open_identity(name)
        snapshot = self.page.safe_snapshot()
        captured = {
            key: job[key] for key in (
                "request_id", "slug", "product_type", "display_name",
                "source_repository", "source_branch", "source_sha",
                "registration_type", "partner_center_selection",
                "identity_return_target",
            )
        }
        captured.update(identity)
        captured.update({
            "creation_status": creation,
            "overview_exact_match_count": 1,
            "identity_details_observed": True,
        })
        observation = IdentityObservation(
            target_id=self.page.target_id,
            display_name=name,
            creation_status=creation,
            initial_search_count=count,
            identity=dict(identity),
            observed_url=str(snapshot["url"]),
            observed_title=str(snapshot["title"]),
        )
        return captured, observation

    def verify_current(self, observation: IdentityObservation, receipt: dict) -> bool:
        snapshot = self.page.safe_snapshot()
        current = self.page._identity_values()
        return (
            self.page.target_id == observation.target_id
            and snapshot.get("url") == observation.observed_url
            and current == observation.identity
            and all(receipt.get(key) == value for key, value in current.items())
            and receipt.get("display_name") == observation.display_name
        )


def diagnostic() -> dict:
    version = ensure_edge()
    page = CdpPage.attach()
    try:
        page.navigate(PARTNER_PRODUCTS_URL)
        snapshot = page.safe_snapshot()
        return {"status": "PARTNER_CENTER_CONTROLS_OBSERVED", **version, **snapshot}
    finally:
        page.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("diagnose",))
    args = parser.parse_args(argv)
    try:
        result = diagnostic() if args.mode == "diagnose" else {}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PartnerCenterHold, requests.RequestException, ValueError) as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
