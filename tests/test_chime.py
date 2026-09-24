from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Callable
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from support import ROOT

import chime

T0 = 1_800_000_000
DAY = 24 * 60 * 60
REAL_RUN = subprocess.run  # the tests patch subprocess.run itself
BUNDLED = str(ROOT / "sounds" / "you-got-mail.oga")
TOKEN = "0123456789abcdef"
TOKEN_RE = re.compile(r"[0-9a-f]{16}")


def _workdir() -> Path:
    root = ROOT / ".test-tmp"
    root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(dir=root))


class FakeRun:
    """Stands in for subprocess.run: no audio, no real omarchy-shell."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.dnd: object = b"off\n"
        self.dnd_code = 0
        self.missing: set[str] = set()
        self.player_code = 0
        self.player_codes: list[int] = []  # exit codes for the next player runs, then player_code
        self.player_stderr = b"boom\n"
        self.player_error: Exception | None = None
        self.unplayable: set[str] = set()  # files the player rejects with exit 1
        self.while_playing: Callable[[], None] | None = None  # runs as each player starts

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append((list(argv), kwargs))
        name = argv[0]
        if name in self.missing:
            raise FileNotFoundError(2, "No such file or directory", name)
        if name == "omarchy-shell":
            if isinstance(self.dnd, Exception):
                raise self.dnd
            return subprocess.CompletedProcess(argv, self.dnd_code, self.dnd, b"")
        if self.while_playing is not None:
            self.while_playing()
        if self.player_error is not None:
            raise self.player_error
        if argv[-1] in self.unplayable:
            code = 1
        else:
            code = self.player_codes.pop(0) if self.player_codes else self.player_code
        return subprocess.CompletedProcess(argv, code, b"", self.player_stderr)

    @property
    def players(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls if argv[0] != "omarchy-shell"]

    def kwargs_for(self, name: str) -> dict:
        return next(kwargs for argv, kwargs in self.calls if argv[0] == name)


class ChimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.runtime = self.tmp / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir(mode=0o700)
        self.sound = self.home / "sound.oga"
        self.sound.write_bytes(b"OggS")
        env = patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.runtime), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("XDG_CACHE_HOME", None)
        self.fake = FakeRun()
        run = patch.object(chime.subprocess, "run", self.fake)
        run.start()
        self.addCleanup(run.stop)
        self.now = T0
        clock = patch.object(chime.time, "time", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.sleeps: list[float] = []
        self.while_waiting: Callable[[], None] | None = None
        sleep = patch.object(chime, "_sleep", self.fake_sleep)
        sleep.start()
        self.addCleanup(sleep.stop)

    def fake_sleep(self, seconds: float) -> None:
        """Wait without waiting: run `while_waiting` (once), then move the clock on."""
        self.assert_unlocked()
        self.sleeps.append(seconds)
        end = self.now + seconds
        action, self.while_waiting = self.while_waiting, None
        if action is not None:
            action()
        self.now = max(self.now, end)  # unless the action moved the clock further

    def assert_unlocked(self) -> None:
        fd = os.open(self.state_dir / "chime.lock", os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.fail("the chime lock is held during a wait or a play")
        finally:
            os.close(fd)

    @property
    def state_dir(self) -> Path:
        return self.runtime / "you-got-mail"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "chime.json"

    def state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def write_state(self, data: object) -> None:
        self.state_dir.mkdir(mode=0o700, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data)
        self.state_file.write_text(text, encoding="utf-8")

    def chime(self, *ids: str, cooldown: str = "60", volume: str | None = "100", file: str | None = None) -> dict:
        args = ["--cooldown", cooldown]
        if volume is not None:
            args += ["--volume", volume]
        if file is not None:
            args += ["--file", file]
        return chime.run([*args, "--", *ids])


class AnnouncedTests(ChimeTestCase):
    def test_first_call_plays_and_records_ids_and_chime_time(self) -> None:
        self.assertEqual(self.chime("work:abc", "home:def"), {"ok": True, "played": "pw-play"})
        self.assertEqual(len(self.fake.players), 1)
        self.assertEqual(self.state(), {"announced": {"work:abc": T0, "home:def": T0}, "lastChime": T0})

    def test_second_call_with_same_ids_spawns_no_player(self) -> None:
        self.chime("work:abc", "home:def")
        self.now += 3600
        self.assertEqual(self.chime("home:def", "work:abc"), {"ok": True, "skipped": "announced"})
        self.assertEqual(len(self.fake.players), 1)

    def test_some_new_and_some_announced_ids_play(self) -> None:
        self.chime("work:abc")
        self.now += 3600
        self.assertEqual(self.chime("work:abc", "work:new"), {"ok": True, "played": "pw-play"})
        self.assertEqual(len(self.fake.players), 2)
        self.assertEqual(self.state()["announced"], {"work:abc": T0, "work:new": T0 + 3600})

    def test_announced_ids_older_than_a_day_are_dropped(self) -> None:
        self.write_state(
            {"announced": {"work:old": T0 - DAY - 1, "work:recent": T0 - 3600}, "lastChime": T0 - 7200}
        )
        self.assertEqual(self.chime("work:new"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.state()["announced"], {"work:recent": T0 - 3600, "work:new": T0})

    def test_malformed_state_is_treated_as_empty(self) -> None:
        for text in (
            "not json",
            "[]",
            '{"announced": [], "lastChime": "soon"}',
            '{"announced": {"work:abc": "x"}}',
            '{"announced": {"work:abc": Infinity, "work:b": NaN}, "lastChime": -Infinity}',
        ):
            with self.subTest(text=text):
                self.fake.calls.clear()
                self.write_state(text)
                self.assertEqual(self.chime("work:abc"), {"ok": True, "played": "pw-play"})
                self.assertEqual(self.state(), {"announced": {"work:abc": T0}, "lastChime": T0})

    def test_unreadable_bytes_in_state_are_treated_as_empty(self) -> None:
        self.state_dir.mkdir(mode=0o700)
        self.state_file.write_bytes(b"\xff\xfe\x00")
        self.assertEqual(self.chime("work:abc"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.state()["announced"], {"work:abc": T0})

    def test_waits_for_another_copy_holding_the_lock(self) -> None:
        self.state_dir.mkdir(mode=0o700)
        results: list[dict] = []
        with open(self.state_dir / "chime.lock", "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            worker = threading.Thread(target=lambda: results.append(self.chime("work:abc")))
            worker.start()
            worker.join(timeout=0.3)
            self.assertTrue(worker.is_alive())
            self.assertFalse(self.state_file.exists())
            self.assertEqual(self.fake.players, [])
        worker.join(timeout=5)
        self.assertEqual(results, [{"ok": True, "played": "pw-play"}])

    def test_state_is_private(self) -> None:
        self.chime("work:abc")
        self.assertEqual(self.state_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.state_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(p.name for p in self.state_dir.iterdir()), ["chime.json", "chime.lock"])


class CooldownTests(ChimeTestCase):
    def test_cooldown_applies_across_calls(self) -> None:
        self.assertEqual(self.chime("work:a"), {"ok": True, "played": "pw-play"})
        self.now += 59
        self.assertEqual(self.chime("work:b"), {"ok": True, "played": "pw-play", "deferred": True})
        self.assertEqual(self.sleeps, [1])
        self.assertEqual(len(self.fake.players), 2)
        self.assertEqual(self.state(), {"announced": {"work:a": T0, "work:b": T0 + 59}, "lastChime": T0 + 60})
        self.now += 60
        self.assertEqual(self.chime("work:c"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.sleeps, [1])
        self.assertEqual(self.state()["lastChime"], T0 + 120)

    def test_cooldown_is_clamped_and_defaults_to_sixty(self) -> None:
        cases = [("99999", 3600), ("-5", 0), ("0", 0), ("soon", 60), ("", 60)]
        for raw, seconds in cases:
            with self.subTest(raw=raw):
                self.now = T0
                self.sleeps.clear()
                self.write_state({"announced": {}, "lastChime": T0 - seconds})
                self.assertEqual(self.chime("work:a", cooldown=raw), {"ok": True, "played": "pw-play"})
                self.assertEqual(self.sleeps, [])
                if seconds:
                    self.write_state({"announced": {}, "lastChime": T0 - seconds + 1})
                    self.assertEqual(
                        self.chime("work:a", cooldown=raw), {"ok": True, "played": "pw-play", "deferred": True}
                    )
                    self.assertEqual(self.sleeps, [1])

    def test_omitted_cooldown_is_sixty(self) -> None:
        self.write_state({"announced": {}, "lastChime": T0 - 60})
        self.assertEqual(chime.run(["--", "work:a"]), {"ok": True, "played": "pw-play"})
        self.write_state({"announced": {}, "lastChime": T0 - 59})
        self.assertEqual(chime.run(["--", "work:b"]), {"ok": True, "played": "pw-play", "deferred": True})
        self.assertEqual(self.sleeps, [1])

    def test_cooldown_zero_never_waits(self) -> None:
        self.write_state({"announced": {}, "lastChime": T0, "pending": {"due": T0 + 30, "token": TOKEN}})
        self.assertEqual(self.chime("work:a", cooldown="0"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.state(), {"announced": {"work:a": T0}, "lastChime": T0})

    def test_a_last_chime_in_the_future_reads_as_now(self) -> None:
        # The clock went back: wait one cooldown at most, and never with cooldown 0.
        self.write_state({"announced": {}, "lastChime": T0 + 7200})
        self.assertEqual(self.chime("work:a", cooldown="0"), {"ok": True, "played": "pw-play"})
        self.write_state({"announced": {}, "lastChime": T0 + 7200})
        self.assertEqual(self.chime("work:b"), {"ok": True, "played": "pw-play", "deferred": True})
        self.assertEqual(self.sleeps, [60])
        self.assertEqual(self.state()["lastChime"], T0 + 60)


class DeferredChimeTests(ChimeTestCase):
    """Mail inside the cooldown gets one chime when it ends."""

    DEFERRED = {"ok": True, "played": "pw-play", "deferred": True}

    def setUp(self) -> None:
        super().setUp()
        # The last chime was 10 s ago, so the 60 s cooldown ends at T0 + 50.
        self.write_state({"announced": {"work:a": T0 - 10}, "lastChime": T0 - 10})

    def test_mail_inside_the_cooldown_plays_once_when_it_ends(self) -> None:
        pending: list[dict] = []
        self.while_waiting = lambda: pending.append(self.state()["pending"])
        self.assertEqual(self.chime("work:b"), self.DEFERRED)
        self.assertEqual(self.sleeps, [50])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["due"], T0 + 50)
        self.assertTrue(TOKEN_RE.fullmatch(pending[0]["token"]), pending[0])
        self.assertEqual(self.fake.players, [["pw-play", "--media-role", "Notification", "--volume", "1", BUNDLED]])
        self.assertEqual(self.state(), {"announced": {"work:a": T0 - 10, "work:b": T0}, "lastChime": T0 + 50})

    def test_new_mail_while_waiting_is_queued_behind_the_waiting_chime(self) -> None:
        seen: list[object] = []

        def during_wait() -> None:
            self.now += 5
            seen.extend([self.chime("work:c"), list(self.sleeps), len(self.fake.players)])
            seen.append(self.state()["announced"].get("work:c"))

        self.while_waiting = during_wait
        self.assertEqual(self.chime("work:b"), self.DEFERRED)
        self.assertEqual(seen, [{"ok": True, "skipped": "queued"}, [50], 0, T0 + 5])
        self.assertEqual(len(self.fake.players), 1)
        self.assertEqual(self.state()["lastChime"], T0 + 50)
        self.assertNotIn("pending", self.state())

    def test_same_mail_from_another_copy_while_waiting_is_announced(self) -> None:
        seen: list[dict] = []
        self.while_waiting = lambda: seen.append(self.chime("work:b"))
        self.assertEqual(self.chime("work:b"), self.DEFERRED)
        self.assertEqual(seen, [{"ok": True, "skipped": "announced"}])
        self.assertEqual(self.sleeps, [50])
        self.assertEqual(len(self.fake.players), 1)

    def test_do_not_disturb_when_the_wait_ends_stays_quiet(self) -> None:
        self.while_waiting = lambda: setattr(self.fake, "dnd", b"on\n")
        self.assertEqual(self.chime("work:b"), {"ok": True, "skipped": "dnd"})
        self.assertEqual(self.fake.players, [])
        self.assertEqual(self.state(), {"announced": {"work:a": T0 - 10, "work:b": T0}, "lastChime": T0 - 10})

    def test_do_not_disturb_while_waiting_leaves_the_waiting_chime_alone(self) -> None:
        seen: list[object] = []

        def during_wait() -> None:
            seen.append(self.state()["pending"])
            self.fake.dnd = b"on\n"
            seen.append(self.chime("work:c"))
            self.fake.dnd = b"off\n"
            seen.append(self.state()["pending"])

        self.while_waiting = during_wait
        self.assertEqual(self.chime("work:b"), self.DEFERRED)
        self.assertEqual(seen[1], {"ok": True, "skipped": "dnd"})
        self.assertEqual(seen[2], seen[0])
        self.assertEqual(len(self.fake.players), 1)

    def test_a_chime_after_the_due_time_supersedes_the_waiting_one(self) -> None:
        seen: list[object] = []

        def during_wait() -> None:
            self.now = T0 + 51
            seen.extend([self.chime("work:c"), list(self.sleeps), self.state()])
            seen.append(self.state_file.read_bytes())

        self.while_waiting = during_wait
        self.assertEqual(self.chime("work:b"), {"ok": True, "skipped": "superseded"})
        announced = {"work:a": T0 - 10, "work:b": T0, "work:c": T0 + 51}
        self.assertEqual(seen[:3], [{"ok": True, "played": "pw-play"}, [50], {"announced": announced, "lastChime": T0 + 51}])
        self.assertEqual(self.state_file.read_bytes(), seen[3])  # the waiter wrote nothing
        self.assertEqual(len(self.fake.players), 1)

    def test_a_waiting_chime_more_than_a_minute_overdue_is_replaced(self) -> None:
        self.write_state({"announced": {}, "lastChime": T0 - 10, "pending": {"due": T0 - 61, "token": TOKEN}})
        pending: list[dict] = []
        self.while_waiting = lambda: pending.append(self.state()["pending"])
        self.assertEqual(self.chime("work:b"), self.DEFERRED)
        self.assertEqual(self.sleeps, [50])
        self.assertEqual(pending[0]["due"], T0 + 50)
        self.assertNotEqual(pending[0]["token"], TOKEN)
        self.assertEqual(len(self.fake.players), 1)

    def test_a_waiting_chime_up_to_a_minute_overdue_still_counts(self) -> None:
        self.write_state({"announced": {}, "lastChime": T0 - 10, "pending": {"due": T0 - 60, "token": TOKEN}})
        self.assertEqual(self.chime("work:b"), {"ok": True, "skipped": "queued"})
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.fake.players, [])
        self.assertEqual(self.state()["pending"], {"due": T0 - 60, "token": TOKEN})

    def test_malformed_pending_reads_as_none(self) -> None:
        cases = [
            "soon",
            [],
            {"token": TOKEN},
            {"due": "soon", "token": TOKEN},
            {"due": True, "token": TOKEN},
            {"due": float("nan"), "token": TOKEN},
            {"due": T0 + 30},
            {"due": T0 + 30, "token": 123},
            {"due": T0 + 30, "token": TOKEN.upper()},
            {"due": T0 + 30, "token": TOKEN[:15]},
            {"due": T0 + 30, "token": TOKEN + "0"},
            {"due": T0 + 30, "token": TOKEN + "\n"},
        ]
        for pending in cases:
            with self.subTest(pending=pending):
                self.now = T0
                self.sleeps.clear()
                self.fake.calls.clear()
                self.write_state({"announced": {}, "lastChime": T0 - 10, "pending": pending})
                self.assertEqual(self.chime("work:b"), self.DEFERRED)
                self.assertEqual(self.sleeps, [50])
                self.assertEqual(len(self.fake.players), 1)

    def test_a_deferred_chime_still_reports_the_fallback(self) -> None:
        missing = str(self.home / "nope.oga")
        self.assertEqual(
            self.chime("work:b", file=missing), {**self.DEFERRED, "fallback": f"not a sound file: {missing}"}
        )
        self.assertEqual([argv[-1] for argv in self.fake.players], [BUNDLED])


class RetryTests(ChimeTestCase):
    """A play the player fails (exits with an error) is tried again 30 s later, up to 3 times."""

    FAILED = {"ok": False, "error": "pw-play exited 1: boom"}
    PLAYED = {"ok": True, "played": "pw-play"}

    def setUp(self) -> None:
        super().setUp()
        self.fake.while_playing = self.assert_unlocked  # never held across playback either

    def write_during_the_first_play(self, data: dict) -> None:
        """Stand in for another copy writing the shared record while this one plays."""

        def while_playing() -> None:
            self.assert_unlocked()
            self.fake.while_playing = self.assert_unlocked
            self.write_state(data)

        self.fake.while_playing = while_playing

    def test_a_failed_play_is_tried_again_thirty_seconds_later(self) -> None:
        self.fake.player_codes = [1]
        pending: list[dict] = []
        self.while_waiting = lambda: pending.append(self.state()["pending"])
        self.assertEqual(self.chime("work:a"), {**self.PLAYED, "retries": 1})
        self.assertEqual(self.sleeps, [30])
        self.assertEqual(len(self.fake.players), 2)
        self.assertEqual(pending[0]["due"], T0 + 30)
        self.assertTrue(TOKEN_RE.fullmatch(pending[0]["token"]), pending[0])
        self.assertEqual(self.state(), {"announced": {"work:a": T0}, "lastChime": T0 + 30})

    def test_a_player_that_keeps_failing_gives_up_after_three_retries(self) -> None:
        self.fake.player_code = 1
        self.assertEqual(self.chime("work:a"), {**self.FAILED, "retries": 3})
        self.assertEqual(self.sleeps, [30, 30, 30])
        self.assertEqual(len(self.fake.players), 4)
        self.assertEqual(self.state(), {"announced": {"work:a": T0}, "lastChime": T0 + 90})

    def assert_no_retry(self, error: str, players: list[str]) -> None:
        self.assertEqual(self.chime("work:a"), {"ok": False, "error": error})
        self.assertEqual([argv[0] for argv in self.fake.players], players)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.state(), {"announced": {"work:a": T0}, "lastChime": T0})

    def test_no_retry_after_a_timeout(self) -> None:
        self.fake.player_error = subprocess.TimeoutExpired(["pw-play"], 15)  # it played for 15 s
        self.assert_no_retry("pw-play timed out", ["pw-play"])

    def test_no_retry_after_a_signal(self) -> None:
        self.fake.player_code = -15  # someone stopped it
        self.assert_no_retry("pw-play exited -15: boom", ["pw-play"])

    def test_no_retry_when_no_player_is_found(self) -> None:
        self.fake.missing = {"pw-play", "paplay"}
        self.assert_no_retry("no audio player found (pw-play or paplay)", ["pw-play", "paplay"])

    def test_the_manual_test_is_never_retried(self) -> None:
        self.fake.while_playing = None  # no lock file: the manual test takes no lock
        self.fake.player_code = 1
        self.assertEqual(chime.run([]), self.FAILED)
        self.assertEqual(len(self.fake.players), 1)
        self.assertEqual(self.sleeps, [])
        self.assertFalse(self.state_dir.exists())

    def test_do_not_disturb_before_a_retry_stays_quiet(self) -> None:
        self.fake.player_codes = [1]
        self.while_waiting = lambda: setattr(self.fake, "dnd", b"on\n")
        self.assertEqual(self.chime("work:a"), {"ok": True, "skipped": "dnd"})
        self.assertEqual(self.sleeps, [30])
        self.assertEqual(len(self.fake.players), 1)
        self.assertEqual(self.state(), {"announced": {"work:a": T0}, "lastChime": T0})

    def test_a_later_retry_stopped_by_do_not_disturb_still_counts_the_retries(self) -> None:
        self.fake.player_code = 1

        def first_wait() -> None:
            self.while_waiting = lambda: setattr(self.fake, "dnd", b"on\n")  # before the second retry

        self.while_waiting = first_wait
        self.assertEqual(self.chime("work:a"), {"ok": True, "skipped": "dnd", "retries": 1})
        self.assertEqual(self.sleeps, [30, 30])
        self.assertEqual(len(self.fake.players), 2)
        self.assertEqual(self.state(), {"announced": {"work:a": T0}, "lastChime": T0 + 30})

    def test_a_chime_during_the_retry_wait_supersedes_it(self) -> None:
        self.fake.player_codes = [1]
        seen: list[object] = []

        def during_wait() -> None:
            self.now = T0 + 61  # past the cooldown of the failed play, so work:b plays at once
            seen.extend([self.chime("work:b"), self.state_file.read_bytes()])

        self.while_waiting = during_wait
        self.assertEqual(self.chime("work:a"), {"ok": True, "skipped": "superseded"})
        self.assertEqual(seen[0], self.PLAYED)
        self.assertEqual(self.state_file.read_bytes(), seen[1])  # the waiter wrote nothing
        self.assertEqual(self.state(), {"announced": {"work:a": T0, "work:b": T0 + 61}, "lastChime": T0 + 61})
        self.assertEqual(len(self.fake.players), 2)  # the failed play and work:b's

    def test_mail_during_the_retry_wait_is_queued_behind_it(self) -> None:
        self.fake.player_codes = [1]
        seen: list[object] = []

        def during_wait() -> None:
            self.now += 5
            seen.extend([self.chime("work:b"), len(self.fake.players)])

        self.while_waiting = during_wait
        self.assertEqual(self.chime("work:a"), {**self.PLAYED, "retries": 1})
        self.assertEqual(seen, [{"ok": True, "skipped": "queued"}, 1])
        self.assertEqual(len(self.fake.players), 2)
        self.assertEqual(self.state(), {"announced": {"work:a": T0, "work:b": T0 + 5}, "lastChime": T0 + 30})

    def test_no_retry_when_a_waiting_chime_already_covers_the_mail(self) -> None:
        # Mail for another copy arrived during the play and is waiting for the cooldown.
        waiting = {"due": T0 + 60, "token": TOKEN}
        concurrent = {"announced": {"work:a": T0, "work:b": T0}, "lastChime": T0, "pending": waiting}
        self.write_during_the_first_play(concurrent)
        self.fake.player_codes = [1]
        self.assertEqual(self.chime("work:a"), self.FAILED)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(len(self.fake.players), 1)
        self.assertEqual(self.state(), concurrent)

    def test_a_waiting_chime_counts_until_a_minute_overdue(self) -> None:
        for n, (overdue, retried) in enumerate(((60, False), (61, True))):
            with self.subTest(overdue=overdue):
                self.now = T0
                self.sleeps.clear()
                self.fake.calls.clear()
                msg_id = f"work:{n}"
                self.write_state({"announced": {}, "lastChime": 0})
                waiting = {"due": T0 - overdue, "token": TOKEN}
                self.write_during_the_first_play({"announced": {msg_id: T0}, "lastChime": T0, "pending": waiting})
                self.fake.player_codes = [1]
                self.assertEqual(self.chime(msg_id), {**self.PLAYED, "retries": 1} if retried else self.FAILED)
                self.assertEqual(self.sleeps, [30] if retried else [])
                self.assertEqual(self.state().get("pending"), None if retried else waiting)

    def test_a_retry_still_reports_the_fallback(self) -> None:
        missing = str(self.home / "nope.oga")
        self.fake.player_codes = [1]
        self.assertEqual(
            self.chime("work:a", file=missing),
            {**self.PLAYED, "retries": 1, "fallback": f"not a sound file: {missing}"},
        )
        self.assertEqual([argv[-1] for argv in self.fake.players], [BUNDLED, BUNDLED])

    def test_a_retry_of_a_file_the_player_rejects_still_reports_the_fallback(self) -> None:
        self.fake.unplayable = {str(self.sound)}
        self.fake.player_codes = [1]  # the bundled clip fails too, the first time
        self.assertEqual(
            self.chime("work:a", file=str(self.sound)),
            {**self.PLAYED, "retries": 1, "fallback": f"pw-play could not play {self.sound}: boom"},
        )
        self.assertEqual(
            [argv[-1] for argv in self.fake.players], [str(self.sound), BUNDLED, str(self.sound), BUNDLED]
        )

    def test_a_retry_stopped_by_do_not_disturb_still_reports_the_fallback(self) -> None:
        self.fake.unplayable = {str(self.sound)}
        self.fake.player_codes = [1]  # the bundled clip fails too
        self.while_waiting = lambda: setattr(self.fake, "dnd", b"on\n")
        self.assertEqual(
            self.chime("work:a", file=str(self.sound)),
            {"ok": True, "skipped": "dnd", "fallback": f"pw-play could not play {self.sound}: boom"},
        )
        self.assertEqual(self.sleeps, [30])
        self.assertEqual([argv[-1] for argv in self.fake.players], [str(self.sound), BUNDLED])

    def test_a_deferred_chime_that_is_retried_reports_both(self) -> None:
        self.write_state({"announced": {"work:a": T0 - 10}, "lastChime": T0 - 10})
        self.fake.player_codes = [1]
        self.assertEqual(self.chime("work:b"), {**self.PLAYED, "deferred": True, "retries": 1})
        self.assertEqual(self.sleeps, [50, 30])
        self.assertEqual(len(self.fake.players), 2)
        self.assertEqual(self.state(), {"announced": {"work:a": T0 - 10, "work:b": T0}, "lastChime": T0 + 80})


class CancelTests(ChimeTestCase):
    """`chime --cancel` drops a waiting chime when the sound is turned off."""

    CANCELLED = {"ok": True, "cancelled": True}

    def cancel_while_waiting(self) -> list[object]:
        """Cancel from inside the wait; record the result, whether it ran anything, and the state."""
        seen: list[object] = []

        def during_wait() -> None:
            calls = len(self.fake.calls)
            seen.extend([chime.run(["--cancel"]), len(self.fake.calls) - calls, self.state()])

        self.while_waiting = during_wait
        return seen

    def test_cancel_drops_a_chime_waiting_for_the_cooldown(self) -> None:
        self.write_state({"announced": {"work:a": T0 - 10}, "lastChime": T0 - 10})
        seen = self.cancel_while_waiting()
        self.assertEqual(self.chime("work:b"), {"ok": True, "skipped": "superseded"})
        self.assertEqual(seen, [self.CANCELLED, 0, {"announced": {"work:a": T0 - 10, "work:b": T0}, "lastChime": T0 - 10}])
        self.assertEqual(self.sleeps, [50])
        self.assertEqual(self.fake.players, [])
        self.assertNotIn("pending", self.state())

    def test_cancel_drops_a_chime_waiting_to_try_again(self) -> None:
        self.fake.player_codes = [1]
        seen = self.cancel_while_waiting()
        self.assertEqual(self.chime("work:a"), {"ok": True, "skipped": "superseded"})
        self.assertEqual(seen, [self.CANCELLED, 0, {"announced": {"work:a": T0}, "lastChime": T0}])
        self.assertEqual(self.sleeps, [30])
        self.assertEqual(len(self.fake.players), 1)  # the failed play only

    def test_cancel_keeps_announced_and_last_chime(self) -> None:
        # A waiter more than a minute overdue may be sleeping through a suspend: drop it too.
        for due in (T0 + 50, T0 - 61):
            with self.subTest(due=due):
                kept = {"announced": {"work:a": T0 - 10, "work:b": T0}, "lastChime": T0 - 10}
                self.write_state({**kept, "pending": {"due": due, "token": TOKEN}})
                self.assertEqual(chime.run(["--cancel"]), self.CANCELLED)
                self.assertEqual(self.state(), kept)
                self.assertEqual(self.fake.calls, [])

    def test_cancel_with_nothing_waiting_writes_nothing(self) -> None:
        self.assertEqual(chime.run(["--cancel"]), {"ok": True, "cancelled": False})
        self.assertFalse(self.state_file.exists())
        for data in (
            {"announced": {"work:a": T0}, "lastChime": T0},
            {"announced": {"work:a": T0}, "lastChime": T0, "pending": {"due": T0 + 30, "token": "junk"}},
            "not json",
        ):
            with self.subTest(data=data):
                self.write_state(data)
                before = self.state_file.read_bytes()
                self.assertEqual(chime.run(["--cancel"]), {"ok": True, "cancelled": False})
                self.assertEqual(self.state_file.read_bytes(), before)
        self.assertEqual(self.fake.calls, [])

    def test_cancel_with_the_state_unavailable_is_an_error(self) -> None:
        self.state_dir.write_text("not a directory", encoding="utf-8")
        result = chime.run(["--cancel"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"].startswith("chime state unavailable: "), result["error"])

    def test_cancel_with_anything_else_is_a_usage_error(self) -> None:
        for args in (
            ["--cancel", "--volume", "50"],
            ["--file", str(self.sound), "--cancel"],
            ["--cancel", "--cooldown", "60"],
            ["--cancel", "--cancel"],
            ["--cancel", "--"],
            ["--cancel", "--", "work:a"],
            ["--", "--cancel"],
        ):
            with self.subTest(args=args):
                result = chime.run(args)
                self.assertFalse(result["ok"])
                self.assertTrue(result["error"].startswith("usage: "), result["error"])
                self.assertIn("--cancel", result["error"])
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(self.state_dir.exists())


class DoNotDisturbTests(ChimeTestCase):
    def test_dnd_on_spawns_no_player_and_still_records_ids(self) -> None:
        self.fake.dnd = b"on\n"
        self.assertEqual(self.chime("work:abc"), {"ok": True, "skipped": "dnd"})
        self.assertEqual(self.fake.players, [])
        self.assertEqual(self.state(), {"announced": {"work:abc": T0}, "lastChime": 0})
        self.fake.dnd = b"off\n"
        self.assertEqual(self.chime("work:abc"), {"ok": True, "skipped": "announced"})
        self.assertEqual(self.fake.players, [])

    def test_dnd_query_is_bounded_by_two_seconds(self) -> None:
        self.chime("work:abc")
        self.assertEqual(self.fake.calls[0][0], ["omarchy-shell", "notifications", "isDnd"])
        self.assertEqual(self.fake.kwargs_for("omarchy-shell").get("timeout"), 2)

    def test_failing_dnd_query_counts_as_silenced(self) -> None:
        cases = {
            "missing": (FileNotFoundError(2, "No such file or directory", "omarchy-shell"), 0),
            "timeout": (subprocess.TimeoutExpired(["omarchy-shell"], 2), 0),
            "exit 1": (b"off\n", 1),
            "other output": (b"maybe\n", 0),
            "empty": (b"", 0),
        }
        for label, (dnd, code) in cases.items():
            with self.subTest(label):
                self.fake.calls.clear()
                self.fake.dnd, self.fake.dnd_code = dnd, code
                msg_id = "work:" + label.replace(" ", "-")
                self.assertEqual(self.chime(msg_id), {"ok": True, "skipped": "dnd"})
                self.assertEqual(self.fake.players, [])
                self.assertIn(msg_id, self.state()["announced"])

    def test_announced_wins_over_dnd(self) -> None:
        self.chime("work:abc")
        self.fake.dnd = b"on\n"
        self.assertEqual(self.chime("work:abc"), {"ok": True, "skipped": "announced"})


class SoundFileTests(ChimeTestCase):
    def test_bundled_clip_is_the_default(self) -> None:
        self.assertEqual(self.chime("work:abc"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.fake.players[0][-1], BUNDLED)

    def test_leading_tilde_is_expanded(self) -> None:
        self.assertEqual(self.chime("work:abc", file="~/sound.oga"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.fake.players[0][-1], str(self.sound))

    def test_relative_file_starting_with_dash_becomes_an_absolute_path(self) -> None:
        (self.home / "-q.oga").write_bytes(b"OggS")
        old = os.getcwd()
        os.chdir(self.home)
        self.addCleanup(os.chdir, old)
        self.assertEqual(self.chime("work:abc", file="-q.oga"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.fake.players[0][-1], str(self.home / "-q.oga"))


class PlayerTests(ChimeTestCase):
    def test_pw_play_gets_notification_role_and_unit_volume(self) -> None:
        for volume, expected in (("100", "1"), ("50", "0.5"), ("7", "0.07"), ("0", "0"), ("250", "1"), ("-3", "0")):
            with self.subTest(volume=volume):
                self.fake.calls.clear()
                self.assertEqual(chime.run(["--volume", volume, "--file", str(self.sound)]), {"ok": True, "played": "pw-play"})
                self.assertEqual(
                    self.fake.players,
                    [["pw-play", "--media-role", "Notification", "--volume", expected, str(self.sound)]],
                )

    def test_omitted_volume_passes_no_volume_option(self) -> None:
        chime.run(["--file", str(self.sound)])
        self.assertEqual(self.fake.players, [["pw-play", "--media-role", "Notification", str(self.sound)]])

    def test_paplay_fallback_gets_event_role_and_pulse_volume(self) -> None:
        self.fake.missing = {"pw-play"}
        for volume, expected in (("100", "65536"), ("50", "32768"), ("33", "21627"), ("0", "0")):
            with self.subTest(volume=volume):
                self.fake.calls.clear()
                self.assertEqual(chime.run(["--volume", volume, "--file", str(self.sound)]), {"ok": True, "played": "paplay"})
                self.assertEqual([argv[0] for argv in self.fake.players], ["pw-play", "paplay"])
                self.assertEqual(
                    self.fake.players[-1],
                    ["paplay", "--property=media.role=event", "--volume", expected, str(self.sound)],
                )

    def test_players_run_with_a_timeout_and_captured_output(self) -> None:
        self.fake.missing = {"pw-play"}
        chime.run(["--file", str(self.sound)])
        for name in ("pw-play", "paplay"):
            kwargs = self.fake.kwargs_for(name)
            self.assertEqual(kwargs.get("timeout"), 15)
            self.assertNotIn("shell", kwargs)
            self.assertTrue(kwargs.get("capture_output") or kwargs.get("stdout") is not None)

    def test_pw_play_failure_on_the_bundled_clip_is_final(self) -> None:
        self.fake.player_code = 1
        self.assertEqual(chime.run([]), {"ok": False, "error": "pw-play exited 1: boom"})
        self.assertEqual(self.fake.players, [["pw-play", "--media-role", "Notification", BUNDLED]])

    def test_player_timeout_is_an_error_and_is_not_retried(self) -> None:
        self.fake.player_error = subprocess.TimeoutExpired(["pw-play"], 15)
        self.assertEqual(chime.run(["--file", str(self.sound)]), {"ok": False, "error": "pw-play timed out"})
        self.assertEqual([argv[0] for argv in self.fake.players], ["pw-play"])

    def test_no_player_found(self) -> None:
        self.fake.missing = {"pw-play", "paplay"}
        self.assertEqual(
            chime.run(["--file", str(self.sound)]),
            {"ok": False, "error": "no audio player found (pw-play or paplay)"},
        )


class FallbackTests(ChimeTestCase):
    def test_missing_or_non_regular_file_plays_the_bundled_clip(self) -> None:
        for n, path in enumerate((str(self.home / "nope.oga"), str(self.home), "/dev/null")):
            with self.subTest(path=path):
                self.fake.calls.clear()
                self.assertEqual(
                    self.chime(f"work:{n}", cooldown="0", file=path),
                    {"ok": True, "played": "pw-play", "fallback": f"not a sound file: {path}"},
                )
                self.assertEqual(self.fake.players, [["pw-play", "--media-role", "Notification", "--volume", "1", BUNDLED]])

    @unittest.skipIf(os.geteuid() == 0, "root can read a mode-000 file")
    def test_unreadable_file_plays_the_bundled_clip(self) -> None:
        self.sound.chmod(0)
        self.assertEqual(
            self.chime("work:abc", file=str(self.sound)),
            {"ok": True, "played": "pw-play", "fallback": f"cannot read: {self.sound}"},
        )
        self.assertEqual([argv[-1] for argv in self.fake.players], [BUNDLED])

    def test_file_the_player_rejects_is_retried_once_with_the_bundled_clip(self) -> None:
        self.fake.unplayable = {str(self.sound)}
        for stderr, detail in ((b"bad format\n", ": bad format"), (b"", "")):
            with self.subTest(stderr=stderr):
                self.fake.calls.clear()
                self.fake.player_stderr = stderr
                self.assertEqual(
                    chime.run(["--volume", "50", "--file", str(self.sound)]),
                    {"ok": True, "played": "pw-play", "fallback": f"pw-play could not play {self.sound}{detail}"},
                )
                pw_play = ["pw-play", "--media-role", "Notification", "--volume", "0.5"]
                self.assertEqual(self.fake.players, [pw_play + [str(self.sound)], pw_play + [BUNDLED]])

    def test_player_killed_by_a_signal_is_not_retried(self) -> None:
        self.fake.player_code = -15  # e.g. `pkill pw-play` mid-clip: the file was playing
        self.assertEqual(chime.run(["--file", str(self.sound)]), {"ok": False, "error": "pw-play exited -15: boom"})
        self.assertEqual(self.fake.players, [["pw-play", "--media-role", "Notification", str(self.sound)]])

    def test_retry_uses_the_same_player_selection(self) -> None:
        self.fake.missing = {"pw-play"}
        self.fake.unplayable = {str(self.sound)}
        self.assertEqual(
            chime.run(["--file", str(self.sound)]),
            {"ok": True, "played": "paplay", "fallback": f"paplay could not play {self.sound}: boom"},
        )
        self.assertEqual(
            [(argv[0], argv[-1]) for argv in self.fake.players],
            [("pw-play", str(self.sound)), ("paplay", str(self.sound)), ("pw-play", BUNDLED), ("paplay", BUNDLED)],
        )

    def test_bundled_retry_that_fails_too_is_an_error_with_the_fallback(self) -> None:
        self.fake.player_code = 1
        self.assertEqual(
            chime.run(["--file", str(self.sound)]),
            {"ok": False, "error": "pw-play exited 1: boom", "fallback": f"pw-play could not play {self.sound}: boom"},
        )
        self.assertEqual([argv[-1] for argv in self.fake.players], [str(self.sound), BUNDLED])

    def test_skipped_results_report_the_fallback_too(self) -> None:
        missing = str(self.home / "nope.oga")
        reason = f"not a sound file: {missing}"
        self.chime("work:abc", file=missing)
        self.assertEqual(self.chime("work:abc", file=missing), {"ok": True, "skipped": "announced", "fallback": reason})
        self.fake.dnd = b"on\n"
        self.assertEqual(chime.run(["--file", missing]), {"ok": True, "skipped": "dnd", "fallback": reason})
        self.assertEqual(len(self.fake.players), 1)

    def test_missing_bundled_clip_is_an_error(self) -> None:
        bundled = self.tmp / "gone.oga"
        missing = str(self.home / "nope.oga")
        with patch.object(chime, "BUNDLED_SOUND", bundled):
            self.assertEqual(self.chime("work:abc"), {"ok": False, "error": f"not a sound file: {bundled}"})
            self.assertEqual(
                self.chime("work:abc", file=missing),
                {"ok": False, "error": f"not a sound file: {bundled}", "fallback": f"not a sound file: {missing}"},
            )
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(self.state_dir.exists())


class ManualTestTests(ChimeTestCase):
    def test_without_ids_plays_inside_cooldown_and_leaves_state_untouched(self) -> None:
        self.write_state({"announced": {"work:abc": T0}, "lastChime": T0, "pending": {"due": T0 + 60, "token": TOKEN}})
        before = self.state_file.read_bytes()
        self.assertEqual(chime.run([]), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertFalse((self.state_dir / "chime.lock").exists())

    def test_without_ids_honours_dnd(self) -> None:
        self.fake.dnd = b"on\n"
        self.assertEqual(chime.run([]), {"ok": True, "skipped": "dnd"})
        self.assertEqual(self.fake.players, [])
        self.assertFalse(self.state_dir.exists())


class ArgumentTests(ChimeTestCase):
    def test_invalid_ids_are_dropped(self) -> None:
        long_account = "a" * 34 + ":x"
        self.assertEqual(
            self.chime("bad", "-x:y", "work:ok", "work:has space", "work:nl\n", long_account, "work:" + "z" * 513),
            {"ok": True, "played": "pw-play"},
        )
        self.assertEqual(self.state()["announced"], {"work:ok": T0})

    def test_no_valid_ids_is_an_error_and_plays_nothing(self) -> None:
        for ids in ((), ("bad", "also bad:x")):
            with self.subTest(ids=ids):
                self.assertEqual(self.chime(*ids), {"ok": False, "error": "no valid message IDs"})
                self.assertEqual(self.fake.calls, [])
                self.assertFalse(self.state_dir.exists())

    def test_usage_errors(self) -> None:
        for args in (["--loud"], ["--file"], ["--volume"], ["--cooldown"], ["work:abc"]):
            with self.subTest(args=args):
                result = chime.run(args)
                self.assertFalse(result["ok"])
                self.assertTrue(result["error"].startswith("usage: "), result["error"])
                self.assertEqual(self.fake.calls, [])


class StateDirTests(ChimeTestCase):
    def test_falls_back_to_the_cache_dir(self) -> None:
        cache = self.home / ".cache" / "omarchy-you-got-mail"
        for runtime in (None, "", "relative/run", str(self.tmp / "missing"), str(self.sound)):
            with self.subTest(runtime=runtime):
                shutil.rmtree(cache, ignore_errors=True)
                if runtime is None:
                    os.environ.pop("XDG_RUNTIME_DIR", None)
                else:
                    os.environ["XDG_RUNTIME_DIR"] = runtime
                self.assertEqual(self.chime("work:abc"), {"ok": True, "played": "pw-play"})
                data = json.loads((cache / "chime.json").read_text(encoding="utf-8"))
                self.assertEqual(data["announced"], {"work:abc": T0})
                self.assertEqual(cache.stat().st_mode & 0o777, 0o700)

    def test_fallback_honours_xdg_cache_home(self) -> None:
        os.environ.pop("XDG_RUNTIME_DIR", None)
        os.environ["XDG_CACHE_HOME"] = str(self.tmp / "cache")
        self.chime("work:abc")
        self.assertTrue((self.tmp / "cache" / "omarchy-you-got-mail" / "chime.json").is_file())


class CliTests(ChimeTestCase):
    def test_cli_dispatches_chime_and_prints_one_json_object(self) -> None:
        import cli

        buf = StringIO()
        with redirect_stdout(buf), patch.object(sys, "argv", ["you-got-mail", "chime", "--volume", "80", "--", "work:abc"]):
            cli.main()
        lines = buf.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"ok": True, "played": "pw-play"})

    def test_help_mentions_chime(self) -> None:
        import cli

        self.assertIn("you-got-mail chime [--file PATH] [--volume 0-100] [--cooldown SEC] [-- ID ...]", cli.HELP)
        self.assertIn("you-got-mail chime --cancel", cli.HELP)

    def test_wrapper_keeps_player_output_off_stdout(self) -> None:
        bindir = self.tmp / "bin"
        bindir.mkdir()
        log = self.tmp / "argv.log"
        fakes = {
            "omarchy-shell": "echo off\n",
            "pw-play": f'echo player noise; echo player err >&2; printf "%s\\n" "$@" > "{log}"\n',
            "paplay": "echo paplay must not run; exit 1\n",
        }
        for name, body in fakes.items():
            script = bindir / name
            script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
            script.chmod(0o700)
        path = os.pathsep.join(
            [str(bindir), os.path.dirname(shutil.which("python3") or ""), os.path.dirname(shutil.which("bash") or "")]
        )
        env = {"PATH": path, "HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.runtime)}
        proc = REAL_RUN(
            [str(ROOT / "bin" / "you-got-mail"), "chime", "--cooldown", "60", "--volume", "50", "--file", str(self.sound), "--", "work:abc"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '{"ok": true, "played": "pw-play"}\n')
        self.assertEqual(proc.stderr, "")
        self.assertEqual(
            log.read_text(encoding="utf-8").splitlines(),
            ["--media-role", "Notification", "--volume", "0.5", str(self.sound)],
        )


if __name__ == "__main__":
    unittest.main()
