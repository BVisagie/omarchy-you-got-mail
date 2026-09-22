from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import patch

import orchestrate
from support import capture_json, message


def _account(acc_id: str, provider: str, label: str) -> dict:
    return {"id": acc_id, "provider": provider, "label": label}


class ProviderResultTests(unittest.TestCase):
    def test_nonzero_provider_exit_cannot_report_success(self) -> None:
        process = subprocess.CompletedProcess([], 1, '{"ok":true}', '')
        with patch.object(orchestrate.subprocess, "run", return_value=process):
            result = orchestrate._run_provider(_account("gmail", "gmail", "Gmail"), ["read", "one"])
        self.assertFalse(result["ok"])
        self.assertIn("exited 1", result["error"])

    def test_successful_exit_preserves_provider_failure(self) -> None:
        process = subprocess.CompletedProcess([], 0, '{"ok":false,"error":"permission denied"}', '')
        with patch.object(orchestrate.subprocess, "run", return_value=process):
            result = orchestrate._run_provider(_account("gmail", "gmail", "Gmail"), ["read", "one"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "permission denied")


class AccountStatusTests(unittest.TestCase):
    def test_every_inbox_has_id_and_only_successes_have_finish_time(self) -> None:
        accounts = [
            _account("work", "gmail", "Mail"),
            _account("personal", "imap", "Mail"),
        ]
        def run(acc, args):
            return {"ok": True, "unread": 0} if acc["id"] == "work" else {"ok": False, "error": "offline"}
        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ), patch.object(orchestrate.time, "time", return_value=1234):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual([box["id"] for box in payload["inboxes"]], ["work", "personal"])
        self.assertEqual(payload["inboxes"][0]["checkedAt"], 1234)
        self.assertNotIn("checkedAt", payload["inboxes"][1])
        self.assertEqual(payload["unread"], 0)

    def test_total_failure_keeps_all_account_ids_without_fresh_check_times(self) -> None:
        accounts = [_account("work", "gmail", "Work"), _account("home", "imap", "Home")]
        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", return_value={"ok": False, "error": "offline"}
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertFalse(payload["ok"])
        self.assertEqual([box["id"] for box in payload["inboxes"]], ["work", "home"])
        self.assertTrue(all("checkedAt" not in box for box in payload["inboxes"]))


class PaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["YOU_GOT_MAIL_MAX"] = "25"

    def tearDown(self) -> None:
        os.environ.pop("YOU_GOT_MAIL_MAX", None)
        os.environ.pop("YOU_GOT_MAIL_FETCH", None)

    def test_merged_next_page_follows_unread_total(self) -> None:
        accounts = [_account("gmail", "gmail", "Gmail")]
        rows = [message(f"m{i}", 1000 - i) for i in range(25)]

        def run(acc: dict, args: list[str]) -> dict:
            self.assertIn("--limit", args)
            return {"ok": True, "unread": 100, "messages": rows, "searchUrl": "https://mail.google.com"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["unread"], 100)
        self.assertEqual(len(payload["messages"]), 25)
        self.assertEqual(payload["nextPage"], "25")

    def test_second_page_fetches_offset_plus_page_size(self) -> None:
        accounts = [_account("gmail", "gmail", "Gmail")]
        seen = {}

        def run(acc: dict, args: list[str]) -> dict:
            limit = int(args[args.index("--limit") + 1])
            seen["limit"] = limit
            rows = [message(f"m{i}", 2000 - i) for i in range(limit)]
            return {"ok": True, "unread": 80, "messages": rows}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "25")
        self.assertEqual(seen["limit"], 50)
        self.assertEqual(payload["thisPage"], "25")
        self.assertEqual(payload["messages"][0]["id"].startswith("gmail:"), True)
        self.assertEqual(len(payload["messages"]), 25)
        self.assertEqual(payload["nextPage"], "50")

    def test_multi_account_newest_first(self) -> None:
        accounts = [
            _account("a", "gmail", "Gmail"),
            _account("b", "outlook", "Outlook"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            limit = int(args[args.index("--limit") + 1])
            if acc["id"] == "a":
                rows = [message(f"a{i}", 100 - i) for i in range(limit)]
                return {"ok": True, "unread": 40, "messages": rows}
            rows = [message(f"b{i}", 500 - i) for i in range(limit)]
            return {"ok": True, "unread": 40, "messages": rows}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertEqual(payload["unread"], 80)
        self.assertEqual(payload["accountCount"], 2)
        first_ids = [m["id"].split(":")[0] for m in payload["messages"]]
        self.assertTrue(all(acc == "b" for acc in first_ids))
        self.assertEqual(payload["nextPage"], "25")

    def test_no_empty_page_past_fetch_cap(self) -> None:
        os.environ["YOU_GOT_MAIL_MAX"] = "50"
        accounts = [_account("gmail", "gmail", "Gmail")]

        def run(acc: dict, args: list[str]) -> dict:
            limit = int(args[args.index("--limit") + 1])
            rows = [message(f"m{i}", 3000 - i) for i in range(limit)]
            return {"ok": True, "unread": 1000, "messages": rows}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "150")
        self.assertEqual(len(payload["messages"]), 50)
        self.assertEqual(payload["nextPage"], "")

    def test_partial_failure_sets_warning(self) -> None:
        accounts = [
            _account("a", "gmail", "Gmail"),
            _account("b", "hey", "HEY"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            if acc["id"] == "b":
                return {"ok": False, "error": "b failed"}
            return {
                "ok": True,
                "unread": 2,
                "messages": [message("1", 1), message("2", 2)],
                "searchUrl": "https://mail.google.com",
            }

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["accountCount"], 2)
        self.assertEqual(payload["unread"], 2)
        self.assertEqual(payload["warning"], "b: b failed")
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(len(payload["inboxes"]), 2)
        self.assertTrue(payload["inboxes"][0]["ok"])
        self.assertFalse(payload["inboxes"][1]["ok"])
        self.assertEqual(payload["inboxes"][1]["error"], "b: b failed")
        self.assertNotIn("needsSignIn", payload)

    def test_empty_success_plus_auth_failure_is_warning(self) -> None:
        accounts = [
            _account("gmail", "gmail", "Gmail"),
            _account("outlook", "outlook", "Outlook"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            if acc["id"] == "gmail":
                return {
                    "ok": False,
                    "error": (
                        "Authentication failed: Failed to get token: Server error: "
                        "invalid_grant: Token has been expired or revoked."
                    ),
                }
            return {"ok": True, "unread": 0, "messages": [], "searchUrl": "https://outlook.live.com/mail/inbox"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["unread"], 0)
        self.assertEqual(payload["messages"], [])
        self.assertTrue(payload["needsSignIn"])
        self.assertIn("gmail: Gmail needs you to sign in again", payload["warning"])
        self.assertIn("you-got-mail accounts login gmail", payload["warning"])
        self.assertNotIn("invalid_grant", payload["warning"])
        self.assertEqual(len(payload["inboxes"]), 2)
        gmail_box = next(box for box in payload["inboxes"] if box["account"] == "Gmail")
        outlook_box = next(box for box in payload["inboxes"] if box["account"] == "Outlook")
        self.assertFalse(gmail_box["ok"])
        self.assertTrue(gmail_box["needsSignIn"])
        self.assertEqual(gmail_box["id"], "gmail")
        self.assertEqual(gmail_box["message"], "gmail: Gmail needs you to sign in again.")
        self.assertEqual(gmail_box["action"]["kind"], "signin")
        self.assertTrue(gmail_box["action"]["command"].endswith("you-got-mail accounts login gmail"))
        self.assertNotIn("action", outlook_box)
        self.assertTrue(outlook_box["ok"])
        self.assertEqual(outlook_box["unread"], 0)

    def test_auth_failure_with_other_unread_keeps_count(self) -> None:
        accounts = [
            _account("gmail", "gmail", "Gmail"),
            _account("outlook", "outlook", "Outlook"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            if acc["id"] == "gmail":
                return {"ok": False, "error": "invalid_grant"}
            return {
                "ok": True,
                "unread": 2,
                "messages": [message("1", 1), message("2", 2)],
                "searchUrl": "https://outlook.live.com/mail/inbox",
            }

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["unread"], 2)
        self.assertTrue(payload["needsSignIn"])
        self.assertEqual(len(payload["messages"]), 2)

    def test_all_accounts_fail_list_is_error(self) -> None:
        accounts = [
            _account("gmail", "gmail", "Gmail"),
            _account("outlook", "outlook", "Outlook"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            return {"ok": False, "error": acc["id"] + " down"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertFalse(payload["ok"])
        self.assertIn("all accounts failed", payload["error"])
        self.assertIn("gmail: gmail down", payload["error"])
        self.assertIn("outlook: outlook down", payload["error"])

    def test_all_accounts_fail_still_carries_fix_actions(self) -> None:
        accounts = [
            _account("gmail", "gmail", "Gmail"),
            _account("home", "hey", "HEY"),
            _account("work", "imap", "Work"),
        ]
        errors = {
            "gmail": "invalid_grant",
            "home": "hey-cli not found",
            "work": "timed out",
        }

        def run(acc: dict, args: list[str]) -> dict:
            return {"ok": False, "error": errors[acc["id"]]}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertFalse(payload["ok"])
        boxes = {box["id"]: box for box in payload["inboxes"]}
        self.assertEqual(boxes["gmail"]["action"]["kind"], "signin")
        self.assertEqual(boxes["home"]["action"]["kind"], "setup")
        self.assertEqual(boxes["home"]["message"], "home: HEY isn't installed for this bar.")
        self.assertNotIn("action", boxes["work"])
        self.assertEqual(boxes["work"]["message"], "work: timed out")


class ReadAllTests(unittest.TestCase):
    def test_full_success_sums_marked(self) -> None:
        accounts = [_account("a", "gmail", "Gmail"), _account("b", "hey", "HEY")]
        seen = []

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            seen.append((acc["id"], args, timeout))
            return {"ok": True, "marked": 3 if acc["id"] == "a" else 2}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertEqual(payload, {"ok": True, "marked": 5})
        self.assertEqual({row[0] for row in seen}, {"a", "b"})
        self.assertTrue(all(row[1] == ["read-all"] for row in seen))
        self.assertTrue(all(row[2] == orchestrate.READ_ALL_TIMEOUT for row in seen))

    def test_partial_account_failure_keeps_warning_and_marks(self) -> None:
        accounts = [_account("a", "gmail", "Gmail"), _account("b", "hey", "HEY")]

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            if acc["id"] == "b":
                return {"ok": False, "marked": 1, "error": "b failed"}
            return {"ok": True, "marked": 4}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["marked"], 5)
        self.assertEqual(payload["warning"], "b: b failed")

    def test_all_accounts_fail_includes_partial_marks(self) -> None:
        accounts = [_account("a", "gmail", "Gmail"), _account("b", "hey", "HEY")]

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            return {"ok": False, "marked": 2 if acc["id"] == "a" else 0, "error": acc["id"] + " failed"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["marked"], 2)
        self.assertIn("all accounts failed", payload["error"])

    def test_timeout_uses_read_all_budget(self) -> None:
        accounts = [_account("a", "gmail", "Gmail")]

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            self.assertEqual(timeout, 120)
            return {"ok": False, "error": "a: timed out"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["marked"], 0)
        self.assertEqual(payload["error"], "a: timed out")


if __name__ == "__main__":
    unittest.main()
