"""Shared helpers for You've Got Mail. No secrets are printed."""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
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
MAX_CLI_OUTPUT = 8 * 1024 * 1024


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
    # ASCII escapes carry any text, a lone surrogate included, to the reader.
    sys.stdout.write(json.dumps(payload) + "\n")


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


PROVIDER_LABELS = {
    "gmail": "Gmail",
    "outlook": "Outlook",
    "fastmail": "Fastmail",
    "imap": "IMAP",
    "hey": "HEY",
}

_SIGNIN_EXPIRED = "sign-in expired. in a terminal:"
_NEEDS_SIGNIN = "needs you to sign in again"
_MISSING_TOOL = "isn't installed for this bar"
_UNREACHABLE = "couldn't reach"

SETUP_GUIDE_URL = "https://github.com/BVisagie/omarchy-you-got-mail/blob/main/docs/ACCOUNTS.md"
_SETUP_ANCHORS = {"gmail": "#gmail", "hey": "#hey"}

_AUTH_NEEDLES = (
    "invalid_grant",
    "token has been expired or revoked",
    "has been expired",
    "has expired due to",
    "token expired",
    "grant has expired",
    "authentication failed",
    "failed to get token",
    "not signed in",
    "not logged in",
    "unauthenticated",
    "unauthorized",
    "invalid credentials",
    "login failed",
    "authenticationfailed",
    "aadsts",
    "http 401",
    "token missing",
)

_MISSING_TOOL_NEEDLES = (
    "not found on path",
    "command not found",
    "gws not found",
    "hey-cli not found",
    "hey not found",
)

_UNREACHABLE_NEEDLES = (
    "tls handshake",
    "could not reach",
    "couldn't reach",
    "connection refused",
    "network is unreachable",
    "temporary failure in name resolution",
    "name or service not known",
    "failed to resolve",
)


def cli_command() -> str:
    """The CLI as you would type it in a terminal.

    The plugin never puts `you-got-mail` on PATH, so the short name is only
    used when it already resolves to this plugin's script.
    """
    script = Path(os.environ.get("YOU_GOT_MAIL_ROOT") or ROOT) / "bin" / "you-got-mail"
    found = shutil.which("you-got-mail")
    if found and os.path.realpath(found) == os.path.realpath(script):
        return "you-got-mail"
    home = os.environ.get("HOME", "").rstrip("/")
    text = str(script)
    if home and text.startswith(home + "/"):
        return "~/" + shlex.quote(text[len(home) + 1 :])
    return shlex.quote(text)


def login_command(provider: str, account_id: str = "") -> str:
    target = account_id or provider or "account"
    return f"{cli_command()} accounts login {shlex.quote(target)}"


def is_auth_failure(raw: str) -> bool:
    text = (raw or "").lower()
    if not text:
        return False
    if _SIGNIN_EXPIRED in text or _NEEDS_SIGNIN in text:
        return True
    if any(needle in text for needle in _AUTH_NEEDLES):
        return True
    return re.search(r"(?:^|[\s:])401(?:\D|$)", text) is not None


def is_missing_tool(raw: str) -> bool:
    text = (raw or "").lower()
    if not text:
        return False
    if _MISSING_TOOL in text:
        return True
    return any(needle in text for needle in _MISSING_TOOL_NEEDLES)


def is_unreachable(raw: str) -> bool:
    text = (raw or "").lower()
    if not text:
        return False
    if _UNREACHABLE in text:
        return True
    return any(needle in text for needle in _UNREACHABLE_NEEDLES)


def needs_sign_in(raw: str) -> bool:
    return is_auth_failure(raw)


