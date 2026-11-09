"""Fetch Romance.io with the Camoufox browser that calibre 9.16+ provides.

calibre downloads Camoufox, a Firefox build meant for sites that put an anti-bot
check in front of their pages, for its own Amazon source and news recipes. It
is used here only when calibre has already installed it: installing means
downloading hundreds of megabytes, which no lookup should start on its own.

Nothing here clicks or solves Romance.io's Cloudflare check. When the check is
served, Camoufox is left on it while its scripts run, as an ordinary browser
would be, and the page is loaded once more only after Cloudflare has handed
over its clearance cookie. calibre's warmup, which visits unrelated sites first
to look like someone browsing, and its humanized typing are not used.

Runs inside the supervised browser worker, like the other browsers.
"""

import html as html_module
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# Statuses Cloudflare serves its check with: 403 for the check itself, 429 when
# it thinks requests come too often.
_CHECK_STATUSES = (403, 429)
# While Camoufox waits on the check: how often to look for clearance, how
# often to say it is still waiting, and how much time to keep for loading the
# page again once Cloudflare accepts it.
_CHECK_POLL_SECONDS = 1
_CHECK_REPORT_SECONDS = 15
_RELOAD_RESERVE_SECONDS = 5
# Longest single page load. Cloudflare's check page can keep a load going for
# all of it, and clearance is only looked for once the load ends.
_OPEN_TIMEOUT = 15
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def installed_camoufox() -> Optional[Any]:
    """Return calibre's existing Camoufox install, or None, without downloading anything."""
    try:
        from calibre.web.automate import download_deps
    except ImportError:
        return None  # calibre before 9.16
    try:
        system = download_deps.system_camoufox()
        if system is not None:
            return download_deps.Install(system.binary, download_deps.system_camoufox_version(system))
        installer = download_deps.camoufox_installer
        if not os.path.isdir(installer.install_dir):
            return None
        with open(os.path.join(installer.install_dir, download_deps.METADATA_FILE_NAME), "rb") as stream:
            version = json.loads(stream.read(64 * 1024) or b"{}").get("version", "")
        if not installer.is_installed(version):
            return None
        return download_deps.Install(installer.payload_path(installer.version_dir(version)), version)
    except Exception:  # pylint: disable=broad-except
        # Any surprise in calibre's install records means not using Camoufox
        return None


def camoufox_available() -> bool:
    return installed_camoufox() is not None


def camoufox_missing_hint() -> str:
    """Say how to get Camoufox, for a lookup that met the check without it."""
    try:
        from calibre.web.automate import download_deps  # noqa: F401  # pylint: disable=unused-import
    except ImportError:
        return "Calibre 9.17 or later can often get past Romance.io's check by itself with its Camoufox browser"
    # calibre downloads it, with no prompt, when a metadata download starts with a
    # source that needs it enabled, which its Amazon.com source is by default.
    return (
        "Calibre's Camoufox browser, which can often get past Romance.io's check, is not installed yet. Calibre "
        "installs it the first time Download metadata runs with its Amazon.com source enabled (the default)."
    )


# The metadata source plugin, which runs inside calibre's metadata download
METADATA_SOURCE_PLUGIN = "romanceio"
# About the longest a lookup that meets the check can need with Camoufox:
# about 20 seconds to start, then as long as Cloudflare takes.
_METADATA_WAIT_NEEDED = 90


def metadata_wait_hint() -> str:
    """Say how to keep calibre from stopping the source while Camoufox works, if it would."""
    try:
        from calibre.ebooks.metadata.sources.prefs import msprefs

        wait = int(msprefs["wait_after_first_identify_result"])
    except Exception:  # pylint: disable=broad-except
        return ""  # Outside calibre's metadata download, or a calibre without the setting
    if wait >= _METADATA_WAIT_NEEDED:
        return ""
    return (
        f"Calibre stops waiting for slower sources {wait} seconds after the first source answers, and Camoufox "
        f"can need up to about {_METADATA_WAIT_NEEDED} seconds to get past Romance.io's check. If Romance.io "
        f"results are missing, set 'Max. time to wait after first match is found' to {_METADATA_WAIT_NEEDED} "
        "seconds in Preferences > Metadata download."
    )


def _default_browser(install: Any) -> Any:
    from calibre.web.automate.recipes import Browser

    # One tab, no images, and none of the warmup visits to other sites.
    return Browser(warmup=False, block_images=True, max_tabs=1, install=install)


def _clearance_value(cookies: List[Dict[str, Any]]) -> str:
    for cookie in cookies:
        if cookie.get("name") == "cf_clearance" and str(cookie.get("domain", "")).lstrip(".").endswith("romance.io"):
            return str(cookie.get("value") or "")
    return ""


def _as_document(response: Any) -> Tuple[str, bool]:
    """The page as the other browsers hand it back, and whether it is JSON.

    Chrome shows JSON wrapped in a <pre>, which is what callers parse, while
    Camoufox hands back the bytes the server sent.
    """
    body = response.read().decode("utf-8", errors="replace")
    content_type = str(response.headers.get("Content-Type") or "").partition(";")[0].strip().lower()
    if content_type == "application/json":
        return f"<html><head></head><body><pre>{html_module.escape(body)}</pre></body></html>", True
    return body, False


def _json_complete(document: str) -> bool:
    # Unlike a rendered page, JSON from Camoufox is the whole response, so even
    # an empty search result, too short to pass for a finished page, is complete.
    from .common_romanceio_webengine import _JsonText

    parser = _JsonText()
    parser.feed(document)
    try:
        return isinstance(json.loads("".join(parser.parts)), (dict, list))
    except (ValueError, TypeError):
        return False


