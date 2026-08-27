"""Shared helpers for You've Got Mail. No secrets are printed."""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy-you-got-mail"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
SECRETS_DIR = CONFIG_DIR / "secrets"

ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
PROVIDERS = ("gmail", "outlook", "fastmail", "imap", "hey")
PAGE_SIZE_MAX = 50
FETCH_CAP = 200
MAX_HTTP_BODY = 2 * 1024 * 1024
MAX_HTTP_ERROR = 64 * 1024
MAX_LOCAL_FILE = 64 * 1024


class ResponseTooLargeError(ValueError):
    def __init__(self, message: str = "response too large") -> None:
        super().__init__(message)


class FileTooLargeError(ValueError):
    def __init__(self, message: str = "file too large") -> None:
        super().__init__(message)


def _declared_length(fp: object) -> int | None:
    headers = getattr(fp, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


def read_http_body(fp: object, limit: int = MAX_HTTP_BODY) -> bytes:
    declared = _declared_length(fp)
    if declared is not None and declared > limit:
        raise ResponseTooLargeError()
    read = getattr(fp, "read")
    data = read(limit + 1)
    if not isinstance(data, (bytes, bytearray)):
        data = bytes(data)
    if len(data) > limit:
        raise ResponseTooLargeError()
    return bytes(data)


def die(message: str, code: int = 0) -> None:
    sys.stdout.write(json.dumps({"ok": False, "error": message}, ensure_ascii=False) + "\n")
    raise SystemExit(code)


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_owned_file(
    path: Path,
    limit: int = MAX_LOCAL_FILE,
    *,
    require_private: bool = False,
) -> bytes | None:
    """Open path once, validate the fd, and read at most *limit* bytes.

    Uses O_NOFOLLOW|O_NONBLOCK so a swapped symlink or FIFO cannot redirect
    or block the read. Missing paths, dangling/final-component symlinks, and
    non-regular files return None. Wrong owner is None unless require_private
    is set, in which case PermissionError is raised (and too-open mode too).
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENXIO, errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOTDIR):
            return None
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if st.st_uid != os.getuid():
            if require_private:
                raise PermissionError("not owned")
            return None
        if require_private and st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise PermissionError("too open")
        if st.st_size > limit:
            raise FileTooLargeError()
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise FileTooLargeError()
        return data
    finally:
        os.close(fd)


def _config_max() -> str | None:
    path = CONFIG_DIR / "config"
    try:
        raw = read_owned_file(path)
    except (OSError, FileTooLargeError, PermissionError):
        return None
    if raw is None:
        return None
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, rest = stripped.partition("=")
        if key.strip().lower() == "max":
            return rest.strip().strip("\"'")
    return None


def clamp_int(raw: object, default: int, lo: int, hi: int) -> int:
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def max_messages() -> int:
    raw = os.environ.get("YOU_GOT_MAIL_MAX") or _config_max() or "25"
    return clamp_int(raw, 25, 1, PAGE_SIZE_MAX)


def fetch_limit(raw: object | None = None) -> int:
    if raw is None:
        raw = os.environ.get("YOU_GOT_MAIL_FETCH") or os.environ.get("YOU_GOT_MAIL_MAX") or "25"
    return clamp_int(raw, 25, 1, FETCH_CAP)


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
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    replaced = False
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = -1
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        replaced = True
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        dirfd = os.open(str(path.parent), flags)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        os.chmod(path, 0o600)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if not replaced:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def load_accounts() -> list[dict]:
    implicit = [{"id": "gmail", "provider": "gmail", "label": "Gmail"}]
    try:
        raw = read_owned_file(ACCOUNTS_FILE)
    except FileTooLargeError:
        die("accounts.json is too large")
    except OSError:
        die("accounts.json is not valid JSON")
    if raw is None:
        return implicit
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        die("accounts.json is not valid JSON")
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, list) or not accounts:
        return implicit
    out = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        acc_id = str(item.get("id") or "")
        provider = str(item.get("provider") or "")
        if not ACCOUNT_ID_RE.match(acc_id) or provider not in PROVIDERS:
            continue
        out.append(item)
    return out or implicit


def save_accounts(accounts: list[dict]) -> None:
    ensure_config_dirs()
    write_private(ACCOUNTS_FILE, json.dumps({"accounts": accounts}, indent=2) + "\n")


def secret_path(account_id: str) -> Path:
    return SECRETS_DIR / f"{account_id}.json"


def load_secret_file(path: Path, account_id: str = "") -> dict:
    label = account_id or path.name
    try:
        raw = read_owned_file(path, require_private=True)
    except FileTooLargeError:
        die(f"secret file for {label} is too large")
    except PermissionError as exc:
        reason = str(exc)
        if "too open" in reason:
            die(f"secret file for {label} is too open; chmod 600 it")
        if "not owned" in reason:
            die(f"secret file for {label} is not owned by you")
        die(f"secret file for {label} is not readable")
    except OSError:
        die(f"secret file for {label} is not readable")
    if raw is None:
        return {}
    parent = path.parent
    if parent.is_symlink():
        die(f"secret directory for {label} is a symlink")
    try:
        pst = parent.stat()
    except OSError:
        die(f"secret directory for {label} is not readable")
    if pst.st_uid != os.getuid() or pst.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        die(f"secret directory for {label} is too open; chmod 700 it")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        die(f"secret file for {label} is not valid JSON")
    return data if isinstance(data, dict) else {}


def load_secret(account_id: str) -> dict:
    return load_secret_file(secret_path(account_id), account_id)


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