def classify_account_error(
    account: dict | str, raw: str, *, provider: str = ""
) -> tuple[str, dict | None]:
    """A short account failure message, plus the action that fixes it, if any.

    The action is `{"kind": "signin", "command": ...}` for an expired or
    missing sign-in, `{"kind": "setup", "url": ...}` for a missing tool, or
    None. The panel draws the action; the tooltip uses `account_error`.
    """
    if isinstance(account, dict):
        acc_id = str(account.get("id") or "")
        provider = provider or str(account.get("provider") or "")
    else:
        acc_id = str(account)
    label = acc_id or provider or "account"
    name = PROVIDER_LABELS.get(provider, provider or label)
    text = one_line(str(raw or "failed"), limit=240)
    prefix = f"{label}: "
    if text.lower().startswith(label.lower() + ":"):
        rest = text.split(":", 1)[1].lstrip()
    else:
        rest = text
    if is_auth_failure(text):
        return (
            f"{prefix}{name} needs you to sign in again.",
            {"kind": "signin", "command": login_command(provider, acc_id)},
        )
    if is_missing_tool(text):
        return (
            f"{prefix}{name} isn't installed for this bar.",
            {"kind": "setup", "url": SETUP_GUIDE_URL + _SETUP_ANCHORS.get(provider, "")},
        )
    if is_unreachable(text):
        return f"{prefix}Couldn't reach {name}.", None
    return prefix + rest, None


def account_error(account: dict | str, raw: str, *, provider: str = "") -> str:
    """Prefix an account failure, and replace OAuth soup with a login command."""
    message, action = classify_account_error(account, raw, provider=provider)
    if action and action["kind"] == "signin":
        return f"{message} In a terminal: {action['command']}"
    if action and action["kind"] == "setup":
        return f"{message} See the setup guide."
    return message


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


# After the program exits, how long to wait for output a process it started
# still holds open. What the program itself wrote is already in the pipe.
EXIT_GRACE = 0.5

# Process groups run_capped started and has not finished with. They are in
# sessions of their own, so a Ctrl+C at the terminal does not reach them;
# stop_active() does.
_ACTIVE_GROUPS: set[int] = set()
_ACTIVE_LOCK = threading.Lock()


def stop_active() -> None:
    with _ACTIVE_LOCK:
        groups = list(_ACTIVE_GROUPS)
    for group in groups:
        try:
            os.killpg(group, signal.SIGKILL)
        except OSError:
            pass


def run_capped(
    cmd: list[str],
    env: dict,
    timeout: float,
    limit: int = MAX_CLI_OUTPUT,
    own_group: bool = True,
) -> subprocess.CompletedProcess:
    """Like subprocess.run(capture_output=True, text=True), with a size cap.

    A program that prints more than `limit` bytes on either stream is killed
    and ResponseTooLargeError is raised, so a runaway reply cannot fill memory.
    """
    # In its own process group, a stop also reaches anything it started. A
    # command run from inside such a group stays in it (own_group=False), so
    # stopping the outer one stops it as well.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=own_group
    )
    if own_group:
        with _ACTIVE_LOCK:
            _ACTIVE_GROUPS.add(proc.pid)

    # The leader is only reaped (proc.wait) after its group is stopped. Until
    # then its PID, which is the group's id, cannot be reused, so the stop
    # cannot reach an unrelated group.
    def stop() -> None:
        if own_group:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError):
                pass
        proc.kill()

    def exited() -> bool:
        try:
            return os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is not None
        except ChildProcessError:
            return True

    output = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    for stream in output:
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    exited_at = None
    try:
        while selector.get_map():
            now = time.monotonic()
            if now > deadline:
                raise subprocess.TimeoutExpired(cmd, timeout)
            if exited_at is None and exited():
                exited_at = now
                if own_group:
                    stop()  # anything it left running
            elif exited_at is not None and now - exited_at > EXIT_GRACE:
                break
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = output[key.fileobj]
                buffer += chunk
                if len(buffer) > limit:
                    stop()
                    proc.wait()
                    raise ResponseTooLargeError(
                        f"printed more than {limit // (1024 * 1024)} MB"
                    )
        while not exited():
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(0.02)
        if own_group:
            stop()  # a helper that closed its pipes may still be running
        returncode = proc.wait()
    except BaseException:
        # A timeout, or an interrupt arriving here: nothing it started runs on.
        if proc.returncode is None:
            stop()
            proc.wait()
        raise
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_GROUPS.discard(proc.pid)
        selector.close()
        proc.stdout.close()
        proc.stderr.close()
    # Invalid UTF-8 stays visible as lone surrogates, so the checks after
    # this refuse an id or link that holds it instead of opening a rewrite.
    return subprocess.CompletedProcess(
        cmd,
        returncode,
        bytes(output[proc.stdout]).decode("utf-8", "surrogateescape"),
        bytes(output[proc.stderr]).decode("utf-8", "surrogateescape"),
    )
