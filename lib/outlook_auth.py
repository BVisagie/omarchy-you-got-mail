"""Microsoft Graph login. Tokens are returned to the caller to store.

Prefers a localhost PKCE browser sign-in (works for personal Outlook.com).
Device-code login remains as a fallback if the browser flow cannot bind.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import webbrowser

from common import (
    MAX_HTTP_ERROR,
    ResponseTooLargeError,
    UnexpectedUrlError,
    open_https,
    read_http_body,
)


SCOPE = "offline_access User.Read Mail.ReadWrite"
LOGIN_HOST = "login.microsoftonline.com"
AUTH = "https://" + LOGIN_HOST + "/{tenant}/oauth2/v2.0"


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        with open_https(url, LOGIN_HOST, method="POST", data=body, headers=headers) as resp:
            return json.loads(read_http_body(resp).decode())
    except UnexpectedUrlError:
        raise RuntimeError(f"Outlook sign-in URL is not on https://{LOGIN_HOST}") from None
    except ResponseTooLargeError as exc:
        raise RuntimeError(str(exc)) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("Outlook returned invalid JSON") from None
    except urllib.error.HTTPError as exc:
        try:
            # A redirect is not followed, and its body (often a page of HTML)
            # is not read or shown: the status says enough.
            if 300 <= exc.code < 400:
                raise RuntimeError(f"Outlook sign-in HTTP {exc.code}") from None
            try:
                detail = read_http_body(exc, MAX_HTTP_ERROR).decode("utf-8")
            except ResponseTooLargeError as err:
                raise RuntimeError(str(err)) from None
            except UnicodeDecodeError:
                raise RuntimeError(str(exc)) from None
            try:
                parsed = json.loads(detail)
                msg = parsed.get("error_description") or parsed.get("error") or detail
            except json.JSONDecodeError:
                msg = detail or str(exc)
            raise RuntimeError(msg) from None
        finally:
            try:
                exc.close()
            except OSError:
                pass


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


# How long the browser sign-in waits for Microsoft's redirect back.
LOGIN_TIMEOUT = 300
# A connection to the listener that goes this long without a byte is dropped.
CONNECTION_TIMEOUT = 10

_SIGNED_IN = b"<html><body><p>Signed in. You can close this tab.</p></body></html>"
_FAILED = b"<html><body><p>Sign-in failed. Return to the terminal.</p></body></html>"
_NOT_THIS = b"<html><body><p>Not this sign-in.</p></body></html>"


def _same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class _CallbackServer(http.server.ThreadingHTTPServer):
    """One-shot listener for the redirect back to http://localhost:<port>/.

    Any local program can reach this port, so only a request to / carrying
    this sign-in's state ends the wait. Everything else is refused and the
    listener keeps waiting. Each connection has its own thread and a read
    timeout, so one that never finishes its request cannot hold the others.
    """

    daemon_threads = True

    def __init__(self, state: str) -> None:
        # Port 0: the listener holds its port from the start, so no other
        # program can take it between choosing a port and listening on it.
        super().__init__(("127.0.0.1", 0), _CallbackHandler)
        self.state = state
        self.result: dict[str, str] = {}
        self.finished = threading.Event()
        self._lock = threading.Lock()

    def take(self, result: dict[str, str]) -> None:
        with self._lock:
            if not self.finished.is_set():
                self.result = result
                self.finished.set()

    def handle_error(self, request: object, client_address: object) -> None:
        # socketserver prints a traceback when a connection breaks mid-reply;
        # any local program could put those in the sign-in terminal.
        return


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    timeout = CONNECTION_TIMEOUT

    def do_GET(self) -> None:  # noqa: N802
        server: _CallbackServer = self.server  # type: ignore[assignment]
        parsed = urllib.parse.urlsplit(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        result = {
            "code": (qs.get("code") or [""])[0],
            "state": (qs.get("state") or [""])[0],
            "error": (qs.get("error") or [""])[0],
            "error_description": (qs.get("error_description") or [""])[0],
        }
        if (
            parsed.path != "/"
            or not (result["code"] or result["error"])
            or not _same(result["state"], server.state)
        ):
            self._reply(400, _NOT_THIS)
            return
        ok = bool(result["code"]) and not result["error"]
        try:
            # The page first, so the browser has it before the listener closes.
            self._reply(200 if ok else 400, _SIGNED_IN if ok else _FAILED)
        finally:
            server.take(result)

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def browser_login(client_id: str, tenant: str = "common") -> dict:
    """Sign in via the system browser and a one-shot http://localhost listener."""
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    try:
        server = _CallbackServer(state)
    except OSError as exc:
        raise RuntimeError(f"could not listen on localhost: {exc}") from None
    port = int(server.server_address[1])
    # Entra treats http://localhost (any port) as a public-client loopback URI.
    redirect = f"http://localhost:{port}/"
    base = AUTH.format(tenant=tenant or "common")
    authorize = (
        f"{base}/authorize?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect,
                "response_mode": "query",
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
    )

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    try:
        sys.stderr.write(
            "\nOpen this URL if the browser does not appear:\n"
            f"  {authorize}\n\n"
            "Sign in as the Outlook mailbox you want to add.\n"
        )
        sys.stderr.flush()
        try:
            webbrowser.open(authorize)
        except Exception:
            pass
        server.finished.wait(LOGIN_TIMEOUT)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    result = dict(server.result)
    # The listener takes only a matching state; checked again, as it is the
    # one thing that ties this redirect to this sign-in.
    if not result or not _same(result.get("state", ""), state):
        raise RuntimeError("Outlook sign-in timed out or was cancelled")
    if result.get("error"):
        raise RuntimeError(result.get("error_description") or result["error"])
    code = result.get("code") or ""
    if not code:
        raise RuntimeError("Outlook sign-in timed out or was cancelled")
    token = _post(
        f"{base}/token",
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect,
            "code_verifier": verifier,
            "scope": SCOPE,
        },
    )
    if token.get("refresh_token"):
        return token
    raise RuntimeError("login succeeded but no refresh token was returned")


