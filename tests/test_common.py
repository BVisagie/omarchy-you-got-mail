from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

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

    def test_gmail_oauth_soup_maps_to_login_command(self) -> None:
        raw = (
            "Authentication failed: Failed to get token: Server error: "
            "invalid_grant: Token has been expired or revoked.: "
            "invalid_grant: Token has been expired or revoked."
        )
        msg = common.account_error(
            {"id": "gmail", "provider": "gmail"},
            raw,
        )
        self.assertTrue(msg.startswith("gmail: Gmail needs you to sign in again."))
        self.assertIn("you-got-mail accounts login gmail", msg)
        self.assertNotIn("invalid_grant", msg)
        self.assertNotIn("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND", msg)
        self.assertTrue(common.needs_sign_in(msg))

    def test_account_error_is_idempotent(self) -> None:
        first = common.account_error(
            {"id": "outlook", "provider": "outlook"},
            "invalid_grant: Token has been expired or revoked.",
        )
        again = common.account_error({"id": "outlook", "provider": "outlook"}, first)
        self.assertEqual(first, again)
        self.assertEqual(first.count("outlook:"), 1)
        self.assertIn("you-got-mail accounts login outlook", first)

    def test_missing_tool_and_unreachable_are_plain_language(self) -> None:
        missing = common.account_error(
            {"id": "gmail", "provider": "gmail"},
            "gws not found on PATH - see the README",
        )
        self.assertEqual(missing, "gmail: Gmail isn't installed for this bar. See the setup guide.")
        self.assertFalse(common.needs_sign_in(missing))
        again = common.account_error({"id": "gmail", "provider": "gmail"}, missing)
        self.assertEqual(again, missing)
        down = common.account_error(
            {"id": "work", "provider": "imap"},
            "IMAP TLS handshake failed",
        )
        self.assertEqual(down, "work: Couldn't reach IMAP.")

    def test_classifier_gives_sign_in_action_for_every_provider(self) -> None:
        cases = [
            ("gmail", "gmail", "invalid_grant: Token has been expired or revoked."),
            ("gmail", "gmail", "Gmail needs you to sign in again. In a terminal: x"),
            ("hey", "hey", "HEY is not signed in; run: hey auth login"),
            ("work", "outlook", "AADSTS70000: The provided grant has expired"),
            ("box", "imap", "IMAP login failed"),
            ("fm", "fastmail", "Fastmail API token missing"),
        ]
        for acc_id, provider, raw in cases:
            with self.subTest(provider=provider, raw=raw):
                message, action = common.classify_account_error(
                    {"id": acc_id, "provider": provider}, raw
                )
                name = common.PROVIDER_LABELS[provider]
                self.assertEqual(message, f"{acc_id}: {name} needs you to sign in again.")
                self.assertEqual(action["kind"], "signin")
                self.assertEqual(action["command"], common.login_command(provider, acc_id))
                self.assertTrue(action["command"].endswith(f" accounts login {acc_id}"))

    def test_classifier_setup_and_plain_failures(self) -> None:
        message, action = common.classify_account_error(
            {"id": "gmail", "provider": "gmail"}, "gws not found on PATH"
        )
        self.assertEqual(message, "gmail: Gmail isn't installed for this bar.")
        self.assertEqual(action, {"kind": "setup", "url": common.SETUP_GUIDE_URL + "#gmail"})
        self.assertTrue(action["url"].startswith("https://"))
        _, action = common.classify_account_error({"id": "h", "provider": "hey"}, "hey-cli not found")
        self.assertTrue(action["url"].endswith("/docs/ACCOUNTS.md#hey"))
        message, action = common.classify_account_error(
            {"id": "work", "provider": "imap"}, "IMAP TLS handshake failed"
        )
        self.assertEqual((message, action), ("work: Couldn't reach IMAP.", None))
        message, action = common.classify_account_error({"id": "work", "provider": "imap"}, "timed out")
        self.assertEqual((message, action), ("work: timed out", None))

    def test_fastmail_missing_token_hint_is_runnable(self) -> None:
        msg = common.account_error({"id": "fm", "provider": "fastmail"}, "Fastmail API token missing")
        self.assertIn("In a terminal: ", msg)
        self.assertTrue(msg.endswith(" accounts login fm"), msg)
        self.assertNotIn("accounts add", msg)

    def test_non_auth_error_is_prefixed_only(self) -> None:
        msg = common.account_error({"id": "work", "provider": "imap"}, "timed out")
        self.assertEqual(msg, "work: timed out")

    def test_is_auth_failure_http_401(self) -> None:
        self.assertTrue(common.is_auth_failure("Fastmail HTTP 401"))
        self.assertFalse(common.is_auth_failure("Fastmail HTTP 500"))
        self.assertFalse(common.is_auth_failure("could not reach host"))
        self.assertTrue(common.is_missing_tool("hey-cli not found. Install with: omarchy-mise-install"))
        self.assertTrue(common.is_unreachable("could not reach IMAP host"))

    def test_encode_decode_id(self) -> None:
        opaque = common.encode_id("work", "INBOX/12")
        self.assertEqual(common.decode_id(opaque), ("work", "INBOX/12"))


