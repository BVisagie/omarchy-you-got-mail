# Writing a provider

A provider is an executable in `providers/<name>`. The panel never talks
to it directly. `bin/you-got-mail` calls it.

Supported names today: `gmail`, `outlook`, `fastmail`, `imap`, `hey`.

## Commands

```text
<provider> list [--limit N]
<provider> read <local-id>
```

Always print **one JSON object** to stdout and exit 0, even on failure:

```json
{"ok":false,"error":"human readable message"}
```

Do not print secrets. Do not write secrets to stderr.

## Environment

| Variable | Meaning |
|---|---|
| `YOU_GOT_MAIL_ACCOUNT_ID` | Short id from `accounts.json` |
| `YOU_GOT_MAIL_ACCOUNT_JSON` | The account object as JSON (no secrets) |
| `YOU_GOT_MAIL_SECRET_FILE` | Absolute path to `secrets/<id>.json` |
| `YOU_GOT_MAIL_MAX` | Default page size |

Read the secret file yourself (`chmod 600`). The orchestrator never puts
the secret in an argument. Gmail and HEY have no plugin secret: they
shell out to `gws` / `hey`, which own the token.

The bar is not a login shell. If you wrap a CLI, search
`~/.local/share/mise/shims` and `~/.local/bin` the way `bin/you-got-mail`
and the Gmail/HEY providers already do. Set `HEY_NONINTERACTIVE=1` (or
equivalent) so a missing login fails closed instead of prompting.

## `list` success

```json
{
  "ok": true,
  "email": "you@example.com",
  "unread": 4,
  "searchUrl": "https://…",
  "messages": [
    {
      "id": "local-id-only",
      "threadId": "…",
      "subject": "Hello",
      "from": "Ada",
      "snippet": "First line",
      "ts": 1710000000,
      "labels": ["Work"],
      "url": "https://…"
    }
  ]
}
```

- `id` is **local to this account**. The orchestrator prefixes it so the
  panel can route `read` back to you.
- `ts` is unix seconds, UTC.
- `url` must be `https://…` or empty. The panel rejects anything else.
  Empty is allowed (IMAP without webmail).
- `snippet` and `subject` must be **one line**. Collapse `\r` `\n` and
  other whitespace. Graph `bodyPreview` includes carriage returns; if you
  pass them through, Qt paints a multi-line preview under the subject.
  Use `one_line()` in `lib/common.py`.
- `unread` is the true unread count, not just `len(messages)`.
- Skip trash, junk, drafts, spam. Include skip-inbox / user folders when
  the provider has that concept (Gmail user labels, IMAP folders). HEY’s
  attention box is the Imbox; Feed, Paper Trail, and the Screener are not
  unread.

The orchestrator adds `account` (the label) and `accountCount` on the
merged payload. You do not.

## `read` success

```json
{"ok":true}
```

Mark that message read on the server so the next poll does not bring it
back (`gws` modify, Graph `isRead`, `hey seen`, IMAP `\Seen`, Fastmail
`$seen`).

## Adding the name to the CLI

1. Drop the executable in `providers/<name>` (`chmod +x`).
2. Add `"<name>"` to `PROVIDERS` in `lib/common.py`.
3. Teach `lib/accounts.py` how to prompt — or that there is no secret
   (Gmail, HEY).
4. Document the steps, including failure modes, in `docs/ACCOUNTS.md`.
