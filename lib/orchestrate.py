"""Fan out list/read across configured accounts and merge unread mail."""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

from common import (
    FETCH_CAP,
    Cancelled,
    ResponseTooLargeError,
    account_error,
    classify_account_error,
    decode_id,
    die,
    emit,
    encode_id,
    load_accounts,
    max_messages,
    needs_sign_in,
    one_line,
    provider_path,
    run_capped,
    secret_path,
    stop_active,
)

LIST_TIMEOUT = 45
READ_ALL_TIMEOUT = 120

# Provider output is data from a mail server or another program. Everything
# the panel draws or acts on is checked and cut to size here, once, so one
# odd value can neither fail the other accounts nor flood the panel.
MAX_COUNT = 10_000_000
MAX_TS = 4_102_444_800  # 2100-01-01
MAX_ID = 512
MAX_URL = 2048
MAX_TEXT = 300
MAX_SNIPPET = 400
MAX_ERROR = 500
MAX_LABELS = 10
MAX_LABEL = 60
MAX_PROVIDER_OUTPUT = 16 * 1024 * 1024


def _bounded_int(value, ceiling: int) -> int:
    """A whole number in 0..ceiling; anything that is not a number is 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and math.isfinite(value):
        number = int(value)
    elif isinstance(value, str) and value.strip().isascii():
        try:
            number = int(value.strip())
        except ValueError:
            return 0
    else:
        return 0
    return min(max(number, 0), ceiling)


def _count(value) -> int:
    return _bounded_int(value, MAX_COUNT)


def _ts(value) -> int:
    ts = _bounded_int(value, MAX_TS + 1)
    return ts if ts <= MAX_TS else 0


def _clean(value: str) -> str:
    # JSON can carry a lone surrogate, which cannot be written back out.
    return value.encode("utf-8", "replace").decode("utf-8")


def _text(value, limit: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return one_line(_clean(str(value)), limit)


# The panel opens only links of this shape (MailState.validUrl); anything else
# is unusable here too, so the CLI and the panel agree. JavaScript's \s also
# covers U+FEFF, which Python's does not, and its \d is ASCII only.
PANEL_URL = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:[/?#][^\s\ufeff]*)?")

# A link that is present but unusable stays unusable: an empty link would let
# a click mark the message read without opening anything.
BAD_URL = "invalid:"


def _url(value) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return BAD_URL
    try:
        value.encode("utf-8")  # a lone surrogate would be rewritten, not kept
    except UnicodeEncodeError:
        return BAD_URL
    url = value
    # A control character cannot travel whole to the browser, so a link
    # carrying one, even at its end, is not opened.
    if len(url) > MAX_URL or not PANEL_URL.fullmatch(url) or any(
        ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url
    ):
        return BAD_URL
    # A host and, if given, a port the browser can use.
    try:
        parts = urlsplit(url)
        parts.port
    except ValueError:
        return BAD_URL
    host = parts.hostname
    if not host:
        return BAD_URL
    # A browser reads a host whose last label is a number as an IPv4 address,
    # so it must be a valid one.
    last = host.rstrip(".").rsplit(".", 1)[-1]
    if re.fullmatch(r"[0-9]+|0[xX][0-9a-fA-F]*", last):
        try:
            ipaddress.IPv4Address(host[:-1] if host.endswith(".") else host)
        except ValueError:
            return BAD_URL
    return url


def _search_url(value) -> str:
    # An inbox link has no read side effect, so an unusable one is just absent.
    url = _url(value)
    return "" if url == BAD_URL else url


def _error(payload: dict, fallback: str) -> str:
    return _text(payload.get("error"), MAX_ERROR) or fallback


def _each(accounts: list[dict], work) -> list:
    """work(account) for every account, up to 8 at once; the results in the
    order they finished.

    Providers run in sessions of their own, out of reach of a terminal's
    Ctrl+C, and the pool would wait for them, still reading or marking mail.
    So an interrupt at any point, while submitting or collecting, cancels the
    accounts still queued and stops the providers running before it waits.
    """
    # All results are gathered before the caller sees any, so what the caller
    # does with them, even exiting, cannot look like an interrupt here.
    pool = ThreadPoolExecutor(max_workers=min(8, len(accounts)))
    try:
        futures = [pool.submit(work, acc) for acc in accounts]
        results = [future.result() for future in as_completed(futures)]
    except BaseException:
        stop_active()  # and no account that slips through can start one
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return results


def _run_provider(account: dict, args: list[str], timeout: int = LIST_TIMEOUT) -> dict:
    provider = account["provider"]
    env = os.environ.copy()
    env["YOU_GOT_MAIL_ACCOUNT_ID"] = account["id"]
    env["YOU_GOT_MAIL_ACCOUNT_JSON"] = json.dumps(account, separators=(",", ":"))
    env["YOU_GOT_MAIL_SECRET_FILE"] = str(secret_path(account["id"]))
    env["YOU_GOT_MAIL_MAX"] = os.environ.get("YOU_GOT_MAIL_MAX", str(max_messages()))
    env["YOU_GOT_MAIL_FETCH"] = os.environ.get("YOU_GOT_MAIL_FETCH", env["YOU_GOT_MAIL_MAX"])
    try:
        proc = run_capped(
            [str(provider_path(provider)), *args], env, timeout, MAX_PROVIDER_OUTPUT
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{account['id']}: timed out"}
    except ResponseTooLargeError:
        return {"ok": False, "error": f"{account['id']}: provider sent more output than expected"}
    except Cancelled:
        return {"ok": False, "error": f"{account['id']}: stopped"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"{account['id']}: {exc}"}
    text = (proc.stdout or "").strip()
    if not text:
        err = _text(proc.stderr, MAX_ERROR)
        return {"ok": False, "error": f"{account['id']}: {err or 'no output'}"}
    try:
        payload = json.loads(text.split("\n")[-1])
    except (ValueError, RecursionError):
        return {"ok": False, "error": f"{account['id']}: provider returned invalid JSON"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": f"{account['id']}: provider returned invalid JSON"}
    # Only a JSON true is success; "false" and 1 are not.
    payload["ok"] = payload.get("ok") is True
    if proc.returncode != 0 and payload["ok"]:
        return {"ok": False, "error": f"{account['id']}: provider exited {proc.returncode}"}
    return payload


def _tag_messages(account: dict, payload: dict, limit: int) -> list[dict]:
    label = _text(account.get("label") or account["id"], MAX_TEXT)
    rows = payload.get("messages")
    tagged = []
    for msg in rows if isinstance(rows, list) else []:
        if len(tagged) >= limit:
            break
        if not isinstance(msg, dict):
            continue
        local_id = msg.get("id")
        if isinstance(local_id, bool) or not isinstance(local_id, (str, int)):
            continue
        local_id = str(local_id)
        # NUL cannot travel back as a command argument when the row is read.
        if not local_id or "\x00" in local_id:
            continue
        # The panel takes ids whose encoded part fits MAX_ID characters.
        try:
            opaque = encode_id(account["id"], local_id)
        except UnicodeEncodeError:
            continue
        if len(opaque.split(":", 1)[1]) > MAX_ID:
            continue
        labels = msg.get("labels")
        tagged.append(
            {
                "id": opaque,
                "account": label,
                "subject": _text(msg.get("subject"), MAX_TEXT),
                "from": _text(msg.get("from"), MAX_TEXT),
                "snippet": _text(msg.get("snippet"), MAX_SNIPPET),
                "ts": _ts(msg.get("ts")),
                "url": _url(msg.get("url")),
                "labels": [
                    _text(lab, MAX_LABEL)
                    for lab in (labels if isinstance(labels, list) else [])[:MAX_LABELS]
                    if _text(lab, MAX_LABEL)
                ],
            }
        )
    return tagged


def cmd_list(page_token: str) -> None:
    accounts = load_accounts()
    page = 0
    if page_token:
        try:
            page = int(page_token)
        except ValueError:
            page = 0
        if page < 0:
            page = 0
    per = max_messages()
    start = page
    needed = start + per
    fetch = str(min(FETCH_CAP, max(per, needed)))
    os.environ["YOU_GOT_MAIL_FETCH"] = fetch

    errors: list[str] = []
    error_by_id: dict[str, str] = {}
    merged: list[dict] = []
    unread = 0
    emails = []
    payloads: dict[str, dict] = {}

    # Each worker keeps only the checked, bounded part of its reply, so what
    # is held until every account finishes does not grow with reply size.
    def work(acc: dict) -> tuple[dict, dict, float]:
        payload = _run_provider(acc, ["list", "--limit", fetch])
        if not payload.get("ok"):
            return acc, {"ok": False, "error": _error(payload, "failed")}, time.time()
        summary = {
            "ok": True,
            "unread": _count(payload.get("unread")),
            "email": _text(payload.get("email"), MAX_TEXT),
            "searchUrl": _search_url(payload.get("searchUrl")),
            "rows": _tag_messages(acc, payload, int(fetch)),
        }
        return acc, summary, time.time()

    checked_at: dict[str, float] = {}
    for acc, payload, finished_at in _each(accounts, work):
        if not payload["ok"]:
            msg = account_error(acc, payload["error"])
            errors.append(msg)
            error_by_id[acc["id"]] = msg
            continue
        payloads[acc["id"]] = payload
        checked_at[acc["id"]] = finished_at
        # QML holds the total in a 32-bit int.
        unread = min(unread + payload["unread"], MAX_COUNT)
        if payload["email"]:
            emails.append(payload["email"])
        merged.extend(payload["rows"])

    inboxes = []
    signin = False
    for acc in accounts:
        label = _text(acc.get("label") or acc["id"], MAX_TEXT)
        payload = payloads.get(acc["id"])
        if payload:
            inboxes.append(
                {
                    "id": acc["id"],
                    "account": label,
                    "checkedAt": checked_at[acc["id"]],
                    "unread": payload["unread"],
                    "searchUrl": payload["searchUrl"],
                    "ok": True,
                    "needsSignIn": False,
                }
            )
            continue
        err = error_by_id.get(acc["id"], "failed")
        acc_signin = needs_sign_in(err)
        if acc_signin:
            signin = True
        message, action = classify_account_error(acc, err)
        box = {
            "id": acc["id"],
            "account": label,
            "unread": 0,
            "searchUrl": "",
            "ok": False,
            "needsSignIn": acc_signin,
            "error": err,
            "message": message,
        }
        if action:
            box["action"] = action
        inboxes.append(box)

    if not payloads and errors:
        err = errors[0] if len(errors) == 1 else "all accounts failed: " + "; ".join(errors)
        emit(
            {
                "ok": False,
                "error": err,
                "needsSignIn": signin,
                "unread": 0,
                "messages": [],
                "inboxes": inboxes,
                "accountCount": len(accounts),
                "searchUrl": "",
                "nextPage": "",
                "thisPage": str(start),
            }
        )
        return

    merged.sort(key=lambda m: m["ts"], reverse=True)
    chunk = merged[start : start + per]
    # A message in the global top N must be in each account's top N, so
    # fetching `start + per` from every provider is enough for this page.
    # Do not offer a page past FETCH_CAP — that offset would be empty.
    next_start = start + per
    capped_total = min(max(len(merged), unread), FETCH_CAP)
    next_page = str(next_start) if next_start < capped_total else ""

    email = emails[0] if len(emails) == 1 else ""
    search_url = ""
    if len(accounts) == 1:
        search_url = str(inboxes[0].get("searchUrl") or "") if inboxes else ""

    out = {
        "ok": True,
        "email": email,
        "unread": unread,
        "searchUrl": search_url,
        "inboxes": inboxes,
        "nextPage": next_page,
        "thisPage": str(start),
        "accountCount": len(accounts),
        "messages": chunk,
    }
    if errors:
        out["warning"] = "; ".join(errors)
    if signin:
        out["needsSignIn"] = True
    emit(out)


def cmd_read(opaque: str) -> None:
    account_id, local_id = decode_id(opaque)
    accounts = {a["id"]: a for a in load_accounts()}
    acc = accounts.get(account_id)
    if not acc:
        die("unknown account")
    # Through _each like the others: the provider runs on a worker thread,
    # which a signal never interrupts, and an interrupt here stops it.
    def work(acc: dict) -> dict:
        payload = _run_provider(acc, ["read", local_id])
        return {"ok": bool(payload.get("ok")), "error": _error(payload, "could not mark as read")}

    (result,) = _each([acc], work)
    if not result["ok"]:
        die(result["error"])
    emit({"ok": True})


def cmd_read_all() -> None:
    accounts = load_accounts()
    errors: list[str] = []
    marked = 0
    succeeded = 0

    # Only what the totals need is kept until every account finishes.
    def work(acc: dict) -> tuple[dict, dict]:
        payload = _run_provider(acc, ["read-all"], timeout=READ_ALL_TIMEOUT)
        return acc, {
            "ok": bool(payload.get("ok")),
            "marked": _count(payload.get("marked")),
            "error": _error(payload, "failed"),
        }

    for acc, payload in _each(accounts, work):
        marked = min(marked + payload["marked"], MAX_COUNT)
        if payload["ok"]:
            succeeded += 1
            continue
        errors.append(account_error(acc, payload["error"]))

    signin = any(needs_sign_in(e) for e in errors)
    if succeeded == 0:
        err = errors[0] if len(errors) == 1 else "all accounts failed: " + "; ".join(errors)
        payload = {"ok": False, "error": err, "marked": marked}
        if signin:
            payload["needsSignIn"] = True
        emit(payload)
        return

    out: dict = {"ok": True, "marked": marked}
    if errors:
        out["warning"] = "; ".join(errors)
    if signin:
        out["needsSignIn"] = True
    emit(out)
