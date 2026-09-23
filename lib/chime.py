"""Play the new-mail sound once, however many widget copies ask.

Omarchy runs one copy of the bar widget per monitor, and each copy polls on
its own. Every copy passes its new message IDs here; a shared record of the
IDs already announced, and of the last chime, makes the sound play once per
arrival and at most once per cooldown. Do Not Disturb silences it.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

from common import ROOT, clamp_int, emit, one_line, write_private

USAGE = "usage: you-got-mail chime [--file PATH] [--volume 0-100] [--cooldown SEC] [-- ID ...]"
BUNDLED_SOUND = ROOT / "sounds" / "you-got-mail.oga"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,32}:[A-Za-z0-9_-]{1,512}$")
OPTIONS = ("--file", "--volume", "--cooldown")
DEFAULT_COOLDOWN = 60
MAX_COOLDOWN = 3600
ANNOUNCED_TTL = 24 * 60 * 60
DND_TIMEOUT = 2
PLAY_TIMEOUT = 15


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


def _load_state(path: Path, now: int) -> tuple[dict[str, int], int]:
    """Announced IDs younger than a day, and the last chime; junk reads as empty."""
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
    return announced, int(last) if _is_time(last) else 0


def _claim(ids: list[str], silenced: bool, cooldown: int) -> str | None:
    """Record the IDs under the lock; return why not to play, or None to play."""
    state_dir = _state_dir()
    fd = os.open(state_dir / "chime.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        state_file = state_dir / "chime.json"
        now = int(time.time())
        announced, last = _load_state(state_file, now)
        if all(msg_id in announced for msg_id in ids):
            return "announced"
        for msg_id in ids:
            announced.setdefault(msg_id, now)
        if silenced:
            skipped = "dnd"
        elif now - last < cooldown:
            skipped = "cooldown"
        else:
            skipped, last = None, now
        write_private(state_file, json.dumps({"announced": announced, "lastChime": last}) + "\n")
        return skipped
    finally:
        os.close(fd)


def _players(path: str, volume: int | None) -> list[list[str]]:
    # pw-play defaults to the Music role and takes 0-1.0; paplay takes 0-65536.
    pw_play = ["pw-play", "--media-role", "Notification"]
    paplay = ["paplay", "--property=media.role=event"]
    if volume is not None:
        pw_play += ["--volume", f"{volume / 100:g}"]
        paplay += ["--volume", str(round(volume * 65536 / 100))]
    return [pw_play + [path], paplay + [path]]


def _play(path: str, volume: int | None) -> dict:
    """Try pw-play, then paplay only if pw-play cannot start (never twice).

    If the player rejects a file other than the bundled clip, play the bundled
    clip the same way instead. Not after a timeout: the file played all along.
    """
    for argv in _players(path, volume):
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=PLAY_TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return _fail(f"{argv[0]} timed out")
        except OSError:
            continue
        if proc.returncode != 0:
            stderr = one_line(proc.stderr.decode("utf-8", "replace"))
            detail = f": {stderr}" if stderr else ""
            if path != str(BUNDLED_SOUND):
                return _noted(_play(str(BUNDLED_SOUND), volume), f"{argv[0]} could not play {path}{detail}")
            return _fail(f"{argv[0]} exited {proc.returncode}{detail}")
        return {"ok": True, "played": argv[0]}
    return _fail("no audio player found (pw-play or paplay)")


def _chime(path: str, ids: list[str] | None, opts: dict[str, str]) -> dict:
    """Play `path` now, unless Do Not Disturb or the shared record says not to."""
    if not os.path.isfile(path):  # _sound checked a chosen file, not the bundled clip
        return _fail(f"not a sound file: {path}")
    # Ask before taking the lock, so the lock is never held across the timeout.
    silenced = _dnd_on()
    if ids is None:
        if silenced:
            return {"ok": True, "skipped": "dnd"}
    else:
        cooldown = clamp_int(opts.get("--cooldown"), DEFAULT_COOLDOWN, 0, MAX_COOLDOWN)
        try:
            skipped = _claim(ids, silenced, cooldown)
        except OSError as exc:
            return _fail(f"chime state unavailable: {exc}")
        if skipped:
            return {"ok": True, "skipped": skipped}
    return _play(path, _volume(opts.get("--volume")))


def run(args: list[str]) -> dict:
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
