# Accounts

You've Got Mail shows **one unread pile** across every account you add.
The panel does not change: unread only, click to open.

```bash
you-got-mail accounts           # list
you-got-mail accounts add       # interactive
you-got-mail accounts add gmail
you-got-mail accounts add hey
you-got-mail accounts add outlook
you-got-mail accounts add fastmail
you-got-mail accounts add imap
you-got-mail accounts remove <id>
```

Run these from a terminal, not from the bar. The plugin binary is:

```bash
~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail
```

Put it on your PATH if you want the short command, or call it with that path.

## Where things live

| File | What |
|---|---|
| `~/.config/omarchy-you-got-mail/accounts.json` | Account list. No secrets. |
| `~/.config/omarchy-you-got-mail/secrets/<id>.json` | Tokens and passwords, mode `600`. |
| `~/.cache/omarchy-you-got-mail/` | Message cache. Safe to delete. |

If `accounts.json` is missing, a single **gmail** account is assumed so v1
setups keep working.

## Gmail

Uses the [Google Workspace CLI](https://github.com/googleworkspace/cli). The
plugin never sees a Google token.

```bash
gws auth login -s gmail
you-got-mail accounts add gmail
```

Unread is Inbox plus your own labels (skip-inbox included), not Promotions
sitting in All Mail or Trash.

## HEY

HEY has no IMAP and no public API. The plugin talks to it through
[hey-cli](https://github.com/basecamp/hey-cli), the same engine the
official Omarchy HEY bar plugin uses. The plugin never sees a HEY token.

```bash
omarchy-mise-install github:basecamp/hey-cli hey
hey auth login
you-got-mail accounts add hey
```

Leave **linked account id** blank unless you want one mailbox of a
multi-account HEY login. Blank means every linked account.

Unread is **unseen mail in the Imbox**. The Feed, Paper Trail, and the
Screener are not part of this pile — they are not HEY's "needs your
attention" box. Clicking a row opens the thread on
[app.hey.com](https://app.hey.com) and marks that posting seen.

This is not a replacement for [37signals.hey](https://github.com/basecamp/omarchy-hey-plugin).
You can run both; they share hey-cli's login.

## Fastmail

Uses JMAP with an API token.

1. Fastmail → Settings → Privacy & Security → Integrations → API tokens.
2. Create a token with mail read and write.
3. `you-got-mail accounts add fastmail` and paste the token (it is not echoed).

Clicking a message opens it in Fastmail’s web app.

## Outlook

Personal `outlook.com` / `live.com` / `hotmail.com` mailboxes (including
[outlook.live.com](https://outlook.live.com/)) **cannot use IMAP with a
password or app password**. Microsoft retired that path. Use Graph.

### Microsoft Graph (recommended)

Needs an Azure app registration you own (Microsoft does not let a desktop
app ship a shared client id for mail). Personal Microsoft accounts work.

1. Open the [Entra admin center](https://entra.microsoft.com/) signed in as
   the mailbox you are adding. If it asks you to create a tenant / Azure
   subscription, the free one is enough.
2. Identity → Applications → App registrations → **New registration**.
3. Name it e.g. `you-got-mail`. Supported accounts: **Personal Microsoft
   accounts only** (or **any org and personal** if you also have work mail).
4. Authentication → Add a platform → **Mobile and desktop applications**.
   Tick `http://localhost` and
   `https://login.microsoftonline.com/common/oauth2/nativeclient`.
   Under Advanced: **Allow public client flows** = Yes.
5. API permissions → Microsoft Graph → Delegated: `User.Read`,
   `Mail.ReadWrite`, `offline_access`. No admin consent is needed for a
   personal mailbox you own.
6. Copy the **Application (client) ID** from Overview.
7. `you-got-mail accounts add outlook`, choose `graph`, paste the client id.
   Tenant: `consumers` for outlook.com, `common` for work/school.
   A browser tab opens; sign in as that mailbox and accept mail access.

The first extra account also writes the implicit Gmail account into
`accounts.json`, so Gmail stays on the pile.

### IMAP

Only for leftover hosts that still accept an app password — **not**
personal Outlook.com.

```text
host: outlook.office365.com
port: 993
```

`you-got-mail accounts add outlook` and choose `imap`, or add a generic IMAP
account with that host. Clicking a message opens Outlook on the web.

## IMAP (any host)

Works with Fastmail, Outlook, iCloud (app password), university mail, etc.

```text
host, port (993), username, password or app password
webmail URL (optional) — opened when you click a message
```

Unread is every folder except trash, junk/spam, drafts, sent, and similar.
There is no standard “open this IMAP message in the browser” URL; if you
leave webmail empty, click still marks the message read.

## Editing the files yourself

`accounts.json`:

```json
{
  "accounts": [
    { "id": "gmail", "provider": "gmail", "label": "Gmail" },
    { "id": "hey", "provider": "hey", "label": "HEY" },
    {
      "id": "fastmail",
      "provider": "fastmail",
      "label": "Fastmail",
      "email": "you@fastmail.com"
    },
    {
      "id": "work",
      "provider": "imap",
      "label": "Work",
      "host": "imap.example.com",
      "port": 993,
      "user": "you@example.com",
      "webmail": "https://webmail.example.com/"
    }
  ]
}
```

`secrets/fastmail.json`:

```json
{ "token": "…" }
```

`secrets/work.json`:

```json
{ "password": "…" }
```

`secrets/outlook.json` (Graph):

```json
{
  "client_id": "…",
  "tenant": "common",
  "refresh_token": "…"
}
```

Never commit these files. `chmod 700 ~/.config/omarchy-you-got-mail` and
`chmod 600` the secrets.

## More than one account

The badge is the sum of unread. The panel is newest-first across every
account. When more than one account is configured, the account label is
shown as a chip on each row. Right-click (open webmail search) is only
wired when a single account is present — there is no combined search URL.