class LoginCommandTests(unittest.TestCase):
    """The panel prints this for you to paste. The plugin never puts
    `you-got-mail` on PATH, so the short name alone is not runnable."""

    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()

    def _env(self, home: Path, root: Path = ROOT) -> dict[str, str]:
        return {"HOME": str(home), "PATH": str(self.bindir), "YOU_GOT_MAIL_ROOT": str(root)}

    def test_not_on_path_uses_plugin_path_under_home(self) -> None:
        with patch.dict(os.environ, self._env(ROOT.parent)):
            cmd = common.login_command("gmail", "gmail")
        self.assertEqual(cmd, f"~/{ROOT.name}/bin/you-got-mail accounts login gmail")

    def test_not_on_path_outside_home_uses_absolute_path(self) -> None:
        with patch.dict(os.environ, self._env(self.tmp / "home")):
            cmd = common.login_command("outlook", "work")
        self.assertEqual(cmd, f"{ROOT}/bin/you-got-mail accounts login work")

    def test_plugin_root_with_space_is_quoted(self) -> None:
        root = self.tmp / "my plugin"
        with patch.dict(os.environ, self._env(self.tmp, root)):
            cli = common.cli_command()
        self.assertTrue(cli.startswith("~/"), cli)
        proc = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", f"printf '%s\\n' {cli}"],
            capture_output=True,
            text=True,
            env={"HOME": str(self.tmp), "PATH": "/usr/bin:/bin"},
            check=True,
        )
        self.assertEqual(proc.stdout, f"{root}/bin/you-got-mail\n")

    def test_short_name_when_path_links_to_this_plugin(self) -> None:
        (self.bindir / "you-got-mail").symlink_to(ROOT / "bin" / "you-got-mail")
        with patch.dict(os.environ, self._env(ROOT.parent)):
            cmd = common.login_command("gmail", "gmail")
        self.assertEqual(cmd, "you-got-mail accounts login gmail")

    def test_other_you_got_mail_on_path_is_not_trusted(self) -> None:
        other = self.bindir / "you-got-mail"
        other.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        other.chmod(0o755)
        with patch.dict(os.environ, self._env(ROOT.parent)):
            cmd = common.login_command("gmail", "gmail")
        self.assertEqual(cmd, f"~/{ROOT.name}/bin/you-got-mail accounts login gmail")

    def test_sign_in_hint_runs_in_a_fresh_shell(self) -> None:
        with patch.dict(os.environ, self._env(ROOT.parent)):
            msg = common.account_error(
                {"id": "gmail", "provider": "gmail"},
                "invalid_grant: Token has been expired or revoked.",
            )
        hint = msg.split("In a terminal: ", 1)[1]
        self.assertTrue(hint.endswith(" accounts login gmail"), msg)
        cli = hint[: -len(" accounts login gmail")]
        # No you-got-mail on PATH, like a terminal on a stock install.
        path = os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"])
        proc = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", f"{cli} --help"],
            capture_output=True,
            text=True,
            env={"HOME": str(ROOT.parent), "PATH": path},
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("accounts login", proc.stdout)


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


