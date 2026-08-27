"""Microsoft device-code login. Tokens are returned to the caller to store."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPE = "offline_access User.Read Mail.ReadWrite"
AUTH = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("error_description") or parsed.get("error") or detail
        except json.JSONDecodeError:
            msg = detail or str(exc)
        raise RuntimeError(msg) from None


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
