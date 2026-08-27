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


class HttpBodyTests(unittest.TestCase):
    def _body(self, data: bytes, content_length: object | None = ""):
        class Body:
            def __init__(self) -> None:
                self._buf = __import__("io").BytesIO(data)
                self.headers = {}
                if content_length != "":
                    self.headers["Content-Length"] = content_length

            def read(self, n: int = -1) -> bytes:
                return self._buf.read(n)

        return Body()

    def test_accepts_body_at_limit(self) -> None:
        limit = 16
        raw = common.read_http_body(self._body(b"a" * limit), limit)
        self.assertEqual(raw, b"a" * limit)

    def test_rejects_one_byte_over_limit(self) -> None:
        limit = 16
        with self.assertRaises(common.ResponseTooLargeError):
            common.read_http_body(self._body(b"a" * (limit + 1)), limit)

    def test_rejects_oversized_declared_length(self) -> None:
        limit = 16
        with self.assertRaises(common.ResponseTooLargeError):
            common.read_http_body(self._body(b"ok", content_length=str(limit + 1)), limit)

    def test_rejects_lying_undersized_length(self) -> None:
        limit = 16
        with self.assertRaises(common.ResponseTooLargeError):
            common.read_http_body(
                self._body(b"a" * (limit + 1), content_length="4"),
                limit,
            )

    def test_malformed_or_negative_length_still_caps_stream(self) -> None:
        limit = 8
        raw = common.read_http_body(self._body(b"abcd", content_length="nope"), limit)
        self.assertEqual(raw, b"abcd")
        with self.assertRaises(common.ResponseTooLargeError):
            common.read_http_body(self._body(b"a" * (limit + 1), content_length="-1"), limit)


class PrivateWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        os.chmod(self.tmp, 0o700)
        self.path = self.tmp / "secret.json"

    def test_write_private_mode_600(self) -> None:
        common.write_private(self.path, '{"token":"abc"}\n')
        self.assertTrue(self.path.is_file())
        self.assertFalse(self.path.is_symlink())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"token":"abc"}\n')

    def test_planted_tmp_symlink_is_not_followed(self) -> None:
        target = self.tmp / "other-file"
        target.write_text("keep\n", encoding="utf-8")
        os.chmod(target, 0o600)
        planted = self.tmp / "secret.json.tmp"
        planted.symlink_to(target)
        common.write_private(self.path, '{"ok":true}\n')
        self.assertTrue(self.path.is_file())
        self.assertFalse(self.path.is_symlink())
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"ok":true}\n')
        self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")
        self.assertTrue(planted.is_symlink())


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
        self.assertEqual(data["version"], "2.4.1")
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
        self.assertIn("read-all", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
