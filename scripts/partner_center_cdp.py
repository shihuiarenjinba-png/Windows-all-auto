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
import re
import subprocess
import time
from typing import Any
from urllib.parse import urljoin, urlparse

try:  # Windows runtime dependencies; offline Linux contract CI may omit them.
    import requests
except ModuleNotFoundError:  # pragma: no cover - exercised by Linux import CI
    requests = None
try:
    import websocket
except ModuleNotFoundError:  # pragma: no cover - exercised by Linux import CI
    websocket = None

REQUEST_ERRORS = ((requests.RequestException, ValueError)
                  if requests is not None else (OSError, ValueError))


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CDP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"
PARTNER_HOST = "partner.microsoft.com"
PARTNER_PRODUCTS_URL = "https://partner.microsoft.com/dashboard/products"


def _is_products_overview(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != PARTNER_HOST:
        return False
    path = parsed.path.rstrip("/").lower()
    return (
        path == "/dashboard/products"
        or re.fullmatch(
            r"/[a-z]{2}-[a-z]{2}/dashboard/apps-and-games/overview", path
        ) is not None
    )


def _is_product_overview(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == PARTNER_HOST
        and re.fullmatch(
            r"/[a-z]{2}-[a-z]{2}/dashboard/products/"
            r"[A-Za-z0-9]{8,32}/overview",
            parsed.path.rstrip("/"),
        ) is not None
    )


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
    if requests is None:
        raise PartnerCenterHold("HOLD_LOCAL_PREREQUISITE: requests is missing")
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
    except REQUEST_ERRORS:
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
            except REQUEST_ERRORS:
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
        if websocket is None:
            raise PartnerCenterHold("HOLD_LOCAL_PREREQUISITE: websocket-client is missing")
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

    def current_target_url(self) -> str:
        try:
            targets = _get_json("/json")
        except REQUEST_ERRORS as exc:
            raise PartnerCenterHold("HOLD_BROWSER_AUTOMATION_UNAVAILABLE") from exc
        matches = [
            item for item in targets if isinstance(item, dict)
            and item.get("type") == "page"
            and item.get("id") == self.target_id
        ] if isinstance(targets, list) else []
        if len(matches) != 1 or not isinstance(matches[0].get("url"), str):
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        return str(matches[0]["url"])

    def command(self, method: str, params: dict | None = None,
                timeout: float = 15.0) -> dict:
        self.next_id += 1
        command_id = self.next_id
        try:
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
        except websocket.WebSocketTimeoutException as exc:
            raise PartnerCenterHold(
                f"HOLD_BROWSER_COMMAND_TIMEOUT:{method}"
            ) from exc
        except (websocket.WebSocketException, OSError, ValueError) as exc:
            raise PartnerCenterHold("HOLD_BROWSER_AUTOMATION_UNAVAILABLE") from exc

    def evaluate(self, expression: str, *, user_gesture: bool = False) -> Any:
        result = self.command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": user_gesture,
        })
        value = result.get("result", {})
        if value.get("subtype") == "error" or "exceptionDetails" in result:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        return value.get("value")

    def navigate(self, url: str, timeout: float = 45.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != PARTNER_HOST:
            raise PartnerCenterHold("HOLD_BROWSER_NAVIGATION_REJECTED")
        current_url = self.current_target_url()
        if (url == PARTNER_PRODUCTS_URL
                and isinstance(current_url, str)
                and _is_products_overview(current_url)):
            return
        if (url == PARTNER_PRODUCTS_URL
                and isinstance(current_url, str)
                and _is_product_overview(current_url)):
            try:
                self.pointer_click_exact_link("Apps and games")
            except PartnerCenterHold as exc:
                if str(exc) != "HOLD_PRODUCT_LINK_AMBIGUOUS":
                    raise
                # Some Partner Center layouts omit the breadcrumb from the
                # targetable DOM. The destination is the fixed same-host
                # products overview, so a location assignment is read-only.
                assigned = self.evaluate(
                    "location.assign(" + json.dumps(url, ensure_ascii=False)
                    + "); true"
                )
                if assigned is not True:
                    raise PartnerCenterHold("HOLD_BROWSER_NAVIGATION_REJECTED")
        else:
            assigned = self.evaluate(
                "location.assign(" + json.dumps(url, ensure_ascii=False) + "); true"
            )
            if assigned is not True:
                raise PartnerCenterHold("HOLD_BROWSER_NAVIGATION_REJECTED")
        deadline = time.monotonic() + timeout
        last = None
        stable = 0
        while time.monotonic() < deadline:
            state = self.evaluate(
                "JSON.stringify({u:location.href,t:document.title,r:document.readyState})"
            )
            if isinstance(state, str):
                current = json.loads(state)
                observed_url = str(current.get("u", ""))
                reached = (
                    _is_products_overview(observed_url)
                    if url == PARTNER_PRODUCTS_URL
                    else observed_url.rstrip("/") == url.rstrip("/")
                )
                if (current == last and current.get("r") == "complete"
                        and reached):
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

    def wait_for_exact_control(self, names: list[str],
                               timeout: float = 15.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = [
                control for control in self._visible_controls()
                if control.get("name") in names
            ]
            if len(matches) == 1:
                return str(matches[0]["name"])
            if len(matches) > 1:
                raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
            time.sleep(0.25)
        raise PartnerCenterHold("HOLD_IDENTITY_CONTROL_NOT_READY")

    def _wait_not_busy(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        stable = 0
        last_signature = None
        while time.monotonic() < deadline:
            value = self.evaluate(r"""
JSON.stringify((() => {
  const visible = e => {
    const s=getComputedStyle(e), r=e.getBoundingClientRect();
    return s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0;
  };
  const isPersistentShellBar = e => {
    const r=e.getBoundingClientRect();
    return e.getAttribute('role')==='progressbar'
      && e.getAttribute('aria-label')==='Progress bar'
      && e.classList.contains('progress-bar')
      && e.classList.contains('indeterminate')
      && e.classList.contains('indeterminate-bar')
      && r.height<=4;
  };
  const busy=[...new Set(document.querySelectorAll(
    '[aria-busy="true"],[role="progressbar"],.spinner,.loading'
  ))].filter(visible).filter(e=>!isPersistentShellBar(e));
  const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
  const controls=[...document.querySelectorAll(
    'button,a,input,select,[role="button"],[role="link"],[role="textbox"]'
  )].filter(visible).map(e=>[
    e.tagName, clean(e.getAttribute('aria-label')||e.innerText||e.value),
    clean(e.getAttribute('href')), Boolean(e.disabled)
  ]);
  return {
    ready:document.readyState,
    blocking:busy.length,
    signature:JSON.stringify([location.href,document.title,controls])
  };
})())
""")
            state = json.loads(value) if isinstance(value, str) else {}
            signature = state.get("signature")
            if (state.get("ready") == "complete"
                    and state.get("blocking") == 0
                    and isinstance(signature, str)):
                stable = stable + 1 if signature == last_signature else 1
                last_signature = signature
                if stable >= 3:
                    return
            else:
                stable = 0
                last_signature = None
            time.sleep(0.4)
        raise PartnerCenterHold("HOLD_BROWSER_LOAD_TIMEOUT")

    def click_exact(self, names: list[str]) -> str:
        raw_names = json.dumps(names, ensure_ascii=False)
        script = r"""
JSON.stringify((() => {
  const wanted = __NAMES__;
  const clean = v => String(v || '').replace(/\s+/g,' ').trim();
  const visible = e => { const s=getComputedStyle(e),r=e.getBoundingClientRect(); return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0; };
  const label = e => {
    const menuLabel = e.getAttribute('role')==='menuitem'
      ? e.querySelector('.info-tooltip-container') : null;
    return clean(e.getAttribute('aria-label') || menuLabel?.innerText || e.innerText || e.value);
  };
  const items=[...document.querySelectorAll('button,a,[role="button"],[role="link"],[role="menuitem"],input[type="button"],input[type="submit"]')]
    .filter(visible)
    .filter(e=>!e.disabled && e.getAttribute('aria-disabled')!=='true')
    .map(e => ({e,n:label(e)}))
    .filter(x => wanted.includes(x.n));
  if(items.length!==1) return {ok:false,count:items.length,names:items.map(x=>x.n)};
  items[0].e.click();
  return {ok:true,name:items[0].n};
})())
""".replace("__NAMES__", raw_names)
        result = self.evaluate(script, user_gesture=True)
        parsed = json.loads(result) if isinstance(result, str) else {}
        if parsed.get("ok") is not True:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")
        return str(parsed["name"])

    def pointer_click_exact_link(self, name: str) -> None:
        script = r"""
JSON.stringify((() => {
  const wanted=__NAME__;
  const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
  const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
  const items=[...document.querySelectorAll('a')]
    .filter(visible).filter(e=>clean(e.innerText)===wanted);
  if(items.length!==1) return {ok:false,count:items.length};
  const r=items[0].getBoundingClientRect();
  return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2};
})())
""".replace("__NAME__", json.dumps(name, ensure_ascii=False))
        raw = self.evaluate(script)
        result = json.loads(raw) if isinstance(raw, str) else {}
        x, y = result.get("x"), result.get("y")
        if (result.get("ok") is not True
                or type(x) not in {int, float} or type(y) not in {int, float}
                or not 0 <= x <= 100_000 or not 0 <= y <= 100_000):
            raise PartnerCenterHold("HOLD_PRODUCT_LINK_AMBIGUOUS")
        for event_type in ("mousePressed", "mouseReleased"):
            self.command("Input.dispatchMouseEvent", {
                "type": event_type, "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })

    def open_product_create_menu(self) -> None:
        result = self.evaluate(r"""
JSON.stringify((() => {
  const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
  const selector='offers-table lib-table-command-bar .command-bar-item-highlight button.btn.btn-dropdown.no-outline';
  const items=[...document.querySelectorAll(selector)].filter(visible);
  if(items.length!==1) return {ok:false,count:items.length};
  items[0].click();
  return {ok:true};
})())
""")
        parsed = json.loads(result) if isinstance(result, str) else {}
        if parsed.get("ok") is not True:
            raise PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS")

    def fill_textbox(self, hints: list[str], value: str) -> None:
        script = r"""
JSON.stringify((() => {
  const hints=__HINTS__.map(x=>x.toLowerCase());
  const value=__VALUE__;
  const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
  const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0&&!e.disabled;};
  const deepQuery=(selector,root=document) => {
    const output=[...root.querySelectorAll(selector)];
    for(const element of root.querySelectorAll('*')) {
      if(element.shadowRoot) output.push(...deepQuery(selector,element.shadowRoot));
    }
    return output;
  };
  const shadowHosts=e=>{const hosts=[];let node=e;while(node){const root=node.getRootNode();const host=root&&root.host;if(!host)break;hosts.push(host);node=host;}return hosts;};
  const isProductSearch=e=>!shadowHosts(e).some(host=>host.id==='pc-header-search-box');
  const wantsSearch=hints.some(h=>h.includes('search'));
  const inputs=deepQuery('input:not([type]),input[type="text"],input[type="search"],textarea,[role="textbox"]')
    .filter(visible)
    .filter(e=>!wantsSearch||isProductSearch(e))
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
        matches = [
            control for control in self._visible_controls()
            if control.get("tag") == "a"
            and control.get("name") == display_name
            and isinstance(control.get("href"), str)
        ]
        if len(matches) != 1:
            raise PartnerCenterHold("HOLD_PRODUCT_LINK_AMBIGUOUS")
        target = urljoin(PARTNER_PRODUCTS_URL, matches[0]["href"])
        parsed = urlparse(target)
        if (parsed.scheme != "https" or parsed.hostname != PARTNER_HOST
                or re.fullmatch(
                    r"/[a-z]{2}-[a-z]{2}/dashboard/products/"
                    r"[A-Za-z0-9]{8,32}/overview",
                    parsed.path.rstrip("/"),
                ) is None):
            raise PartnerCenterHold("HOLD_PRODUCT_LINK_AMBIGUOUS")
        self.pointer_click_exact_link(display_name)
        try:
            self._wait_exact_url(
                target, timeout=45.0,
                failure_code="HOLD_PRODUCT_OPEN_NOT_CONFIRMED",
            )
        except PartnerCenterHold as exc:
            if str(exc) != "HOLD_PRODUCT_OPEN_NOT_CONFIRMED":
                raise
            # The trusted pointer click is never repeated. Navigation to the
            # already validated same-host exact-product URL is read-only.
            self.navigate(target, timeout=90.0)
            self._wait_exact_url(
                target, timeout=90.0,
                failure_code="HOLD_PRODUCT_OPEN_NOT_CONFIRMED",
            )
        self._wait_not_busy()

    def _wait_exact_url(self, target: str, timeout: float,
                        failure_code: str) -> None:
        expected = target.rstrip("/")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(r"""
JSON.stringify({url:location.href,ready:document.readyState})
""")
            state = json.loads(value) if isinstance(value, str) else {}
            if (state.get("ready") == "complete"
                    and str(state.get("url", "")).rstrip("/") == expected):
                return
            time.sleep(0.5)
        raise PartnerCenterHold(failure_code)

    def _create_product(self, display_name: str) -> None:
        self.open_product_create_menu()
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
        try:
            self._wait_product_creation_outcome(display_name)
        except PartnerCenterHold as exc:
            if str(exc) != "HOLD_PRODUCT_CREATE_NOT_CONFIRMED":
                raise
            count = self.search_product(display_name)
            if count == 1:
                return
            if count > 1:
                raise PartnerCenterHold("HOLD_DUPLICATE_PRODUCT") from exc
            raise

    def _wait_product_creation_outcome(
            self, display_name: str, timeout: float = 60.0,
            failure_code: str = "HOLD_PRODUCT_CREATE_NOT_CONFIRMED") -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(r"""
JSON.stringify({url:location.href,title:document.title,ready:document.readyState})
""")
            state = json.loads(value) if isinstance(value, str) else {}
            path = urlparse(str(state.get("url", ""))).path.rstrip("/")
            title = str(state.get("title", ""))
            if (state.get("ready") == "complete"
                    and re.fullmatch(
                        r"/[a-z]{2}-[a-z]{2}/dashboard/products/"
                        r"[A-Za-z0-9]{8,32}/overview", path,
                    ) is not None
                    and display_name in title):
                return
            time.sleep(0.5)
        raise PartnerCenterHold(failure_code)

    def _identity_values(self, display_name: str) -> dict:
        labels = {
            "store_id": ["Store ID"],
            "identity_name": ["Package/Identity/Name", "Package/Identity name", "Identity name", "Package identity name"],
            "publisher": ["Package/Identity/Publisher", "Publisher"],
            "publisher_display_name": ["Package/Properties/PublisherDisplayName", "Publisher display name"],
            "package_family_name": ["Package Family Name (PFN)", "Package family name", "PFN"],
            "package_sid": ["Package SID"],
        }
        script = r"""
JSON.stringify((() => {
 const labels=__LABELS__;
 const expectedName=__DISPLAY_NAME__;
 const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
 const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
 const deepQuery=(selector,root=document) => {
   const output=[...root.querySelectorAll(selector)];
   for(const element of root.querySelectorAll('*')) if(element.shadowRoot) output.push(...deepQuery(selector,element.shadowRoot));
   return output;
 };
 const all=deepQuery('dt,th,td,div,span,p,label').filter(visible);
 const read=(names) => {
   const values=[];
   for(const name of names){
    const exact=all.filter(e=>clean(e.innerText||e.textContent)===name);
    for(const label of exact){
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
    const combined=all.filter(e=>{
      const text=clean(e.innerText||e.textContent);
      if(!text.startsWith(name+' ')) return false;
      return ![...e.children].some(child=>clean(child.innerText||child.textContent).startsWith(name+' '));
    });
    for(const item of combined){const v=clean(item.innerText||item.textContent).slice(name.length).trim();if(v) values.push(v);}
   }
   return [...new Set(values)];
 };
 const output={}; for(const [key,names] of Object.entries(labels)) output[key]=read(names);
 const headings=deepQuery('h1,[role="heading"]').filter(visible).filter(e=>clean(e.innerText||e.textContent)===expectedName);
 output.reserved_display_name=headings.length ? [expectedName] : [];
 return output;
})())
""".replace("__LABELS__", json.dumps(labels, ensure_ascii=False)).replace(
            "__DISPLAY_NAME__", json.dumps(display_name, ensure_ascii=False)
        )
        raw = self.evaluate(script)
        values = json.loads(raw) if isinstance(raw, str) else {}
        result = {}
        for key in (*labels, "reserved_display_name"):
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
            identity = self._identity_values(display_name)
        except PartnerCenterHold as exc:
            if str(exc) != "HOLD_IDENTITY_DETAILS_AMBIGUOUS":
                raise
            control = self.wait_for_exact_control([
                "Toggle Product identity", "View product identity",
                "Product identity", "Product Identity",
            ])
            try:
                self.click_exact([control])
            except PartnerCenterHold as click_exc:
                if str(click_exc) == "HOLD_BROWSER_STATE_AMBIGUOUS":
                    raise PartnerCenterHold(
                        "HOLD_IDENTITY_CONTROL_CHANGED"
                    ) from click_exc
                raise
            self._wait_not_busy()
            identity = self._identity_values(display_name)
        self.safe_snapshot()
        return identity

    def _submission_draft_state(self) -> dict:
        """Return same-product draft evidence without opening or submitting it."""
        raw = self.evaluate(r"""
JSON.stringify((() => {
  const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
  const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
  const path=location.pathname.replace(/\/$/,'');
  const product=path.match(/\/dashboard\/products\/([A-Za-z0-9]{8,32})(?:\/|$)/i);
  const productId=product ? product[1] : '';
  const submissionPath=new RegExp('/dashboard/products/'+productId+'/submissions/([0-9]+)(?:/|$)','i');
  const links=[...document.querySelectorAll('a[href]')].filter(visible).map(e=>({
    name:clean(e.innerText||e.textContent), href:String(e.href||'')
  })).filter(x=>productId && (()=>{try{return new URL(x.href,location.href).pathname.match(submissionPath);}catch(_){return false;}})());
  const current=productId ? path.match(submissionPath) : null;
  const starts=[...document.querySelectorAll('button,a,[role="button"]')].filter(visible)
    .filter(e=>clean(e.innerText||e.textContent)==='Start submission');
  return {product_id:productId,current_submission_id:current?current[1]:null,
          submission_links:links,start_submission_count:starts.length};
})())
""")
        state = json.loads(raw) if isinstance(raw, str) else {}
        if (not isinstance(state, dict)
                or not re.fullmatch(r"[A-Za-z0-9]{8,32}", str(state.get("product_id", "")))
                or type(state.get("start_submission_count")) is not int
                or not isinstance(state.get("submission_links"), list)):
            raise PartnerCenterHold("HOLD_SUBMISSION_DRAFT_STATE_AMBIGUOUS")
        return state

    @staticmethod
    def _draft_is_open(state: dict) -> bool:
        if state.get("current_submission_id"):
            return True
        links = state.get("submission_links", [])
        return len(links) > 0

    def ensure_submission_draft_open(self, display_name: str) -> str:
        """Open one draft only after the caller has proven CAS + replay.

        An existing same-product submission link is sufficient proof and is
        never clicked.  If Start submission is used, it is clicked once; an
        uncertain outcome is re-observed and never retried in this call.
        """
        current = self.safe_snapshot()
        if (not _is_product_overview(str(current.get("url", "")))
                or display_name not in str(current.get("title", ""))):
            self._open_exact_product(display_name)
        self._wait_not_busy()
        before = self._submission_draft_state()
        if self._draft_is_open(before):
            return "ALREADY_OPEN"
        if before["start_submission_count"] != 1:
            raise PartnerCenterHold("HOLD_SUBMISSION_DRAFT_STATE_AMBIGUOUS")
        self.click_exact(["Start submission"])
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            self._wait_not_busy()
            after = self._submission_draft_state()
            if self._draft_is_open(after):
                return "OPENED"
            time.sleep(0.5)
        # Do not click again after an uncertain outcome. Re-open the exact
        # product once and observe whether Partner Center created the draft.
        count = self.search_product(display_name)
        if count != 1:
            raise PartnerCenterHold("HOLD_SUBMISSION_DRAFT_NOT_CONFIRMED")
        self._open_exact_product(display_name)
        self._wait_not_busy()
        if self._draft_is_open(self._submission_draft_state()):
            return "OPENED_AFTER_RECHECK"
        raise PartnerCenterHold("HOLD_SUBMISSION_DRAFT_NOT_CONFIRMED")


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
        current = self.page._identity_values(observation.display_name)
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
    except (PartnerCenterHold, *REQUEST_ERRORS) as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
