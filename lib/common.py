"""Shared helpers for You've Got Mail. No secrets are printed."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy-you-got-mail"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
SECRETS_DIR = CONFIG_DIR / "secrets"

ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
PROVIDERS = ("gmail", "outlook", "fastmail", "imap", "hey")


def die(message: str, code: int = 0) -> None:
    sys.stdout.write(json.dumps({"ok": False, "error": message}, ensure_ascii=False) + "\n")
    raise SystemExit(code)


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def max_messages() -> int:
    raw = os.environ.get("YOU_GOT_MAIL_MAX", "25")
    try:
        n = int(raw)
    except ValueError:
        return 25
    return max(1, min(50, n))


def one_line(value: str, limit: int = 180) -> str:
    text = re.sub(r"[\u00ad\u034f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]+", "", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def ensure_config_dirs() -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    SECRETS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def load_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.is_file() or ACCOUNTS_FILE.is_symlink():
        return [{"id": "gmail", "provider": "gmail", "label": "Gmail"}]
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        die("accounts.json is not valid JSON")
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, list) or not accounts:
        return [{"id": "gmail", "provider": "gmail", "label": "Gmail"}]
    out = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        acc_id = str(item.get("id") or "")
        provider = str(item.get("provider") or "")
        if not ACCOUNT_ID_RE.match(acc_id) or provider not in PROVIDERS:
            continue
        out.append(item)
    return out or [{"id": "gmail", "provider": "gmail", "label": "Gmail"}]


def save_accounts(accounts: list[dict]) -> None:
    ensure_config_dirs()
    write_private(ACCOUNTS_FILE, json.dumps({"accounts": accounts}, indent=2) + "\n")


def secret_path(account_id: str) -> Path:
    return SECRETS_DIR / f"{account_id}.json"


def load_secret(account_id: str) -> dict:
    path = secret_path(account_id)
    if not path.is_file() or path.is_symlink():
        return {}
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        die(f"secret file for {account_id} is too open; chmod 600 it")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        die(f"secret file for {account_id} is not valid JSON")
    return data if isinstance(data, dict) else {}


def save_secret(account_id: str, data: dict) -> None:
    ensure_config_dirs()
    write_private(secret_path(account_id), json.dumps(data, indent=2) + "\n")


def encode_id(account_id: str, local_id: str) -> str:
    # URL-safe, no padding; local ids can contain slashes (IMAP folders).
    import base64

    blob = base64.urlsafe_b64encode(local_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{account_id}:{blob}"


def decode_id(opaque: str) -> tuple[str, str]:
    import base64

    if ":" not in opaque:
        die("not a message id")
    account_id, blob = opaque.split(":", 1)
    if not ACCOUNT_ID_RE.match(account_id) or not blob:
        die("not a message id")
    pad = "=" * ((4 - len(blob) % 4) % 4)
    try:
        local = base64.urlsafe_b64decode(blob + pad).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        die("not a message id")
    return account_id, local


def provider_path(provider: str) -> Path:
    path = ROOT / "providers" / provider
    if not path.is_file():
        die(f"provider '{provider}' is not installed")
    return path
