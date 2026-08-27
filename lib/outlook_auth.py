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
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from common import (
    MAX_HTTP_ERROR,
    ResponseTooLargeError,
    read_http_body,
)


SCOPE = "offline_access User.Read Mail.ReadWrite"
AUTH = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(read_http_body(resp).decode())
    except ResponseTooLargeError as exc:
        raise RuntimeError(str(exc)) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("Outlook returned invalid JSON") from None
    except urllib.error.HTTPError as exc:
        try:
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def browser_login(client_id: str, tenant: str = "common") -> dict:
    """Sign in via the system browser and a one-shot http://localhost listener."""
    verifier, challenge = _pkce()
    port = _free_port()
    # Entra treats http://localhost (any port) as a public-client loopback URI.
    redirect = f"http://localhost:{port}/"
    state = secrets.token_urlsafe(16)
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

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if not qs.get("code") and not qs.get("error"):
                self.send_response(204)
                self.end_headers()
                return
            self.server.result = {  # type: ignore[attr-defined]
                "code": (qs.get("code") or [""])[0],
                "state": (qs.get("state") or [""])[0],
                "error": (qs.get("error") or [""])[0],
                "error_description": (qs.get("error_description") or [""])[0],
            }
            self.server.done = True  # type: ignore[attr-defined]
            ok = bool(self.server.result["code"])  # type: ignore[attr-defined]
            body = (
                b"<html><body><p>Signed in. You can close this tab.</p></body></html>"
                if ok
                else b"<html><body><p>Sign-in failed. Return to the terminal.</p></body></html>"
            )
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    try:
        server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise RuntimeError(f"could not listen on localhost: {exc}") from None
    server.result = {}  # type: ignore[attr-defined]
    server.done = False  # type: ignore[attr-defined]
    server.timeout = 0.5

    def _serve() -> None:
        while not server.done:  # type: ignore[attr-defined]
            server.handle_request()

    thread = threading.Thread(target=_serve, daemon=True)
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
    thread.start()
    deadline = time.time() + 300
    while time.time() < deadline and thread.is_alive() and not server.done:  # type: ignore[attr-defined]
        time.sleep(0.2)
    server.done = True  # type: ignore[attr-defined]
    thread.join(timeout=2)
    server.server_close()
    result = getattr(server, "result", {}) or {}
    if result.get("error"):
        raise RuntimeError(result.get("error_description") or result["error"])
    if result.get("state") and result["state"] != state:
        raise RuntimeError("Outlook sign-in state mismatch")
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
