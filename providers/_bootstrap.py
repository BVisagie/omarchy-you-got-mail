"""Put lib/ on sys.path when a provider is run as an executable."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from common import die  # noqa: E402


def account() -> dict:
    raw = os.environ.get("YOU_GOT_MAIL_ACCOUNT_JSON") or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die("invalid account metadata")
    return data if isinstance(data, dict) else {}


def secret() -> dict:
    path = os.environ.get("YOU_GOT_MAIL_SECRET_FILE") or ""
    if not path:
        return {}
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        die("secret file is not valid JSON")
    return data if isinstance(data, dict) else {}


def parse_args(argv: list[str]) -> tuple[str, list[str], dict[str, str]]:
    if not argv:
        return "list", [], {}
    cmd = argv[0]
    flags: dict[str, str] = {}
    rest: list[str] = []
    i = 1
    while i < len(argv):
        if argv[i] in ("--page", "--limit") and i + 1 < len(argv):
            flags[argv[i][2:]] = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    return cmd, rest, flags
