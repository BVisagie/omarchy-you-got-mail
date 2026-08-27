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
| `YOU_GOT_MAIL_MAX` | Default page size (1–50) |
| `YOU_GOT_MAIL_FETCH` | Rows this call should return (1–200); the orchestrator sets this so merged pages stay complete |
| `YOU_GOT_MAIL_IMAP_PASSWORD` | Optional IMAP password for tests; interactive setup writes `secrets/<id>.json` instead |

Read the secret file through `load_secret_file()` (`chmod 600`, owned by
you, parent `chmod 700`, not a symlink). The orchestrator never puts the
secret in an argument. Gmail and HEY have no plugin secret: they shell
out to `gws` / `hey`, which own the token.

The bar is not a login shell. If you wrap a CLI, search
`~/.local/share/mise/shims`, `~/.local/bin`, and `~/.bun/bin` the way
`bin/you-got-mail` and the Gmail/HEY providers already do. Set
`HEY_NONINTERACTIVE=1` (or equivalent) so a missing login fails closed
instead of prompting.

Catch protocol, network, and parse errors at the provider boundary and
return one JSON object. `_bootstrap.run(main)` is the last-resort wrap.

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
- `unread` is the mailbox total (folder counts, JMAP `calculateTotal`,
  Gmail `resultSizeEstimate`, HEY envelope `unseen_count`, or extra
  unseen pages), not just `len(messages)`. If the API only offers an
  estimate, document that. The merged pile pages at most 200 newest
  messages even when `unread` is larger.
- `subject`, `from`, and `snippet` must be **one line**. Call
  `one_line()` in `lib/common.py` (or the Gmail `entity` filter) so
  carriage returns from Graph `bodyPreview` and HTML entities do not
  wrap the row.
- Skip trash, junk, drafts, spam. Include skip-inbox / user folders when
  the provider has that concept (Gmail user labels, IMAP folders). HEY’s
  attention box is the Imbox; Feed, Paper Trail, and the Screener are not
  unread.

The orchestrator adds `account` (the label), `accountCount`, and an
`inboxes` array (`account`, `unread`, `searchUrl` per account) on the
merged payload. You do not. With more than one account the panel opens
every inbox whose `unread` is greater than zero.

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
