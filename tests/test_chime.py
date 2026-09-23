from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from support import ROOT

import chime

T0 = 1_800_000_000
DAY = 24 * 60 * 60
REAL_RUN = subprocess.run  # the tests patch subprocess.run itself


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
        self.player_error: Exception | None = None

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append((list(argv), kwargs))
        name = argv[0]
        if name in self.missing:
            raise FileNotFoundError(2, "No such file or directory", name)
        if name == "omarchy-shell":
            if isinstance(self.dnd, Exception):
                raise self.dnd
            return subprocess.CompletedProcess(argv, self.dnd_code, self.dnd, b"")
        if self.player_error is not None:
            raise self.player_error
        return subprocess.CompletedProcess(argv, self.player_code, b"", b"boom\n")

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
        self.assertEqual(self.chime("work:b"), {"ok": True, "skipped": "cooldown"})
        self.assertEqual(len(self.fake.players), 1)
        self.assertIn("work:b", self.state()["announced"])
        self.assertEqual(self.state()["lastChime"], T0)
        self.now += 1
        self.assertEqual(self.chime("work:c"), {"ok": True, "played": "pw-play"})
        self.assertEqual(self.state()["lastChime"], T0 + 60)

    def test_cooldown_is_clamped_and_defaults_to_sixty(self) -> None:
        cases = [("99999", 3600), ("-5", 0), ("0", 0), ("soon", 60), ("", 60)]
        for raw, seconds in cases:
            with self.subTest(raw=raw):
                self.write_state({"announced": {}, "lastChime": T0 - seconds})
                self.assertEqual(self.chime("work:a", cooldown=raw), {"ok": True, "played": "pw-play"})
                if seconds:
                    self.write_state({"announced": {}, "lastChime": T0 - seconds + 1})
                    self.assertEqual(self.chime("work:a", cooldown=raw), {"ok": True, "skipped": "cooldown"})

    def test_omitted_cooldown_is_sixty(self) -> None:
        self.write_state({"announced": {}, "lastChime": T0 - 59})
        self.assertEqual(chime.run(["--", "work:a"]), {"ok": True, "skipped": "cooldown"})
        self.write_state({"announced": {}, "lastChime": T0 - 60})
        self.assertEqual(chime.run(["--", "work:b"]), {"ok": True, "played": "pw-play"})


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
        self.chime("work:abc")
        self.assertEqual(self.fake.players[0][-1], str(ROOT / "sounds" / "you-got-mail.oga"))

    def test_missing_or_non_regular_file_is_an_error(self) -> None:
        for path in (str(self.home / "nope.oga"), str(self.home), "/dev/null"):
            with self.subTest(path=path):
                result = self.chime("work:abc", file=path)
                self.assertFalse(result["ok"])
                self.assertIn("error", result)
                self.assertEqual(self.fake.calls, [])
                self.assertFalse(self.state_dir.exists())

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

    def test_pw_play_failure_does_not_fall_back(self) -> None:
        self.fake.player_code = 1
        result = chime.run(["--file", str(self.sound)])
        self.assertFalse(result["ok"])
        self.assertIn("pw-play", result["error"])
        self.assertEqual([argv[0] for argv in self.fake.players], ["pw-play"])

    def test_player_timeout_is_an_error(self) -> None:
        self.fake.player_error = subprocess.TimeoutExpired(["pw-play"], 15)
        result = chime.run(["--file", str(self.sound)])
        self.assertFalse(result["ok"])
        self.assertEqual([argv[0] for argv in self.fake.players], ["pw-play"])

    def test_no_player_found(self) -> None:
        self.fake.missing = {"pw-play", "paplay"}
        self.assertEqual(
            chime.run(["--file", str(self.sound)]),
            {"ok": False, "error": "no audio player found (pw-play or paplay)"},
        )


class ManualTestTests(ChimeTestCase):
    def test_without_ids_plays_inside_cooldown_and_leaves_state_untouched(self) -> None:
        self.write_state({"announced": {"work:abc": T0}, "lastChime": T0})
        before = self.state_file.read_bytes()
        self.assertEqual(chime.run([]), {"ok": True, "played": "pw-play"})
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