class HttpsOnlyTests(unittest.TestCase):
    def test_check_https_url_takes_only_https_on_the_one_host(self) -> None:
        host = "api.fastmail.com"
        for url in (
            "https://api.fastmail.com/jmap/api/",
            "https://API.Fastmail.com/jmap/api/",
            "https://api.fastmail.com:443/jmap/api/?a=b#c",
        ):
            common.check_https_url(url, host)
        for url in (
            "http://api.fastmail.com/jmap/api/",
            "https://api.fastmail.com.example.test/",
            "https://example.test/?host=api.fastmail.com",
            "https://user@api.fastmail.com/",
            "https://user:pw@api.fastmail.com/",
            "https://example.test\\@api.fastmail.com/",
            "https://api.fastmail.com:8443/",
            "https://api.fastmail.com:nope/",
            "https://api.fastmail.com./",
            "https://[::1]/",
            "//api.fastmail.com/jmap/api/",
            "file:///etc/passwd",
            "ftp://api.fastmail.com/",
            "data:,{}",
            "https://api.fastmail.com/a b",
            "https://api.fastmail.com/\r\nX-Injected: 1",
            "https://api.fastmail.com/\x7f",
            "",
            None,
            42,
        ):
            with self.assertRaises(common.UnexpectedUrlError, msg=repr(url)):
                common.check_https_url(url, host)

    def test_opener_handles_only_https_and_follows_no_redirect(self) -> None:
        import urllib.request

        kinds = {type(h) for h in common._HTTPS_OPENER.handlers}
        self.assertIn(urllib.request.HTTPSHandler, kinds)
        for unwanted in (
            urllib.request.HTTPRedirectHandler,
            urllib.request.HTTPHandler,
            urllib.request.FileHandler,
            urllib.request.FTPHandler,
            urllib.request.DataHandler,
            urllib.request.HTTPCookieProcessor,
        ):
            self.assertFalse(any(isinstance(h, unwanted) for h in common._HTTPS_OPENER.handlers), unwanted)
        # Even past the URL check, http: and file: have no handler here.
        for url in ("http://127.0.0.1:9/", "file:///etc/passwd"):
            with self.assertRaises(urllib.error.URLError):
                common._HTTPS_OPENER.open(urllib.request.Request(url), timeout=1)

    def _serve(self, status: int, headers: dict, body: "io.BytesIO"):
        """Answer the real opener chain's https_open with one canned response."""
        import email.message
        import urllib.request

        handler = next(h for h in common._HTTPS_OPENER.handlers if isinstance(h, urllib.request.HTTPSHandler))
        message = email.message.Message()
        for key, value in headers.items():
            message[key] = value
        requests = []

        def https_open(req):
            requests.append(req)
            resp = urllib.request.addinfourl(body, message, req.full_url, status)
            resp.msg = "canned"
            return resp

        return patch.object(handler, "https_open", side_effect=https_open), requests

    def test_redirect_is_an_error_with_its_body_unread_and_no_second_request(self) -> None:
        import io
        import urllib.error

        class Body(io.BytesIO):
            reads = 0

            def read(self, *args):
                Body.reads += 1
                return super().read(*args)

        for status in (301, 302, 303, 307, 308):
            Body.reads = 0
            served, requests = self._serve(status, {"Location": "https://example.test/steal"}, Body(b"x" * 1024))
            with served, self.assertRaises(urllib.error.HTTPError) as caught:
                common.open_https(
                    "https://api.fastmail.com/jmap/session",
                    "api.fastmail.com",
                    headers={"Authorization": "Bearer tok"},
                )
            caught.exception.close()
            self.assertEqual(caught.exception.code, status)
            self.assertEqual(len(requests), 1, status)
            # full_url, not host: an https_proxy setting moves host to the proxy.
            self.assertEqual(urllib.parse.urlsplit(requests[0].full_url).hostname, "api.fastmail.com")
            self.assertEqual(Body.reads, 0, status)

    def test_success_passes_through_and_headers_are_unredirected(self) -> None:
        import io

        served, requests = self._serve(200, {"Content-Type": "application/json"}, io.BytesIO(b"{}"))
        with served:
            with common.open_https(
                "https://graph.microsoft.com/v1.0/me",
                "graph.microsoft.com",
                method="POST",
                data=b"{}",
                headers={"Authorization": "Bearer tok", "Content-Type": "application/json"},
            ) as resp:
                self.assertEqual(common.read_http_body(resp), b"{}")
        (req,) = requests
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.unredirected_hdrs["Authorization"], "Bearer tok")
        self.assertEqual(req.headers, {})

    def test_open_https_checks_the_url_before_opening(self) -> None:
        with patch.object(common._HTTPS_OPENER, "open") as opened:
            with self.assertRaises(common.UnexpectedUrlError):
                common.open_https("https://example.test/", "api.fastmail.com", headers={"Authorization": "Bearer tok"})
        opened.assert_not_called()


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
        target.write_text('{"token":"secret"}\n', encoding="utf-8")
        os.chmod(target, 0o600)
        link = self.tmp / "link.json"
        link.symlink_to(target)
        data = common.load_secret_file(link, "fastmail")
        self.assertEqual(data, {})
        self.assertEqual(target.read_text(encoding="utf-8"), '{"token":"secret"}\n')

    def test_rejects_fifo_without_blocking(self) -> None:
        os.mkfifo(self.path)
        data = common.load_secret_file(self.path, "fastmail")
        self.assertEqual(data, {})

    def test_rejects_oversized_file(self) -> None:
        self.path.write_bytes(b"{" + b"x" * (common.MAX_LOCAL_FILE + 1) + b"}")
        os.chmod(self.path, 0o600)
        payload = capture_json(common.load_secret_file, self.path, "fastmail")
        self.assertFalse(payload["ok"])
        self.assertIn("too large", payload["error"])


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

    def test_reads_valid_accounts(self) -> None:
        common.ACCOUNTS_FILE.write_text(
            json.dumps({"accounts": [{"id": "work", "provider": "imap", "label": "Work"}]}),
            encoding="utf-8",
        )
        os.chmod(common.ACCOUNTS_FILE, 0o600)
        accounts = common.load_accounts()
        self.assertEqual(accounts[0]["id"], "work")
        self.assertEqual(accounts[0]["provider"], "imap")

    def test_symlink_is_implicit_gmail(self) -> None:
        target = self.tmp / "real.json"
        target.write_text(
            json.dumps({"accounts": [{"id": "work", "provider": "imap", "label": "Work"}]}),
            encoding="utf-8",
        )
        os.chmod(target, 0o600)
        common.ACCOUNTS_FILE.symlink_to(target)
        accounts = common.load_accounts()
        self.assertEqual(accounts[0]["provider"], "gmail")
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["accounts"][0]["id"], "work")

    def test_fifo_is_implicit_gmail(self) -> None:
        os.mkfifo(common.ACCOUNTS_FILE)
        accounts = common.load_accounts()
        self.assertEqual(accounts[0]["provider"], "gmail")

    def test_oversized_file_dies(self) -> None:
        common.ACCOUNTS_FILE.write_bytes(b"{" + b"x" * (common.MAX_LOCAL_FILE + 1) + b"}")
        os.chmod(common.ACCOUNTS_FILE, 0o600)
        payload = capture_json(common.load_accounts)
        self.assertFalse(payload["ok"])
        self.assertIn("too large", payload["error"])


