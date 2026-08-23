import ipaddress
import re
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Request, WebSocket

_CHROMIUM_EXTENSION_ID = re.compile(r"^[a-p]{32}$")


def is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def safe_http_request(request: Request) -> bool:
    if not is_loopback_host(request.url.hostname):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
        request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and is_loopback_host(parsed.hostname)
        and parsed.hostname == request.url.hostname
        and origin_port == request_port
    )


def safe_ui_websocket(websocket: WebSocket) -> bool:
    host_header = websocket.headers.get("host", "")
    try:
        host = urlsplit(f"http://{host_header}")
        host_port = host.port or 80
    except ValueError:
        return False
    if not is_loopback_host(host.hostname):
        return False
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port or 80
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == host.hostname
        and origin_port == host_port
    )


def safe_extension_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    if parsed.username or parsed.password or port or parsed.path or parsed.query or parsed.fragment:
        return False
    hostname = parsed.hostname or ""
    if parsed.scheme == "chrome-extension":
        return _CHROMIUM_EXTENSION_ID.fullmatch(hostname) is not None
    if parsed.scheme != "moz-extension":
        return False
    try:
        UUID(hostname)
    except ValueError:
        return False
    return True
