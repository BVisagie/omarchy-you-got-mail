# Writing a provider

A provider is an executable in `providers/<name>`. The panel never talks
to it directly. `bin/you-got-mail` calls it.

Supported names today: `gmail`, `outlook`, `fastmail`, `imap`, `hey`.

## Commands

```text
<provider> list [--limit N]
<provider> read <local-id>
<provider> read-all
```

Always print **one JSON object** to stdout and exit 0, even on failure:

```json
{"ok":false,"error":"human readable message"}
```

Do not print secrets. Do not write secrets to stderr.

The orchestrator rejects a successful JSON response if the provider exits
with a nonzero status. The panel checks both the CLI exit status and the
`ok` field before accepting a read action; failed reads restore the row
and unread count.

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
- `searchUrl` is the account's webmail URL, also HTTPS or empty. Accounts
  uses it for Open inbox, including when `unread` is zero.
- `unread` is the mailbox total (folder counts, JMAP `calculateTotal`,
  Gmail matching-id count, HEY envelope `unseen_count`, or extra unseen
  pages), not just `len(messages)`. Do not use Gmail
  `resultSizeEstimate` as the badge: it is a coarse bucket (often 201).
  The merged pile pages at most 200 newest messages even when `unread`
  is larger.
- `subject`, `from`, and `snippet` must be **one line**. Call
  `one_line()` in `lib/common.py` (or the Gmail `entity` filter) so
  carriage returns from Graph `bodyPreview` and HTML entities do not
  wrap the row.
- Skip trash, junk, drafts, spam. IMAP uses SPECIAL-USE attributes
  (RFC 6154, plus Gmail `\Important`) and then English folder names.
  Include skip-inbox / user folders when the provider has that concept
  (Gmail user labels, IMAP folders). HEY’s attention box is the Imbox;
  Feed, Paper Trail, and the Screener are not unread.

The orchestrator adds `account` (the label) to each message, plus top-level
`accountCount` and `inboxes`. Each inbox has `id`, `account`, `unread`,
`searchUrl`, `ok`, and `needsSignIn`, including accounts that failed.
Successful inboxes also have `checkedAt` (Unix seconds, recorded when that
provider finishes). Failed inboxes have no `checkedAt`; their `unread: 0`
is a placeholder, and the panel shows Unavailable. They also have `error`,
a display `message`, and an optional recovery `action`.
A top-level `needsSignIn` is set when any account is an auth failure.
You do not add those fields. The header's Open inbox action, `i`, and
right-clicking the bar icon open inboxes with unread mail, deduplicated by
URL. Accounts (`m`) lets the user open one successful account's inbox,
including at zero unread. Both require a valid HTTPS `searchUrl`.

## `read` success

```json
{"ok":true}
```

Mark that message read on the server so the next poll does not bring it
back (`gws` modify, Graph `isRead`, `hey seen`, IMAP `\Seen`, Fastmail
`$seen`).

## `read-all` success

```json
{"ok":true,"marked":12}
```

Mark **every** unread message that `list` would count, not just the
current page. Snapshot and deduplicate matching ids **before** changing
any message so pagination cannot skip mail. Skip trash, junk, drafts, and
spam the same way `list` does. HEY still only marks the Imbox.

If some messages were marked and a later batch fails, return that count:

```json
{"ok":false,"marked":8,"error":"could not mark as read"}
```

Do not fall back to thousands of per-message calls when a bulk API is
missing. The orchestrator times this command out after 120 seconds; stop
with a partial `marked` count rather than hanging.

## Adding the name to the CLI

1. Drop the executable in `providers/<name>` (`chmod +x`).
2. Add `"<name>"` to `PROVIDERS` in `lib/common.py`.
3. Teach `lib/accounts.py` how to prompt for `accounts add` and
   `accounts login` — or that there is no plugin secret (Gmail, HEY).
4. Document the steps, including failure modes, in `docs/ACCOUNTS.md`.