class ManifestAndHelpTests(unittest.TestCase):
    def test_manifest_widget_settings(self) -> None:
        data = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+$")
        for name in ("Gmail", "Outlook", "Fastmail", "IMAP", "HEY"):
            self.assertIn(name, data["description"])
            self.assertIn(name, data["barWidget"]["description"])
        keys = {item["key"] for item in data["barWidget"]["schema"]}
        self.assertEqual(keys, {"max", "refreshIntervalSec", "soundEnabled",
                                "soundCooldownSec", "soundVolume", "soundFile"})
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


class OwnedFileReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        os.chmod(self.tmp, 0o700)
        self.path = self.tmp / "owned.json"

    def test_reads_regular_owned_file(self) -> None:
        self.path.write_bytes(b'{"ok":true}')
        os.chmod(self.path, 0o600)
        self.assertEqual(common.read_owned_file(self.path), b'{"ok":true}')

    def test_missing_path_returns_none(self) -> None:
        self.assertIsNone(common.read_owned_file(self.path))

    def test_symlink_returns_none(self) -> None:
        target = self.tmp / "real.json"
        target.write_bytes(b'{"token":"abc"}')
        os.chmod(target, 0o600)
        self.path.symlink_to(target)
        self.assertIsNone(common.read_owned_file(self.path))
        self.assertEqual(target.read_bytes(), b'{"token":"abc"}')

    def test_fifo_returns_none_without_blocking(self) -> None:
        os.mkfifo(self.path)
        self.assertIsNone(common.read_owned_file(self.path))

    def test_rejects_oversize_without_loading_all(self) -> None:
        self.path.write_bytes(b"x" * (common.MAX_LOCAL_FILE + 1))
        os.chmod(self.path, 0o600)
        with self.assertRaises(common.FileTooLargeError):
            common.read_owned_file(self.path)

    def test_accepts_file_at_limit(self) -> None:
        payload = b"x" * common.MAX_LOCAL_FILE
        self.path.write_bytes(payload)
        os.chmod(self.path, 0o600)
        self.assertEqual(common.read_owned_file(self.path), payload)

    def test_require_private_rejects_group_readable(self) -> None:
        self.path.write_bytes(b"{}")
        os.chmod(self.path, 0o644)
        with self.assertRaises(PermissionError) as caught:
            common.read_owned_file(self.path, require_private=True)
        self.assertIn("too open", str(caught.exception))

    def test_common_readers_do_not_use_path_read_text(self) -> None:
        source = (ROOT / "lib" / "common.py").read_text(encoding="utf-8")
        self.assertIn("O_NOFOLLOW", source)
        self.assertIn("O_NONBLOCK", source)
        self.assertNotIn(".read_text(", source)


class ConfigFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        os.chmod(self.tmp, 0o700)
        self._old_dir = common.CONFIG_DIR
        self._old_max = os.environ.pop("YOU_GOT_MAIL_MAX", None)
        common.CONFIG_DIR = self.tmp

    def tearDown(self) -> None:
        common.CONFIG_DIR = self._old_dir
        if self._old_max is None:
            os.environ.pop("YOU_GOT_MAIL_MAX", None)
        else:
            os.environ["YOU_GOT_MAIL_MAX"] = self._old_max

    def test_reads_max(self) -> None:
        path = self.tmp / "config"
        path.write_text("max = 12\n", encoding="utf-8")
        os.chmod(path, 0o600)
        self.assertEqual(common.max_messages(), 12)

    def test_symlink_falls_back_to_default(self) -> None:
        target = self.tmp / "real"
        target.write_text("max = 7\n", encoding="utf-8")
        os.chmod(target, 0o600)
        (self.tmp / "config").symlink_to(target)
        self.assertEqual(common.max_messages(), 25)

    def test_fifo_falls_back_to_default(self) -> None:
        os.mkfifo(self.tmp / "config")
        self.assertEqual(common.max_messages(), 25)

    def test_oversize_falls_back_to_default(self) -> None:
        path = self.tmp / "config"
        path.write_bytes(b"max = 9\n" + b"x" * (common.MAX_LOCAL_FILE + 1))
        os.chmod(path, 0o600)
        self.assertEqual(common.max_messages(), 25)



class OneLineTests(unittest.TestCase):
    def test_joiners_stay_and_invisible_marks_go(self) -> None:
        self.assertEqual(common.one_line("👩\u200d💻"), "👩\u200d💻")
        self.assertEqual(common.one_line("می\u200cخواهم"), "می\u200cخواهم")
        self.assertEqual(common.one_line("a\u200bb\u202ec\ufeff"), "abc")