def _page_title(document: str) -> str:
    match = _TITLE.search(document)
    return html_module.unescape(match.group(1)).strip() if match else ""


def fetch_page_with_camoufox(
    request: Dict[str, Any],
    log: Callable[[str], None],
    browser_factory: Optional[Callable[[Any], Any]] = None,
    on_done: Optional[Callable[..., None]] = None,
) -> str:
    """Load request's URL, or its search fallback, in Camoufox and return the validated page.

    on_done, if given, gets the page, or None and the error, before Camoufox
    is shut down, so the caller need not wait for that.
    """
    from .common_romanceio_fetch_helper import BrowserFetchError

    install = installed_camoufox()
    if install is None:
        raise BrowserFetchError("Calibre's Camoufox browser is not installed")
    started = time.monotonic()
    deadline = started + request.get("max_wait", 30)
    log(f"Starting calibre's Camoufox browser {install.version} (no window)")
    browser = (browser_factory or _default_browser)(install)
    try:
        try:
            page = _navigate(browser, request, log, started, deadline)
        except BrowserFetchError as error:
            failure = error
        except Exception as error:  # pylint: disable=broad-except
            failure = BrowserFetchError(f"Camoufox navigation failed ({type(error).__name__})")
            failure.__cause__ = error
        else:
            if on_done:
                on_done(page)
            return page
        if on_done:
            on_done(None, failure)
        raise failure
    finally:
        try:
            browser.shutdown()
        except Exception:  # pylint: disable=broad-except
            pass  # The supervisor reaps whatever is left.


def _navigate(
    browser: Any, request: Dict[str, Any], log: Callable[[str], None], started: float, deadline: float
) -> str:
    from urllib.error import URLError

    from .common_romanceio_fetch_helper import BrowserFetchError
    from .common_romanceio_session import CHALLENGE_SEEN, CLEARANCE_SAVED, browser_clearance, save_clearance
    from .common_romanceio_webengine import browser_requests, page_failure, page_ready

    challenge_seen = False
    last_failure = "Camoufox did not return validated content within its navigation budget"
    user_agent = browser.user_agent()
    log(f"Camoufox ready after {time.monotonic() - started:.0f}s")
    saved = browser_clearance(user_agent)
    if saved:
        browser.set_simple_cookie("cf_clearance", saved["value"], domain=".romance.io")
        log("Using saved Romance.io verification in Camoufox")
    for route in browser_requests(request):
        log(f"Navigating Camoufox to {route['url']}")
        waited_for_check = False
        while time.monotonic() < deadline:
            opened = time.monotonic()
            try:
                with browser.open(
                    route["url"], timeout=max(1, min(_OPEN_TIMEOUT, deadline - time.monotonic()))
                ) as response:
                    document, is_json = _as_document(response)
            except URLError as error:
                status = getattr(error, "code", None)
                if status == 404 and route.get("not_found_marker"):
                    # calibre does not hand back the body of an error page, so
                    # report the missing book in the words callers look for.
                    log("Romance.io says this page does not exist (HTTP 404)")
                    # Callers search for the words as they are, apostrophe included.
                    marker = html_module.escape(route["not_found_marker"], quote=False)
                    return f"<html><head></head><body><p>{marker}</p></body></html>"
                if status not in _CHECK_STATUSES:
                    last_failure = f"Camoufox could not load the page (HTTP {status or 'error'})"
                    break
                if not challenge_seen:
                    challenge_seen = True
                    log(CHALLENGE_SEEN)
                    log(f"Camoufox took {time.monotonic() - opened:.0f}s to load the check")
                last_failure = "Camoufox verification challenge did not clear within its navigation budget"
                if waited_for_check:
                    break  # Cloudflare's clearance did not get the page either
                waited_for_check = True
                if not _wait_for_clearance(browser, log, opened, deadline):
                    break
                continue
            failure = page_failure(document, route)
            if failure:
                log(failure)
                last_failure = failure
                break
            if _json_complete(document) if is_json else page_ready(document, _page_title(document), route):
                log(f"Camoufox page validated ({len(document)} characters)")
                cookies = [
                    {**cookie, "expiry": cookie.get("expires", 0)}
                    for cookie in browser.cookies()
                    if cookie.get("name") == "cf_clearance"
                ]
                if challenge_seen and cookies and save_clearance(cookies, user_agent):
                    log(CLEARANCE_SAVED)
                return document
            last_failure = "Camoufox did not return validated content"
            break
        if challenge_seen:
            break  # The other route would only meet the same check.
    raise BrowserFetchError(last_failure)


def _wait_for_clearance(browser: Any, log: Callable[[str], None], check_started: float, deadline: float) -> bool:
    """Leave Camoufox on the check until Cloudflare hands over a new clearance.

    Waits as long as the navigation budget allows, keeping enough of it to
    load the page once more.
    """
    before = _clearance_value(browser.cookies())
    log("Leaving Camoufox on the check while Cloudflare runs it")
    wait_until = deadline - _RELOAD_RESERVE_SECONDS
    next_report = time.monotonic() + _CHECK_REPORT_SECONDS
    while time.monotonic() < wait_until:
        time.sleep(_CHECK_POLL_SECONDS)
        current = _clearance_value(browser.cookies())
        if current and current != before:
            log(
                f"Cloudflare accepted Camoufox after {time.monotonic() - check_started:.0f}s on the check; "
                "loading the page again"
            )
            return True
        if time.monotonic() >= next_report:
            next_report += _CHECK_REPORT_SECONDS
            log(f"Still on Cloudflare's check in Camoufox ({time.monotonic() - check_started:.0f}s so far)")
    log(f"Cloudflare did not accept Camoufox after {time.monotonic() - check_started:.0f}s on the check")
    return False
