from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from support import ROOT

import accounts
import common


def _workdir() -> Path:
    root = ROOT / ".test-tmp"
    root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(dir=root))


class AccountsLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        os.chmod(self.tmp, 0o700)
        self._old = (common.CONFIG_DIR, common.ACCOUNTS_FILE, common.SECRETS_DIR)
        common.CONFIG_DIR = self.tmp
        common.ACCOUNTS_FILE = self.tmp / "accounts.json"
        common.SECRETS_DIR = self.tmp / "secrets"
        accounts.ACCOUNTS_FILE = common.ACCOUNTS_FILE

    def tearDown(self) -> None:
        common.CONFIG_DIR, common.ACCOUNTS_FILE, common.SECRETS_DIR = self._old
        accounts.ACCOUNTS_FILE = common.ACCOUNTS_FILE

    def _write_accounts(self, rows: list[dict]) -> None:
        common.save_accounts(rows)

    def test_login_outlook_reuses_id_and_client(self) -> None:
        self._write_accounts(
            [{"id": "outlook", "provider": "outlook", "label": "Outlook"}]
        )
        common.save_secret(
            "outlook",
            {"client_id": "app-1", "tenant": "consumers", "refresh_token": "old"},
        )

        def fake_login(client_id: str, tenant: str) -> dict:
            self.assertEqual(client_id, "app-1")
            self.assertEqual(tenant, "consumers")
            return {"refresh_token": "new-token", "access_token": "a"}

        with patch.object(accounts, "_tty", return_value=True), patch(
            "outlook_auth.graph_login", side_effect=fake_login
        ):
            accounts.cmd_login("outlook")

        ids = [a["id"] for a in common.load_accounts()]
        self.assertEqual(ids, ["outlook"])
        secret = common.load_secret("outlook")
        self.assertEqual(secret["refresh_token"], "new-token")
        self.assertEqual(secret["client_id"], "app-1")
        self.assertNotIn("access_token", secret)

    def test_login_unknown_id_fails(self) -> None:
        self._write_accounts([{"id": "gmail", "provider": "gmail", "label": "Gmail"}])
        with patch.object(accounts, "_tty", return_value=True):
            with self.assertRaises(SystemExit):
                accounts.cmd_login("nope")

    def test_login_refuses_non_tty(self) -> None:
        self._write_accounts([{"id": "gmail", "provider": "gmail", "label": "Gmail"}])
        with patch.object(accounts, "_tty", return_value=False):
            with self.assertRaises(SystemExit):
                accounts.cmd_login("gmail")

    def test_login_fastmail_overwrites_token(self) -> None:
        self._write_accounts(
            [{"id": "fastmail", "provider": "fastmail", "label": "Fastmail"}]
        )
        common.save_secret("fastmail", {"token": "old"})
        with patch.object(accounts, "_tty", return_value=True), patch.object(
            accounts, "_ask_secret", return_value="fresh-token"
        ):
            accounts.cmd_login("fastmail")
        self.assertEqual(common.load_secret("fastmail")["token"], "fresh-token")

    def test_help_mentions_login(self) -> None:
        buf = StringIO()
        with patch("sys.stdout", buf):
            accounts.main(["--help"])
        self.assertIn("accounts login", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
