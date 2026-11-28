from __future__ import annotations

from dataclasses import dataclass
import json
import os
from urllib.error import URLError
from urllib.request import urlopen


DEFAULT_LOCAL_EDGE_CDP = "http://127.0.0.1:9223"


@dataclass(frozen=True)
class CdpDiscovery:
    endpoint: str | None
    status: str
    browser: str | None = None


def discover_local_edge_cdp(*, endpoint: str = DEFAULT_LOCAL_EDGE_CDP, timeout: float = 1.5) -> CdpDiscovery:
    """Discover only the previously used loopback Edge CDP port; never launch a browser or read auth state."""
    try:
        with urlopen(endpoint.rstrip("/") + "/json/version", timeout=timeout) as response:
            if response.status != 200:
                return CdpDiscovery(None, "CDP_HTTP_UNAVAILABLE")
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return CdpDiscovery(None, "CDP_NOT_AVAILABLE")
    browser = str(payload.get("Browser", ""))
    if not browser.startswith("Edg/"):
        return CdpDiscovery(None, "CDP_BROWSER_NOT_EDGE", browser[:80] or None)
    return CdpDiscovery(endpoint, "CDP_CONNECTED", browser[:80])


def resolve_local_edge_cdp(explicit: str | None = None) -> CdpDiscovery:
    """Use an explicitly configured endpoint, else the known local Edge port, without auto-login."""
    configured = explicit or os.environ.get("PARTNER_CENTER_CDP_URL")
    if configured:
        return CdpDiscovery(configured, "CDP_ENDPOINT_CONFIGURED")
    return discover_local_edge_cdp()
