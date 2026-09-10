"""Share short-lived Cloudflare clearance between the two plugin job processes.

Only the clearance cookie and its browser User-Agent are retained. Never save
login cookies, and never attach these headers outside the exact HTTPS origin.
"""

import json
import math
import os
import tempfile
import time
from typing import Any, Dict
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener

_MAX_CACHE_BYTES = 8192
_MAX_CACHE_AGE = 30 * 60


def _cache_path() -> str:
    base = os.environ.get("CALIBRE_SELENIUM_HOME") or os.path.join(os.path.expanduser("~"), ".calibre_selenium")
    return os.path.join(base, "romanceio-clearance.json")


def _valid_record(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    value, agent, expires = record.get("value"), record.get("user_agent"), record.get("expires")
    return (
        isinstance(value, str)
        and 0 < len(value) <= 4096
        and all(33 <= ord(char) <= 126 and char not in ';,\\"' for char in value)
        and isinstance(agent, str)
        and 0 < len(agent) <= 512
        and all(32 <= ord(char) <= 126 for char in agent)
        and isinstance(expires, (int, float))
        and math.isfinite(expires)
        and time.time() < expires <= time.time() + _MAX_CACHE_AGE + 5
    )


def _load() -> Dict[str, Any]:
    try:
        with open(_cache_path(), encoding="utf-8") as stream:
            text = stream.read(_MAX_CACHE_BYTES + 1)
        if len(text) > _MAX_CACHE_BYTES:
            return {}
        record = json.loads(text)
        return record if _valid_record(record) else {}
    except (OSError, ValueError, TypeError):
        return {}


def clearance_headers(url: str) -> Dict[str, str]:
    """Return cached clearance only for requests to Romance.io itself."""
    try:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.romance.io"
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
        ):
            return {}
    except ValueError:
        return {}
    record = _load()
    if not record:
        return {}
    return {"Cookie": "cf_clearance=" + record["value"], "User-Agent": record["user_agent"]}


def save_clearance(cookies: Any, user_agent: str) -> bool:
    """Atomically retain only a usable cf_clearance cookie for at most 30 minutes."""
    record = None
    for cookie in cookies:
        if cookie.get("name") != "cf_clearance" or cookie.get("domain", "").lstrip(".") not in (
            "romance.io",
            "www.romance.io",
        ):
            continue
        expires = cookie.get("expiry", 0)
        if not isinstance(expires, (int, float)) or not math.isfinite(expires):
            continue
        candidate = {
            "value": cookie.get("value"),
            "user_agent": user_agent,
            "expires": min(expires, time.time() + _MAX_CACHE_AGE),
        }
        if _valid_record(candidate):
            record = candidate
            break
    if record is None:
        return False
    path = _cache_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".clearance-", dir=os.path.dirname(path))
    try:
        # mkstemp creates a private file (0600 on POSIX). Atomic replacement lets
        # readers in other jobs see either the complete old or complete new data.
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return True


def discard_clearance(cookie_header: str) -> None:
    """Discard rejected clearance without removing a different, newer record."""
    record = _load()
    if record and cookie_header == "cf_clearance=" + record["value"]:
        try:
            os.remove(_cache_path())
        except OSError:
            pass


class _ClearanceRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.romance.io"
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise HTTPError(req.full_url, code, "Refusing clearance redirect outside Romance.io", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_with_clearance(request: Any, timeout: float) -> Any:
    """Do not let urllib forward the clearance cookie to a different origin."""
    return build_opener(_ClearanceRedirectHandler()).open(request, timeout=timeout)
