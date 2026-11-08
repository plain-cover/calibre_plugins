"""Share short-lived Cloudflare clearance between the two plugin job processes.

Only the clearance cookie and its browser User-Agent are retained. Never save
login cookies, and never attach these headers outside the exact HTTPS origin.
Clearance comes from a browser lookup or from the user completing the
verification window; the embedded engine reuses it only under its own
unmodified User-Agent.
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
# Cloudflare decides how long clearance is honoured and re-challenges when it
# lapses; a lookup that meets a challenge despite saved clearance forgets it.
# This cap only bounds how long a cookie is kept if Cloudflare never says so.
_MAX_CACHE_AGE = 24 * 60 * 60
# After automatic handling fails the check, lookups ask the user instead for this
# long. A judgment call, not a Cloudflare figure: long enough that a bulk job
# does not retry the check book after book, short enough to try again soon.
_AUTOMATIC_CHECK_PAUSE = 60 * 60

# Logged by either browser when Romance.io serves Cloudflare's check.
CHALLENGE_SEEN = "Romance.io is showing a Cloudflare verification page"
# Logged by any browser once it has saved the clearance Cloudflare handed it.
CLEARANCE_SAVED = "Saved temporary Cloudflare clearance; subsequent requests can use direct HTTP"
VERIFY_HINT = (
    "Romance.io asked for a quick Cloudflare verification. Choose 'Verify Romance.io access' from the "
    "Romance.io Fields menu (or the Romance.io metadata source settings), complete the check, then retry."
)


def _base_dir() -> str:
    return os.environ.get("CALIBRE_SELENIUM_HOME") or os.path.join(os.path.expanduser("~"), ".calibre_selenium")


def _cache_path() -> str:
    return os.path.join(_base_dir(), "romanceio-clearance.json")


def _automatic_check_path() -> str:
    return os.path.join(_base_dir(), "romanceio-automatic-check.json")


def note_automatic_check_failed() -> None:
    """Remember that automatic handling could not get past Romance.io's check."""
    try:
        _write({"failed_at": time.time()}, _automatic_check_path())
    except OSError:
        pass


def automatic_check_paused() -> bool:
    """Report whether automatic handling failed the check within the pause, so lookups skip it.

    Each attempt can wait a minute or more on the check and sends Romance.io
    more automated traffic, so lookups ask the user instead until a
    verification succeeds or the pause ends.
    """
    try:
        with open(_automatic_check_path(), encoding="utf-8") as stream:
            failed_at = json.loads(stream.read(256)).get("failed_at")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(failed_at, (int, float)) and 0 <= time.time() - failed_at < _AUTOMATIC_CHECK_PAUSE


def verification_profile_dir() -> str:
    """Chrome profile kept for the verification window only.

    Cloudflare checks a returning browser faster than a brand-new one. It holds
    only what the user does in that window; deleting it simply starts afresh.
    """
    path = os.path.join(_base_dir(), "romanceio-verify-chrome")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


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
        and isinstance(record.get("http_rejected", False), bool)
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
    if not record or record.get("http_rejected"):
        return {}
    return {"Cookie": "cf_clearance=" + record["value"], "User-Agent": record["user_agent"]}


def has_clearance() -> bool:
    """Report whether usable clearance is saved, without revealing it."""
    return bool(_load())


def clearance_browser() -> str:
    """Name the kind of browser the saved clearance belongs to, or "" if none is saved.

    Kept even after direct HTTP has been refused with it, since the browser
    that earned it may still be let through.
    """
    agent = _load().get("user_agent", "")
    if "QtWebEngine/" in agent:
        return "embedded"
    if "Firefox/" in agent:
        return "camoufox"
    if "Chrome/" in agent:
        return "chrome"
    return ""


def browser_clearance(user_agent: str) -> Dict[str, Any]:
    """Return cached clearance for a browser whose own User-Agent earned it.

    Cloudflare binds clearance to the browser that solved the challenge, so a
    different browser (or a disguised one) must not reuse it.
    """
    record = _load()
    if not record or record["user_agent"] != user_agent:
        return {}
    return {"value": record["value"], "expires": record["expires"]}


def save_clearance(cookies: Any, user_agent: str) -> bool:
    """Atomically retain only a usable cf_clearance cookie, for at most a day."""
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
    previous = _load()
    if previous.get("http_rejected") and previous["value"] == record["value"]:
        # Re-saving the same cookie must not resume HTTP requests already refused.
        record["http_rejected"] = True
    _write(record)
    try:
        # A browser has passed the check again, so automatic handling may resume.
        os.remove(_automatic_check_path())
    except OSError:
        pass
    return True


def _write(record: Dict[str, Any], path: str = "") -> None:
    path = path or _cache_path()
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


def forget_clearance(value: str) -> None:
    """Remove clearance Cloudflare no longer honours, unless a newer one replaced it."""
    record = _load()
    if record and record["value"] == value:
        try:
            os.remove(_cache_path())
        except OSError:
            pass


def reject_clearance_for_http(cookie_header: str) -> None:
    """Stop sending clearance that Cloudflare refused over direct HTTP.

    Python's HTTP client is not the browser that earned the clearance, so a
    403 there does not mean the browser engine has lost access. Keep the record
    for the embedded engine, and leave a different, newer record untouched.
    """
    record = _load()
    if record and cookie_header == "cf_clearance=" + record["value"] and not record.get("http_rejected"):
        try:
            _write({**record, "http_rejected": True})
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
