from __future__ import annotations

import unittest
from unittest.mock import patch

from support import capture_json, load_provider


class FastmailReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fm = load_provider("fastmail")

    def _read(self, responses: list) -> dict:
        with patch.object(self.fm, "_session", return_value={"primaryAccounts": {"urn:ietf:params:jmap:mail": "acc"}}), patch.object(
            self.fm, "_jmap", return_value=responses
        ):
            return capture_json(self.fm.cmd_read, "token", "msg-1")

    def test_success_requires_updated_id(self) -> None:
        payload = self._read([["Email/set", {"updated": {"msg-1": {}}}, "s"]])
        self.assertEqual(payload, {"ok": True})

    def test_not_updated_is_failure(self) -> None:
        payload = self._read(
            [["Email/set", {"updated": {}, "notUpdated": {"msg-1": {"type": "notFound"}}}, "s"]]
        )
        self.assertFalse(payload["ok"])

    def test_missing_set_result_is_failure(self) -> None:
        payload = self._read([["error", {"description": "nope"}, "s"]])
        self.assertFalse(payload["ok"])


class HeyUnreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hey = load_provider("hey")

    def test_envelope_unseen_count(self) -> None:
        payload_box = {
            "ok": True,
            "data": {
                "unseen_count": 100,
                "app_url": "https://app.hey.com/imbox",
                "postings": [
                    {"id": "1", "account_id": "acc", "seen": False, "name": "One\nline", "created_at": "2026-01-01T00:00:00Z"},
                    {"id": "2", "account_id": "acc", "seen": False, "name": "Two", "created_at": "2026-01-02T00:00:00Z"},
                ],
            },
        }
        with patch.object(self.hey, "_hey", return_value=payload_box):
            out = capture_json(self.hey.cmd_list, {"id": "hey", "label": "HEY"}, 25)
        self.assertTrue(out["ok"])
        self.assertEqual(out["unread"], 100)
        self.assertEqual(len(out["messages"]), 2)
        self.assertEqual(out["messages"][0]["subject"], "One line")

    def test_pages_until_limit_even_with_envelope(self) -> None:
        calls = {"n": 0}

        def fake_hey(acc, args, timeout=40):
            calls["n"] += 1
            page = "2" if "--page" not in args else ""
            return {
                "ok": True,
                "data": {
                    "unseen_count": 80,
                    "next_page": page,
                    "postings": [
                        {
                            "id": f"p{calls['n']}-{i}",
                            "account_id": "acc",
                            "seen": False,
                            "name": f"Msg {i}",
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                        for i in range(2)
                    ],
                },
            }

        with patch.object(self.hey, "_hey", side_effect=fake_hey):
            out = capture_json(self.hey.cmd_list, {"id": "hey"}, 3)
        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(out["unread"], 80)
        self.assertEqual(len(out["messages"]), 3)


class OutlookUnreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.out = load_provider("outlook")

    def test_folder_unread_skips_junk(self) -> None:
        inbox = "inbox-id"
        junk = "junk-id"

        def fake_http(method, url, token, payload=None, extra_headers=None):
            if "childFolders" in url:
                return {"value": []}
            return {
                "value": [
                    {"id": inbox, "unreadItemCount": 90},
                    {"id": junk, "unreadItemCount": 12},
                ]
            }

        with patch.object(self.out, "_http", side_effect=fake_http):
            total = self.out._folder_unread_total("tok", {junk})
        self.assertEqual(total, 90)

    def test_one_line_preview(self) -> None:
        self.assertEqual(self.out.one_line("Hi\r\nthere"), "Hi there")


class GmailScriptTests(unittest.TestCase):
    def test_counts_matching_ids_not_size_estimate(self) -> None:
        from support import ROOT

        script = (ROOT / "providers" / "gmail").read_text(encoding="utf-8")
        self.assertIn("unread_total", script)
        self.assertNotIn("unread_estimate", script)
        self.assertNotIn("resultSizeEstimate", script)
        # Display pages stay small; a 500-wide list is only the count path.
        self.assertIn('--argjson n 500', script)


if __name__ == "__main__":
    unittest.main()
