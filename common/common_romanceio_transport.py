"""Job-owned HTTP connections and a shared, cancellable lookup budget."""

import functools
import hashlib
import http.client
import inspect
import io
import math
import threading
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from email.message import Message
from http.cookies import CookieError, SimpleCookie
from typing import List, Optional
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import getproxies, proxy_bypass, urlopen

_state = threading.local()
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class LookupCancelled(RuntimeError):
    """The caller cancelled, or the total lookup deadline expired."""


def parse_retry_after(value):
    """Parse Retry-After delay-seconds or an HTTP-date; ignore malformed values."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if value.isascii() and value.isdigit():
            seconds = float(value)
        else:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                # The obsolete asctime HTTP-date format has no explicit zone;
                # HTTP dates are UTC, never the user's local timezone.
                date = date.replace(tzinfo=timezone.utc)
            seconds = date.timestamp() - time.time()
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except (ValueError, TypeError, OverflowError):
        return None


class HttpRateLimitError(RuntimeError):
    """HTTP 429 from JSON or HTML, with the server's optional retry delay."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = parse_retry_after(retry_after)


class Budget:
    def __init__(self, abort=None, seconds=120, log=None):
        self.abort = abort
        self.deadline = time.monotonic() + seconds
        self.failed_browsers = set()
        self.log = log or (lambda _message: None)

    def is_set(self):
        return (self.abort is not None and self.abort.is_set()) or time.monotonic() >= self.deadline

    def remaining(self, maximum):
        if self.is_set():
            raise LookupCancelled("Lookup cancelled or its total time limit expired")
        return min(maximum, self.deadline - time.monotonic())


def current_budget():
    return getattr(_state, "budget", None)


def remaining(maximum):
    budget = current_budget()
    return budget.remaining(maximum) if budget else maximum


def rate_limit_sleep(seconds):
    """Keep deliberate pacing outside the active-work budget.

    Callers sleep in short increments and check cancellation between them.
    Ordinary retry delays and network/browser work still consume the budget.
    """
    budget = current_budget()
    started = time.monotonic()
    try:
        time.sleep(max(0, seconds))
    finally:
        if budget is not None:
            budget.deadline += time.monotonic() - started


def _read_response(response, timeout):
    """Consume and close an HTTP body with the same limits for every transport."""
    # urllib and http.client both return HTTPResponse for HTTP(S). The socket
    # lives under its buffered file, even when Connection: close has already
    # detached it from HTTPSConnection. Capture it before EOF closes that file.
    raw = getattr(getattr(response, "fp", None), "raw", None)
    sock = getattr(raw, "_sock", None)
    chunks: List[bytes] = []
    count = 0
    try:
        while True:
            read_timeout = remaining(timeout)
            if sock is not None and response.fp is not None:
                sock.settimeout(read_timeout)
            chunk = response.read1(min(65536, _MAX_RESPONSE_BYTES - count + 1))
            remaining(timeout)  # Cancellation/deadline can occur during a read.
            if not chunk:
                # read1() does not raise on early EOF for Content-Length bodies.
                # Chunked framing errors are raised by HTTPResponse itself.
                missing = getattr(response, "length", None)
                if missing not in (None, 0):
                    raise http.client.IncompleteRead(b"".join(chunks), missing)
                return b"".join(chunks)
            count += len(chunk)
            if count > _MAX_RESPONSE_BYTES:
                raise ValueError("Romance.io response exceeds the download size limit")
            chunks.append(chunk)
    finally:
        response.close()


def _open_urllib(request, timeout):
    from .common_romanceio_session import open_with_clearance

    opener = open_with_clearance if request.has_header("Cookie") else urlopen
    response = opener(request, timeout=remaining(timeout))
    return io.BytesIO(_read_response(response, timeout))


