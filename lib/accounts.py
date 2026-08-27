"""Add, list, and remove mail accounts. Secrets never go in accounts.json."""

from __future__ import annotations

import getpass
import re
import sys

from common import (
    ACCOUNT_ID_RE,
    ACCOUNTS_FILE,
    PROVIDERS,
    load_accounts,
    save_accounts,
    save_secret,
    secret_path,
)


def fail(message: str) -> None:
    sys.stderr.write(message + "\n")
    raise SystemExit(1)

USAGE = """\
you-got-mail accounts
you-got-mail accounts list
you-got-mail accounts add [gmail|outlook|fastmail|imap|hey]
you-got-mail accounts remove <id>

Accounts live in ~/.config/omarchy-you-got-mail/accounts.json.
Secrets (tokens, passwords) live in ~/.config/omarchy-you-got-mail/secrets/<id>.json
(mode 600) and are never written next to the account list.

See docs/ACCOUNTS.md for the full setup for each provider.
"""


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    sys.stderr.write(f"{prompt}{suffix}: ")
    sys.stderr.flush()
    line = sys.stdin.readline()
    if line == "":
        raise SystemExit(1)
    value = line.strip()
    return value or default


def _ask_secret(prompt: str) -> str:
    if not _tty():
        fail("refusing to read a password from a non-terminal; see docs/ACCOUNTS.md")
    return getpass.getpass(f"{prompt}: ")


def _unique_id(accounts: list[dict], suggested: str) -> str:
    base = suggested
    n = 2
    ids = {a["id"] for a in accounts}
    while suggested in ids:
        suggested = f"{base}{n}"
        n += 1
    return suggested


def cmd_list() -> None:
    accounts = load_accounts()
    if not accounts:
        sys.stdout.write("No accounts. Add one with: you-got-mail accounts add\n")
        return
    for acc in accounts:
        secret = "yes" if secret_path(acc["id"]).is_file() else "no"
        extra = ""
        if acc.get("email"):
            extra = f"  {acc['email']}"
        elif acc.get("user"):
            extra = f"  {acc['user']}"
        sys.stdout.write(
            f"{acc['id']:16}  {acc['provider']:10}  secret={secret}  {acc.get('label') or ''}{extra}\n"
        )


def _add_gmail(accounts: list[dict], acc_id: str, label: str) -> dict:
    sys.stderr.write(
        "Gmail uses the Google Workspace CLI. Authenticate once with:\n"
        "  gws auth login -s gmail\n"
        "  gws auth status\n"
    )
    return {"id": acc_id, "provider": "gmail", "label": label}


def _add_hey(accounts: list[dict], acc_id: str, label: str) -> dict:
    sys.stderr.write(
        "HEY uses hey-cli (https://github.com/basecamp/hey-cli). Install and\n"
        "sign in once; the plugin never sees a HEY token:\n"
        "  omarchy-mise-install github:basecamp/hey-cli hey\n"
        "  hey auth login\n"
        "Unread is unseen mail in the Imbox. Feed, Paper Trail, and the\n"
        "Screener are not part of this pile.\n"
    )
    email = _ask("HEY email (optional, shown in the panel)", "")
    hey_acc = _ask("Linked account id (blank = all linked accounts)", "")
    acc = {"id": acc_id, "provider": "hey", "label": label}
    if email:
        acc["email"] = email
    if hey_acc:
        acc["hey_account"] = hey_acc
    return acc


def _add_fastmail(accounts: list[dict], acc_id: str, label: str) -> dict:
    email = _ask("Fastmail email address")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        fail("that does not look like an email address")
    sys.stderr.write(
        "Create an API token at Fastmail → Settings → Privacy & Security →\n"
        "Integrations → API tokens. Scope: mail read/write.\n"
    )
    token = _ask_secret("API token")
    if not token:
        fail("API token is required")
    save_secret(acc_id, {"token": token})
    return {"id": acc_id, "provider": "fastmail", "label": label, "email": email}