def graph_login(client_id: str, tenant: str = "common") -> dict:
    try:
        return browser_login(client_id, tenant)
    except RuntimeError as exc:
        sys.stderr.write(f"Browser sign-in failed ({exc}); trying device login.\n")
        sys.stderr.flush()
        return device_login(client_id, tenant)


def device_login(client_id: str, tenant: str = "common") -> dict:
    base = AUTH.format(tenant=tenant or "common")
    started = _post(
        f"{base}/devicecode",
        {"client_id": client_id, "scope": SCOPE},
    )
    sys.stderr.write(
        "\n"
        f"{started.get('message') or 'Open the verification URL and enter the code.'}\n"
        f"URL:  {started.get('verification_uri')}\n"
        f"Code: {started.get('user_code')}\n\n"
    )
    sys.stderr.flush()
    interval = int(started.get("interval") or 5)
    expires = int(started.get("expires_in") or 900)
    device_code = started["device_code"]
    deadline = time.time() + expires
    while time.time() < deadline:
        time.sleep(interval)
        try:
            token = _post(
                f"{base}/token",
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device_code,
                },
            )
        except RuntimeError as exc:
            text = str(exc).lower()
            if "authorization_pending" in text:
                continue
            if "slow_down" in text:
                interval += 5
                continue
            raise
        if token.get("refresh_token"):
            return token
        raise RuntimeError("login succeeded but no refresh token was returned")
    raise RuntimeError("device login timed out")


def refresh_access_token(client_id: str, refresh_token: str, tenant: str = "common") -> dict:
    base = AUTH.format(tenant=tenant or "common")
    token = _post(
        f"{base}/token",
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": SCOPE,
        },
    )
    if not token.get("access_token"):
        raise RuntimeError("could not refresh Outlook access token")
    return token