class HttpSession:
    """Reuse one TLS connection per job thread; never share it across workers."""

    def __init__(self):
        self.connection: Optional[http.client.HTTPSConnection] = None
        self.used_at = 0.0
        self.bot_cookie = None
        self.user_agent = None
        self.denied_endpoints = set()
        self.clearance_identity = None

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def open(self, request, timeout):
        """Skip repeated endpoint 403s until clearance changes or this job ends."""
        parsed = urlparse(request.full_url)
        endpoint = None
        if parsed.scheme == "https" and parsed.netloc == "www.romance.io":
            parts = parsed.path.strip("/").split("/")
            endpoint = "/" + "/".join(parts[:2] if parts[0] == "json" else parts[:1])
            cookie = request.get_header("Cookie")
            if cookie:
                identity = hashlib.sha256((cookie + "\n" + request.get_header("User-agent", "")).encode()).digest()
                if identity != self.clearance_identity:
                    self.denied_endpoints.clear()
                    self.clearance_identity = identity
            if endpoint in self.denied_endpoints:
                budget = current_budget()
                if budget:
                    budget.log(f"Skipping HTTP {endpoint}: earlier 403 in this job and no new clearance")
                raise HTTPError(request.full_url, 403, "Earlier endpoint 403; awaiting new clearance", Message(), None)
        try:
            return self._open(request, timeout)
        except HTTPError as error:
            if error.code == 403 and endpoint is not None:
                self.denied_endpoints.add(endpoint)
            raise

    def _open(self, request, timeout):
        started = time.monotonic()
        agent = request.get_header("User-agent")
        if self.user_agent != agent:
            self.close()
            self.bot_cookie = None
            self.user_agent = agent
        url = request.full_url
        # Retain urllib's configured proxy/authentication behavior. Direct TLS
        # pooling is only used for this exact origin, with certificate validation.
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "www.romance.io"
            or (getproxies().get("https") and not proxy_bypass(parsed.hostname))
        ):
            return _open_urllib(request, timeout)
        had_connection = self.connection is not None
        try:
            for _ in range(6):
                timeout = remaining(timeout)
                if time.monotonic() - self.used_at > 30:
                    self.close()
                if self.connection is None:
                    # Use the stdlib's verified HTTPS context and ALPN defaults,
                    # matching urllib rather than constructing a different TLS profile.
                    self.connection = http.client.HTTPSConnection("www.romance.io", timeout=timeout)
                self.connection.timeout = timeout
                if self.connection.sock is not None:
                    self.connection.sock.settimeout(timeout)
                path = urlparse(url)
                target = path.path or "/"
                if path.query:
                    target += "?" + path.query
                # urllib normalizes header names before sending. Request itself
                # stores User-agent, which is a different on-wire representation.
                outgoing = {name.title(): value for name, value in request.header_items()}
                outgoing["Connection"] = "keep-alive"
                if self.bot_cookie and self.bot_cookie[1] > time.monotonic():
                    outgoing["Cookie"] = (
                        outgoing.get("Cookie", "")
                        + ("; " if outgoing.get("Cookie") else "")
                        + "__cf_bm="
                        + self.bot_cookie[0]
                    )
                reused = self.connection.sock is not None
                self.connection.request("GET", target, headers=outgoing)
                response = self.connection.getresponse()
                status, headers, reason = response.status, response.headers, response.reason
                # Keep only the site's bot-session cookie in memory. Never
                # persist login/analytics cookies or send it to another origin.
                for value in headers.get_all("Set-Cookie", []):
                    cookie = SimpleCookie()
                    try:
                        cookie.load(value)
                    except CookieError:
                        continue
                    if "__cf_bm" in cookie:
                        item = cookie["__cf_bm"]
                        if (
                            item["domain"].lstrip(".") in ("", "romance.io", "www.romance.io")
                            and item["path"] in ("", "/")
                            and len(item.value) <= 4096
                            and all(33 <= ord(c) <= 126 and c not in ';,\\"' for c in item.value)
                        ):
                            lifetime = 1800.0
                            try:
                                if item["max-age"]:
                                    lifetime = min(lifetime, float(item["max-age"]))
                                elif item["expires"]:
                                    lifetime = min(
                                        lifetime, parsedate_to_datetime(item["expires"]).timestamp() - time.time()
                                    )
                            except (ValueError, TypeError, OverflowError):
                                continue
                            self.bot_cookie = (
                                (item.value, time.monotonic() + lifetime) if item.value and lifetime > 0 else None
                            )
                body = _read_response(response, timeout)
                budget = current_budget()
                if budget:
                    budget.log(
                        f"HTTP {path.path}: status={status}, challenge={headers.get('cf-mitigated') == 'challenge'}, "
                        f"{len(body)} bytes in {time.monotonic() - started:.2f}s, reused connection={reused}"
                    )
                self.used_at = time.monotonic()
                if response.will_close:
                    self.close()
                if status in (301, 302, 303, 307, 308):
                    redirect = urljoin(url, headers.get("Location", ""))
                    if urlparse(redirect).scheme != "https" or urlparse(redirect).netloc != "www.romance.io":
                        raise HTTPError(url, status, "Refusing redirect outside Romance.io", headers, None)
                    url = redirect
                    continue
                data = io.BytesIO(body)
                if status >= 400:
                    raise HTTPError(url, status, reason, headers, data)
                return data
            raise HTTPError(url, 302, "Too many Romance.io redirects", headers, None)
        except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError):
            self.close()
            # An idle keep-alive socket can be closed by the server. Reconnect
            # once for these idempotent GETs; other failures use normal fallback.
            if had_connection:
                return self.open(request, remaining(timeout))
            raise
        except Exception:
            self.close()
            raise


def open_request(request, timeout=30):
    session = getattr(_state, "http", None)
    if session is not None:
        return session.open(request, timeout)
    return _open_urllib(request, timeout)


def job_session(function):
    """Close the pooled connection on normal completion, failure or cancellation."""

    @functools.wraps(function)
    def run(*args, **kwargs):
        if getattr(_state, "http", None) is not None:
            return function(*args, **kwargs)
        session = _state.http = HttpSession()
        try:
            return function(*args, **kwargs)
        finally:
            session.close()
            _state.http = None

    return run


def lookup_budget(function):
    """HTTP and browser work share 120 seconds, excluding rate-limit waits."""
    signature = inspect.signature(function)

    @functools.wraps(function)
    @job_session
    def run(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        previous = current_budget()
        budget = previous or Budget(bound.arguments.get("abort"), log=bound.arguments.get("log_func"))
        bound.arguments["abort"] = budget
        _state.budget = budget
        try:
            if previous is None:
                budget.log("Lookup time limit: 120s of active work; rate-limit waits and final cleanup are additional")
            return function(*bound.args, **bound.kwargs)
        finally:
            _state.budget = previous

    return run
