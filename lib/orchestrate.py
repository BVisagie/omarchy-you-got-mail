"""Fan out list/read across configured accounts and merge unread mail."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import (
    FETCH_CAP,
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
    secret_path,
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


def _text(value, limit: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return one_line(str(value), limit)


def _url(value) -> str:
    url = value.strip() if isinstance(value, str) else ""
    if len(url) > MAX_URL or not url.startswith("https://"):
        return ""
    return url


def _error(payload: dict, fallback: str) -> str:
    return _text(payload.get("error"), MAX_ERROR) or fallback


def _run_provider(account: dict, args: list[str], timeout: int = LIST_TIMEOUT) -> dict:
    provider = account["provider"]
    env = os.environ.copy()
    env["YOU_GOT_MAIL_ACCOUNT_ID"] = account["id"]
    env["YOU_GOT_MAIL_ACCOUNT_JSON"] = json.dumps(account, separators=(",", ":"))
    env["YOU_GOT_MAIL_SECRET_FILE"] = str(secret_path(account["id"]))
    env["YOU_GOT_MAIL_MAX"] = os.environ.get("YOU_GOT_MAIL_MAX", str(max_messages()))
    env["YOU_GOT_MAIL_FETCH"] = os.environ.get("YOU_GOT_MAIL_FETCH", env["YOU_GOT_MAIL_MAX"])
    try:
        proc = subprocess.run(
            [str(provider_path(provider)), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{account['id']}: timed out"}
    except OSError as exc:
        return {"ok": False, "error": f"{account['id']}: {exc}"}
    text = (proc.stdout or "").strip()
    if not text:
        err = (proc.stderr or "").strip()
        return {"ok": False, "error": f"{account['id']}: {err or 'no output'}"}
    try:
        payload = json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": f"{account['id']}: provider returned invalid JSON"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": f"{account['id']}: provider returned invalid JSON"}
    if proc.returncode != 0 and payload.get("ok"):
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
        if not local_id or len(local_id) > MAX_ID:
            continue
        labels = msg.get("labels")
        tagged.append(
            {
                "id": encode_id(account["id"], local_id),
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

    def work(acc: dict) -> tuple[dict, dict, float]:
        payload = _run_provider(acc, ["list", "--limit", fetch])
        return acc, payload, time.time()

    checked_at: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as pool:
        futures = [pool.submit(work, acc) for acc in accounts]
        for fut in as_completed(futures):
            acc, payload, finished_at = fut.result()
            if not payload.get("ok"):
                msg = account_error(acc, _error(payload, "failed"))
                errors.append(msg)
                error_by_id[acc["id"]] = msg
                continue
            payloads[acc["id"]] = payload
            checked_at[acc["id"]] = finished_at
            unread += _count(payload.get("unread"))
            email = _text(payload.get("email"), MAX_TEXT)
            if email:
                emails.append(email)
            merged.extend(_tag_messages(acc, payload, int(fetch)))

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
                    "unread": _count(payload.get("unread")),
                    "searchUrl": _url(payload.get("searchUrl")),
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
    payload = _run_provider(acc, ["read", local_id])
    if not payload.get("ok"):
        die(_error(payload, "could not mark as read"))
    emit({"ok": True})


def cmd_read_all() -> None:
    accounts = load_accounts()
    errors: list[str] = []
    marked = 0
    succeeded = 0

    def work(acc: dict) -> tuple[dict, dict]:
        return acc, _run_provider(acc, ["read-all"], timeout=READ_ALL_TIMEOUT)

    with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as pool:
        futures = [pool.submit(work, acc) for acc in accounts]
        for fut in as_completed(futures):
            acc, payload = fut.result()
            marked += _count(payload.get("marked"))
            if payload.get("ok"):
                succeeded += 1
                continue
            errors.append(account_error(acc, _error(payload, "failed")))

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