class RunCappedTests(unittest.TestCase):
    def _run(self, script: str, timeout: float = 10, limit: int = 1024):
        return common.run_capped([sys.executable, "-c", script], dict(os.environ), timeout, limit)

    def test_returns_output_and_exit_code(self) -> None:
        proc = self._run("import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)")
        self.assertEqual(proc.stdout.strip(), "out")
        self.assertEqual(proc.stderr.strip(), "err")
        self.assertEqual(proc.returncode, 3)

    def test_stops_a_program_that_prints_too_much(self) -> None:
        with self.assertRaises(common.ResponseTooLargeError):
            self._run("import sys\nwhile True: sys.stdout.write('x' * 4096)")

    def test_too_much_on_stderr_also_stops_it(self) -> None:
        with self.assertRaises(common.ResponseTooLargeError):
            self._run("import sys\nwhile True: sys.stderr.write('x' * 4096)")

    def test_output_at_the_limit_is_fine(self) -> None:
        proc = self._run("import sys; sys.stdout.write('x' * 1024)")
        self.assertEqual(len(proc.stdout), 1024)

    def test_timeout_reaches_a_child_holding_the_pipes(self) -> None:
        import time

        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            self._run(
                "import subprocess, sys, time\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                "time.sleep(30)",
                timeout=0.5,
            )
        self.assertLess(time.monotonic() - started, 5)

    def test_outer_stop_reaches_a_nested_command(self) -> None:
        import time

        # The inner command stays in the outer group, so the outer timeout
        # stops it too instead of leaving it running unsupervised.
        inner = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(Path(common.__file__).parent)!r})\n"
            "import common\n"
            "common.run_capped([sys.executable, '-c', 'import time; time.sleep(30)'],"
            " dict(os.environ), 30, own_group=False)"
        )
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            self._run(inner, timeout=1)
        self.assertLess(time.monotonic() - started, 5)

    def test_leftover_children_are_stopped_when_it_exits(self) -> None:
        import time

        # The program exits at once but leaves a child holding its pipes.
        started = time.monotonic()
        proc = self._run(
            "import subprocess, sys\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "print('done')",
            timeout=10,
        )
        self.assertEqual(proc.stdout.strip(), "done")
        self.assertLess(time.monotonic() - started, 5)

    def test_nested_command_returns_although_its_child_holds_the_pipes(self) -> None:
        import time

        started = time.monotonic()
        proc = common.run_capped(
            [
                sys.executable,
                "-c",
                "import subprocess, sys\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'])\n"
                "print('done')",
            ],
            dict(os.environ),
            10,
            own_group=False,
        )
        self.assertEqual(proc.stdout.strip(), "done")
        self.assertEqual(proc.returncode, 0)
        self.assertLess(time.monotonic() - started, 3)

    def test_invalid_utf8_stays_visible(self) -> None:
        proc = self._run("import sys; sys.stdout.buffer.write(b'a\\xffb')")
        self.assertEqual(proc.stdout, "a\udcffb")
        with self.assertRaises(UnicodeEncodeError):
            proc.stdout.encode("utf-8")

    def test_helper_that_closed_its_pipes_is_stopped(self) -> None:
        import time

        proc = self._run(
            "import subprocess, sys\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],"
            " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "print(p.pid)"
        )
        pid = int(proc.stdout)
        for _ in range(40):
            try:
                state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(0.05)
        else:
            self.fail("helper still running")

    def test_stop_active_reaches_a_running_command(self) -> None:
        import threading
        import time

        self.addCleanup(common._CANCELLED.clear)

        result = {}

        def run() -> None:
            result["proc"] = self._run("import time; time.sleep(30)", timeout=30)

        thread = threading.Thread(target=run)
        started = time.monotonic()
        thread.start()
        while not common._ACTIVE_GROUPS and time.monotonic() - started < 5:
            time.sleep(0.02)
        common.stop_active()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["proc"].returncode, -9)
        self.assertEqual(common._ACTIVE_GROUPS, set())
        # And nothing starts after it.
        with self.assertRaises(common.Cancelled):
            self._run("print('late')")

    def test_a_reaped_group_is_no_longer_registered(self) -> None:
        seen = []
        real_wait = subprocess.Popen.wait

        def wait(proc, *args, **kwargs):
            seen.append(proc.pid in common._ACTIVE_GROUPS)
            return real_wait(proc, *args, **kwargs)

        with patch.object(subprocess.Popen, "wait", wait):
            self._run("print('ok')")
        self.assertTrue(seen)
        self.assertFalse(any(seen))

    def test_timeout_kills_the_program(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            self._run("import time; time.sleep(30)", timeout=0.5)


if __name__ == "__main__":
    unittest.main()
