#!/usr/bin/env python3
"""CLI entry for You've Got Mail."""

from __future__ import annotations

import os
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))

from accounts import USAGE as ACCOUNTS_USAGE
from accounts import main as accounts_main
from chime import main as chime_main
from common import die
from orchestrate import cmd_list, cmd_read, cmd_read_all

HELP = """\
you-got-mail list [--page OFFSET] [--limit N]
you-got-mail read <id>
you-got-mail read-all
you-got-mail chime [--file PATH] [--volume 0-100] [--cooldown SEC] [-- ID ...]
you-got-mail chime --cancel
you-got-mail accounts ...

The panel calls list, read, read-all, and chime.
Accounts are added in a terminal:

  you-got-mail accounts add
  you-got-mail accounts login [id]

--limit is the panel page size (1–50). The CLI also honours
YOU_GOT_MAIL_MAX. Providers may be asked for more rows so merged
pages stay complete.

chime plays the new-mail sound (the bundled clip unless --file is given)
once per new message ID, however many widget copies pass it, and at most
once per --cooldown seconds (default 60). Do Not Disturb silences it. With
no IDs it is a test: it plays now unless Do Not Disturb is on. --cancel
drops a sound still waiting for the cooldown or a retry; the panel runs it
when you turn the sound off.

""" + ACCOUNTS_USAGE


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("list",):
        page = ""
        rest = args[1:] if args else []
        while rest:
            if rest[0] == "--page" and len(rest) > 1:
                page = rest[1]
                rest = rest[2:]
            elif rest[0] == "--limit" and len(rest) > 1:
                os.environ["YOU_GOT_MAIL_MAX"] = rest[1]
                rest = rest[2:]
            else:
                rest = rest[1:]
        cmd_list(page)
        return
    if args[0] == "read":
        if len(args) < 2:
            die("usage: you-got-mail read <id>")
        cmd_read(args[1])
        return
    if args[0] == "read-all":
        cmd_read_all()
        return
    if args[0] == "chime":
        chime_main(args[1:])
        return
    if args[0] == "accounts":
        accounts_main(args[1:])
        return
    if args[0] in ("-h", "--help", "help"):
        sys.stdout.write(HELP)
        return
    die("unknown command; try: you-got-mail --help")


if __name__ == "__main__":
    main()
