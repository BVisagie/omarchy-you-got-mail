from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support import capture_json, ROOT

import common


def _workdir() -> Path:
    root = ROOT / ".test-tmp"
    root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(dir=root))


class CommonHelpersTests(unittest.TestCase):
    def test_clamp_int(self) -> None:
        self.assertEqual(common.clamp_int("25", 10, 1, 50), 25)
        self.assertEqual(common.clamp_int("0", 10, 1, 50), 1)
        self.assertEqual(common.clamp_int("99", 10, 1, 50), 50)
        self.assertEqual(common.clamp_int("nope", 10, 1, 50), 10)

    def test_fetch_limit_caps_at_200(self) -> None:
        self.assertEqual(common.fetch_limit("200"), 200)
        self.assertEqual(common.fetch_limit("999"), 200)
        self.assertEqual(common.fetch_limit("0"), 1)

    def test_one_line_collapses_whitespace(self) -> None:
        self.assertEqual(common.one_line("Hello\r\nworld\t  there"), "Hello world there")
        self.assertTrue(common.one_line("x" * 200).endswith("…"))

    def test_encode_decode_id(self) -> None:
        opaque = common.encode_id("work", "INBOX/12")
        self.assertEqual(common.decode_id(opaque), ("work", "INBOX/12"))


class SecretLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(self._cleanup)
        os.chmod(self.tmp, 0o700)
        self.path = self.tmp / "secret.json"

    def _cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_accepts_owner_private_file(self) -> None:
        self.path.write_text('{"token":"abc"}\n', encoding="utf-8")
        os.chmod(self.path, 0o600)
        data = common.load_secret_file(self.path, "fastmail")
        self.assertEqual(data["token"], "abc")

    def test_rejects_group_readable_file(self) -> None:
        self.path.write_text('{"token":"abc"}\n', encoding="utf-8")
        os.chmod(self.path, 0o644)
        payload = capture_json(common.load_secret_file, self.path, "fastmail")
        self.assertFalse(payload["ok"])
        self.assertIn("too open", payload["error"])

    def test_rejects_open_parent_directory(self) -> None:
        self.path.write_text('{"token":"abc"}\n', encoding="utf-8")
        os.chmod(self.path, 0o600)
        os.chmod(self.tmp, 0o755)
        payload = capture_json(common.load_secret_file, self.path, "fastmail")
        self.assertFalse(payload["ok"])
        self.assertIn("directory", payload["error"])

    def test_rejects_symlink(self) -> None:
        target = self.tmp / "real.json"
        target.write_text("{}\n", encoding="utf-8")
        os.chmod(target, 0o600)
        link = self.tmp / "link.json"
        link.symlink_to(target)
        data = common.load_secret_file(link, "fastmail")
        self.assertEqual(data, {})


class AccountsFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp))
        self._old = (common.CONFIG_DIR, common.ACCOUNTS_FILE, common.SECRETS_DIR)
        common.CONFIG_DIR = self.tmp
        common.ACCOUNTS_FILE = self.tmp / "accounts.json"
        common.SECRETS_DIR = self.tmp / "secrets"

    def tearDown(self) -> None:
        common.CONFIG_DIR, common.ACCOUNTS_FILE, common.SECRETS_DIR = self._old

    def test_missing_file_is_implicit_gmail(self) -> None:
        accounts = common.load_accounts()
        self.assertEqual(accounts[0]["provider"], "gmail")

    def test_rejects_unknown_provider(self) -> None:
        common.ACCOUNTS_FILE.write_text(
            json.dumps({"accounts": [{"id": "x", "provider": "nope"}]}),
            encoding="utf-8",
        )
        accounts = common.load_accounts()
        self.assertEqual(accounts[0]["provider"], "gmail")


class ManifestAndHelpTests(unittest.TestCase):
    def test_manifest_widget_settings(self) -> None:
        data = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "2.3.0")
        keys = {item["key"] for item in data["barWidget"]["schema"]}
        self.assertEqual(keys, {"max", "refreshIntervalSec"})
        self.assertEqual(data["barWidget"]["defaults"]["max"], 25)

    def test_cli_help_documents_limit(self) -> None:
        import cli

        from io import StringIO
        from contextlib import redirect_stdout

        buf = StringIO()
        with redirect_stdout(buf):
            old = __import__("sys").argv
            __import__("sys").argv = ["you-got-mail", "--help"]
            try:
                cli.main()
            finally:
                __import__("sys").argv = old
        self.assertIn("--limit", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