def _add_imap(accounts: list[dict], acc_id: str, label: str) -> dict:
    host = _ask("IMAP host")
    port_s = _ask("IMAP port", "993")
    try:
        port = int(port_s)
    except ValueError:
        fail("port must be a number")
    user = _ask("Username (usually your email)")
    webmail = _ask("Webmail URL (optional, used when you click a message)", "")
    password = _ask_secret("Password or app password")
    if not host or not user or not password:
        fail("host, username and password are required")
    save_secret(acc_id, {"password": password})
    acc = {
        "id": acc_id,
        "provider": "imap",
        "label": label,
        "host": host,
        "port": port,
        "user": user,
    }
    if webmail:
        acc["webmail"] = webmail
    return acc


def _add_outlook(accounts: list[dict], acc_id: str, label: str) -> dict:
    sys.stderr.write(
        "Outlook can use Microsoft Graph (recommended) or IMAP.\n"
        "Graph needs an Azure app registration: see docs/ACCOUNTS.md.\n"
        "IMAP uses outlook.office365.com and an app password.\n"
    )
    kind = _ask("Auth method: graph or imap", "graph").lower()
    if kind == "imap":
        user = _ask("Email address")
        password = _ask_secret("App password")
        if not user or not password:
            fail("email and app password are required")
        save_secret(acc_id, {"password": password})
        return {
            "id": acc_id,
            "provider": "imap",
            "label": label,
            "host": "outlook.office365.com",
            "port": 993,
            "user": user,
            "webmail": "https://outlook.office.com/mail/",
        }
    client_id = _ask("Azure application (client) ID")
    tenant = _ask("Tenant", "common")
    if not client_id:
        fail("client id is required")
    from outlook_auth import device_login

    try:
        tokens = device_login(client_id, tenant)
    except RuntimeError as exc:
        fail(str(exc))
    save_secret(
        acc_id,
        {
            "client_id": client_id,
            "tenant": tenant,
            "refresh_token": tokens["refresh_token"],
        },
    )
    return {"id": acc_id, "provider": "outlook", "label": label}


def cmd_add(provider: str | None) -> None:
    if not _tty():
        fail("accounts add needs a terminal; or edit accounts.json as in docs/ACCOUNTS.md")
    accounts = load_accounts() if ACCOUNTS_FILE.is_file() else []
    if provider is None:
        provider = _ask("Provider (gmail, outlook, fastmail, imap, hey)").lower().strip()
    if provider not in PROVIDERS:
        fail(f"unknown provider '{provider}'. Choose: {', '.join(PROVIDERS)}")
    acc_id = _ask("Short id (letters, numbers, hyphen)", provider)
    if not ACCOUNT_ID_RE.match(acc_id):
        fail("id must start with a letter or number and use only A-Za-z0-9_-")
    acc_id = _unique_id(accounts, acc_id)
    label = _ask("Label in the panel", acc_id)
    if provider == "gmail":
        acc = _add_gmail(accounts, acc_id, label)
    elif provider == "hey":
        acc = _add_hey(accounts, acc_id, label)
    elif provider == "fastmail":
        acc = _add_fastmail(accounts, acc_id, label)
    elif provider == "imap":
        acc = _add_imap(accounts, acc_id, label)
    elif provider == "outlook":
        acc = _add_outlook(accounts, acc_id, label)
    else:
        fail(f"unknown provider '{provider}'")
    accounts.append(acc)
    save_accounts(accounts)
    sys.stdout.write(f"Added {acc_id} ({provider}). The panel picks it up on the next refresh.\n")


def cmd_remove(acc_id: str) -> None:
    accounts = load_accounts()
    kept = [a for a in accounts if a["id"] != acc_id]
    if len(kept) == len(accounts):
        fail(f"no account named '{acc_id}'")
    save_accounts(kept)
    path = secret_path(acc_id)
    if path.is_file() and not path.is_symlink():
        path.unlink()
    sys.stdout.write(f"Removed {acc_id}.\n")


def main(argv: list[str]) -> None:
    # argv is everything after `accounts`
    if not argv or argv[0] in ("list", "--list"):
        cmd_list()
        return
    if argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return
    if argv[0] == "add":
        cmd_add(argv[1] if len(argv) > 1 else None)
        return
    if argv[0] in ("remove", "rm", "delete"):
        if len(argv) < 2:
            fail("usage: you-got-mail accounts remove <id>")
        cmd_remove(argv[1])
        return
    fail("unknown accounts command; try: you-got-mail accounts --help")
