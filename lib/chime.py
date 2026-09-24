"""Play the new-mail sound once, however many widget copies ask.

Omarchy runs one copy of the bar widget per monitor, and each copy polls on
its own. Every copy passes its new message IDs here; a shared record of the
IDs already announced, and of the last chime, makes the sound play once per
arrival and at most once per cooldown. Mail that arrives during the cooldown
gets one chime when it ends. A chime the player fails to play is tried again
a few times. Do Not Disturb silences it. `--cancel` drops a chime still
waiting, for when the sound is turned off.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import secrets
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from common import ROOT, clamp_int, emit, one_line, write_private

USAGE = (
    "usage: you-got-mail chime [--file PATH] [--volume 0-100] [--cooldown SEC] [-- ID ...],"
    " or you-got-mail chime --cancel"
)
BUNDLED_SOUND = ROOT / "sounds" / "you-got-mail.oga"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,32}:[A-Za-z0-9_-]{1,512}$")
TOKEN_RE = re.compile(r"[0-9a-f]{16}")
OPTIONS = ("--file", "--volume", "--cooldown")
DEFAULT_COOLDOWN = 60
MAX_COOLDOWN = 3600
ANNOUNCED_TTL = 24 * 60 * 60
DND_TIMEOUT = 2
PLAY_TIMEOUT = 15
PLAY_RETRIES = 3
PLAY_RETRY_DELAY = 30
STALE_AFTER = 60  # a waiting chime this far past due is presumed gone (or is sleeping through a suspend)

_sleep = time.sleep  # the tests wait without waiting


def _fail(message: str) -> dict:
    return {"ok": False, "error": message}


def _parse(args: list[str]) -> tuple[dict[str, str], list[str] | None] | None:
    """Options, and the IDs after `--` (None when there is no `--`)."""
    opts: dict[str, str] = {}
    i = 0
    while i < len(args):
        if args[i] == "--":
            return opts, args[i + 1 :]
        if args[i] not in OPTIONS or i + 1 >= len(args):
            return None
        opts[args[i]] = args[i + 1]
        i += 2
    return opts, None


def _noted(result: dict, fallback: str | None) -> dict:
    """`result`, saying why the bundled clip stood in for the chosen file, if it did."""
    return {**result, "fallback": fallback} if fallback else result


def _sound(raw: str | None) -> tuple[str, str | None]:
    """The file to play, and why the bundled clip replaces `raw`, if it does."""
    if raw is None:
        return str(BUNDLED_SOUND), None
    # Absolute, so a name like "-q.oga" can never read as a player option.
    path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.isfile(path):
        return str(BUNDLED_SOUND), f"not a sound file: {path}"
    if not os.access(path, os.R_OK):
        return str(BUNDLED_SOUND), f"cannot read: {path}"
    return path, None


def _volume(raw: str | None) -> int | None:
    """0-100, or None (the player's default) when omitted or not an integer."""
    volume = clamp_int(raw, -1, 0, 100) if raw is not None else -1
    return volume if volume >= 0 else None


def _dnd_on() -> bool:
    """Only a clean `off` means sound is allowed; any failure counts as silenced."""
    try:
        proc = subprocess.run(
            ["omarchy-shell", "notifications", "isDnd"],
            capture_output=True,
            timeout=DND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return proc.returncode != 0 or proc.stdout.strip() != b"off"


def _state_dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime and os.path.isabs(runtime) and os.path.isdir(runtime):
        path = Path(runtime) / "you-got-mail"
    else:
        cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        path = Path(cache) / "omarchy-you-got-mail"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _is_time(value: object) -> bool:
    # json.loads accepts NaN and Infinity; int() of either would raise.
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pending(raw: object) -> dict | None:
    """The chime waiting for the cooldown to end or to try again; None when there is none or it is junk."""
    if not isinstance(raw, dict):
        return None
    due, token = raw.get("due"), raw.get("token")
    if not _is_time(due) or not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        return None
    return {"due": int(due), "token": token}


def _live(pending: dict | None, now: int) -> bool:
    """Whether a chime is still waiting; one far past due is presumed gone."""
    return pending is not None and pending["due"] >= now - STALE_AFTER


def _load_state(path: Path, now: int) -> tuple[dict[str, int], int, dict | None]:
    """Announced IDs younger than a day, the last chime and the pending one; junk reads as empty."""
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    raw = data.get("announced")
    announced = {
        key: int(when)
        for key, when in (raw.items() if isinstance(raw, dict) else ())
        if _is_time(when) and now - when < ANNOUNCED_TTL
    }
    last = data.get("lastChime")
    # A last chime in the future (the clock went back) reads as now, so no wait
    # is ever longer than the cooldown.
    last = min(int(last), now) if _is_time(last) else 0
    return announced, last, _pending(data.get("pending"))


def _save_state(path: Path, announced: dict[str, int], last: int, pending: dict | None) -> None:
    data: dict[str, object] = {"announced": announced, "lastChime": last}
    if pending:
        data["pending"] = pending
    write_private(path, json.dumps(data) + "\n")


@contextmanager
def _locked() -> Iterator[Path]:
    """Hold the lock shared by every copy; yields the state file it guards."""
    state_dir = _state_dir()
    fd = os.open(state_dir / "chime.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield state_dir / "chime.json"
    finally:
        os.close(fd)


def _claim(ids: list[str], silenced: bool, cooldown: int) -> str | dict | None:
    """Record the IDs under the lock.

    Return why not to play, the pending chime to wait for, or None to play now.
    """
    with _locked() as state_file:
        now = int(time.time())
        announced, last, pending = _load_state(state_file, now)
        if all(msg_id in announced for msg_id in ids):
            return "announced"
        for msg_id in ids:
            announced.setdefault(msg_id, now)
        if silenced:
            claim = "dnd"
        elif now - last < cooldown:
            if _live(pending, now):
                claim = "queued"  # the chime already waiting covers these IDs
            else:
                claim = pending = {"due": last + cooldown, "token": secrets.token_hex(8)}
        else:
            claim, last, pending = None, now, None  # this chime covers anything queued
        _save_state(state_file, announced, last, pending)
        return claim


def _claim_pending(token: str, silenced: bool) -> str | None:
    """Once the wait is over, take the pending chime if it is still this one.

    Return why not to play, or None to play now.
    """
    with _locked() as state_file:
        now = int(time.time())
        announced, last, pending = _load_state(state_file, now)
        if pending is None or pending["token"] != token:
            return "superseded"  # another chime played meanwhile
        if not silenced:
            last = now
        _save_state(state_file, announced, last, None)
        return "dnd" if silenced else None


def _claim_retry() -> dict | None:
    """After a failed play, queue another try under the lock.

    Return the pending chime to wait for, or None when a waiting chime already covers this mail.
    """
    with _locked() as state_file:
        now = int(time.time())
        announced, last, pending = _load_state(state_file, now)
        if _live(pending, now):
            return None
        pending = {"due": now + PLAY_RETRY_DELAY, "token": secrets.token_hex(8)}
        _save_state(state_file, announced, last, pending)
        return pending


def _wait_for(pending: dict) -> str | None:
    """Sleep, holding no lock, until the pending chime is due; then claim it."""
    _sleep(max(0, pending["due"] - time.time()))
    silenced = _dnd_on()  # before the lock, as in _chime
    return _claim_pending(pending["token"], silenced)


def _players(path: str, volume: int | None) -> list[list[str]]:
    # pw-play defaults to the Music role and takes 0-1.0; paplay takes 0-65536.
    pw_play = ["pw-play", "--media-role", "Notification"]
    paplay = ["paplay", "--property=media.role=event"]
    if volume is not None:
        pw_play += ["--volume", f"{volume / 100:g}"]
        paplay += ["--volume", str(round(volume * 65536 / 100))]
    return [pw_play + [path], paplay + [path]]


def _play(path: str, volume: int | None) -> tuple[dict, bool]:
    """Try pw-play, then paplay only if pw-play cannot start (never twice).

    If the player rejects a file other than the bundled clip (exits with an
    error), play the bundled clip the same way instead. Not after a timeout or
    a signal: the file played, or someone stopped it.

    Also say whether trying again later might work: only when the player
    exited with an error, e.g. while the sound server restarts.
    """
    for argv in _players(path, volume):
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=PLAY_TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return _fail(f"{argv[0]} timed out"), False
        except OSError:
            continue
        if proc.returncode != 0:
            stderr = one_line(proc.stderr.decode("utf-8", "replace"))
            detail = f": {stderr}" if stderr else ""
            if proc.returncode > 0 and path != str(BUNDLED_SOUND):
                result, retryable = _play(str(BUNDLED_SOUND), volume)
                return _noted(result, f"{argv[0]} could not play {path}{detail}"), retryable
            return _fail(f"{argv[0]} exited {proc.returncode}{detail}"), proc.returncode > 0
        return {"ok": True, "played": argv[0]}, False
    return _fail("no audio player found (pw-play or paplay)"), False


def _play_retrying(path: str, volume: int | None) -> tuple[dict, int]:
    """Play; while the player exits with an error, wait and try again, at most PLAY_RETRIES times.

    Each retry waits as a pending chime, so new mail meanwhile is queued behind
    it and any chime that plays first supersedes it. Return the last result, or
    why a retry did not play, and how many retries played.
    """
    result, retryable = _play(path, volume)
    retries = 0
    while retryable and retries < PLAY_RETRIES:
        pending = _claim_retry()
        if pending is None:
            break  # the chime already waiting covers this mail
        skipped = _wait_for(pending)
        if skipped:
            return _noted({"ok": True, "skipped": skipped}, result.get("fallback")), retries
        retries += 1
        result, retryable = _play(path, volume)
    return result, retries


def _chime(path: str, ids: list[str] | None, opts: dict[str, str]) -> dict:
    """Play `path` now or when the cooldown ends, unless Do Not Disturb or the shared record says not to.

    With IDs, a play the player fails is tried again later; the manual test is not.
    """
    if not os.path.isfile(path):  # _sound checked a chosen file, not the bundled clip
        return _fail(f"not a sound file: {path}")
    # Ask before taking the lock, so the lock is never held across the timeout.
    silenced = _dnd_on()
    volume = _volume(opts.get("--volume"))
    if ids is None:
        return {"ok": True, "skipped": "dnd"} if silenced else _play(path, volume)[0]
    cooldown = clamp_int(opts.get("--cooldown"), DEFAULT_COOLDOWN, 0, MAX_COOLDOWN)
    try:
        claim = _claim(ids, silenced, cooldown)
        deferred = isinstance(claim, dict)
        skipped = _wait_for(claim) if deferred else claim
        if skipped:
            return {"ok": True, "skipped": skipped}
        result, retries = _play_retrying(path, volume)  # _play catches the players' OSError
    except OSError as exc:
        return _fail(f"chime state unavailable: {exc}")
    if deferred:
        result = {**result, "deferred": True}
    return {**result, "retries": retries} if retries else result


def _cancel() -> dict:
    """Drop the chime waiting for the cooldown or a retry, so its waiter finds it superseded.

    Keeps the announced IDs and the last chime. Plays nothing and asks no Do Not Disturb.
    """
    try:
        with _locked() as state_file:
            announced, last, pending = _load_state(state_file, int(time.time()))
            if pending is None:
                return {"ok": True, "cancelled": False}
            _save_state(state_file, announced, last, None)
    except OSError as exc:
        return _fail(f"chime state unavailable: {exc}")
    return {"ok": True, "cancelled": True}


def run(args: list[str]) -> dict:
    if "--cancel" in args:
        # A flag on its own: with any option or `--` it is a usage error.
        return _cancel() if args == ["--cancel"] else _fail(USAGE)
    parsed = _parse(args)
    if parsed is None:
        return _fail(USAGE)
    opts, ids = parsed
    if ids is not None:
        ids = [msg_id for msg_id in ids if ID_RE.fullmatch(msg_id)]
        if not ids:
            return _fail("no valid message IDs")
    path, fallback = _sound(opts.get("--file"))
    return _noted(_chime(path, ids, opts), fallback)


def main(args: list[str]) -> None:
    emit(run(args))
