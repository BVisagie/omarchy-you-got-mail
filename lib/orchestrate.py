"""Fan out list/read across configured accounts and merge unread mail."""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import (
    decode_id,
    die,
    emit,
    encode_id,
    load_accounts,
    max_messages,
    provider_path,
    secret_path,
)


def _run_provider(account: dict, args: list[str]) -> dict:
    provider = account["provider"]
    env = os.environ.copy()
    env["YOU_GOT_MAIL_ACCOUNT_ID"] = account["id"]
    env["YOU_GOT_MAIL_ACCOUNT_JSON"] = json.dumps(account, separators=(",", ":"))
    env["YOU_GOT_MAIL_SECRET_FILE"] = str(secret_path(account["id"]))
    env["YOU_GOT_MAIL_MAX"] = os.environ.get("YOU_GOT_MAIL_MAX", str(max_messages()))
    try:
        proc = subprocess.run(
            [str(provider_path(provider)), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=45,
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
    return payload


def _tag_messages(account: dict, payload: dict) -> list[dict]:
    label = str(account.get("label") or account["id"])
    tagged = []
    for msg in payload.get("messages") or []:
        if not isinstance(msg, dict) or not msg.get("id"):
            continue
        item = dict(msg)
        item["id"] = encode_id(account["id"], str(msg["id"]))
        item["account"] = label
        tagged.append(item)
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
    # Each provider fetches one page-worth; we merge by time so mixed
    # accounts still read as a single unread pile.
    fetch = str(min(50, max(per, 25)))

    errors = []
    merged: list[dict] = []
    unread = 0
    emails = []
    payloads: dict[str, dict] = {}

    def work(acc: dict) -> tuple[dict, dict]:
        return acc, _run_provider(acc, ["list", "--limit", fetch])

    with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as pool:
        futures = [pool.submit(work, acc) for acc in accounts]
        for fut in as_completed(futures):
            acc, payload = fut.result()
            if not payload.get("ok"):
                errors.append(str(payload.get("error") or f"{acc['id']}: failed"))
                continue
            payloads[acc["id"]] = payload
            unread += int(payload.get("unread") or 0)
            if payload.get("email"):
                emails.append(str(payload["email"]))
            merged.extend(_tag_messages(acc, payload))

    if not merged and errors and unread == 0:
        die(errors[0] if len(errors) == 1 else "all accounts failed: " + "; ".join(errors))

    merged.sort(key=lambda m: int(m.get("ts") or 0), reverse=True)
    start = page
    chunk = merged[start : start + per]
    next_page = str(start + per) if start + per < len(merged) else ""

    inboxes = []
    for acc in accounts:
        payload = payloads.get(acc["id"])
        if not payload:
            continue
        inboxes.append(
            {
                "account": str(acc.get("label") or acc["id"]),
                "unread": int(payload.get("unread") or 0),
                "searchUrl": str(payload.get("searchUrl") or ""),
            }
        )

    email = emails[0] if len(emails) == 1 else ""
    search_url = ""
    if len(accounts) == 1 and inboxes:
        search_url = str(inboxes[0].get("searchUrl") or "")

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
    emit(out)


def cmd_read(opaque: str) -> None:
    account_id, local_id = decode_id(opaque)
    accounts = {a["id"]: a for a in load_accounts()}
    acc = accounts.get(account_id)
    if not acc:
        die("unknown account")
    payload = _run_provider(acc, ["read", local_id])
    if not payload.get("ok"):
        die(str(payload.get("error") or "could not mark as read"))
    emit({"ok": True})
