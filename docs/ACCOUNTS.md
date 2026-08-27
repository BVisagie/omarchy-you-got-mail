# Accounts

You've Got Mail shows **one unread pile** across every account you add.
The panel does not change: unread only, click to open.

```bash
PLUGIN=~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail

$PLUGIN accounts           # list
$PLUGIN accounts add       # interactive
$PLUGIN accounts add gmail
$PLUGIN accounts add hey
$PLUGIN accounts add outlook
$PLUGIN accounts add fastmail
$PLUGIN accounts add imap
$PLUGIN accounts remove <id>
```

Run these from a **terminal**, not from the bar. Put `$PLUGIN` on your
PATH if you want the short command `you-got-mail`.

- [Which provider?](#which-provider)
- [Where things live](#where-things-live)
- [Implicit Gmail](#implicit-gmail)
- [Gmail](#gmail)
- [HEY](#hey)
- [Outlook](#outlook)
- [Fastmail](#fastmail)
- [IMAP (any host)](#imap-any-host)
- [Editing the files yourself](#editing-the-files-yourself)
- [More than one account](#more-than-one-account)
- [Troubleshooting](#troubleshooting)
- [Revoking access](#revoking-access)

## Which provider?

| Mailbox | Use | Do not use |
|---|---|---|
| Gmail / Google Workspace | `gmail` (`gws`) | IMAP, unless you like app passwords |
| `outlook.com` / `live.com` / `hotmail.com` | `outlook` + Graph | IMAP — Microsoft retired password IMAP |
| Microsoft 365 work/school | `outlook` + Graph (`common`) | IMAP unless the tenant still allows it |
| Fastmail | `fastmail` (JMAP token) or `imap` | — |
| HEY | `hey` (`hey-cli`) | IMAP / a public API — HEY has neither |
| iCloud, university, anything with IMAP | `imap` + app password | — |

## Where things live

| File | What |
|---|---|
| `~/.config/omarchy-you-got-mail/accounts.json` | Account list. No secrets. |
| `~/.config/omarchy-you-got-mail/secrets/<id>.json` | Tokens and passwords, mode `600`. |
| `~/.config/omarchy-you-got-mail/config` | Optional `max = 25` (page size). |
| `~/.cache/omarchy-you-got-mail/` | Gmail message cache. Safe to delete. |

Gmail and HEY store **no** plugin secret: `gws` and `hey` own the login.
Outlook Graph, Fastmail, and IMAP write a secret file.

Never commit these files. `chmod 700 ~/.config/omarchy-you-got-mail` and
`chmod 600` the secrets.

## Implicit Gmail

If `accounts.json` is missing, a single **gmail** account is assumed so
v1 setups keep working.

The first time you add a *different* provider (Outlook, HEY, …), that
implicit Gmail row is written into `accounts.json` so it does not vanish.
If you only wanted Outlook, remove Gmail afterwards:

```bash
$PLUGIN accounts remove gmail
```

## Gmail

Uses the [Google Workspace CLI](https://github.com/googleworkspace/cli).
The plugin never sees a Google token.

```bash
gws auth login -s gmail
gws auth status
$PLUGIN accounts add gmail
```

Ask `gws` for the `gmail` scope only (`-s gmail`). A broad “recommended”
scope set often fails Google’s unverified-app limit.

**Unread** is Inbox plus labels you created (skip-inbox included). It is
not Gmail’s raw `UNREAD` dump: that also counts Trash and archived
Promotions/Updates that the web UI does not show as unread.

The bar is not a login shell. Install `gws` somewhere the plugin already
searches (`~/.local/bin` or `~/.local/share/mise/shims`).

If Google shows **Access blocked / 403 access_denied**, the OAuth client
is in testing: add your Google account as a test user on that client, or
finish Google’s verification. `gws` documents that flow; this plugin does
not ship a Google client id.

## HEY

HEY has no IMAP and no public API. The plugin talks to it through
[hey-cli](https://github.com/basecamp/hey-cli), the same engine the
official Omarchy HEY bar plugin uses. The plugin never sees a HEY token.

```bash
omarchy-mise-install github:basecamp/hey-cli hey
hey auth login
$PLUGIN accounts add hey
```

Leave **linked account id** blank unless you want one mailbox of a
multi-account HEY login. Blank means every linked account.

**Unread** is unseen mail in the **Imbox**. The Feed, Paper Trail, and
the Screener are not part of this pile. Clicking a row opens the thread
on [app.hey.com](https://app.hey.com) and marks that posting seen.

This is not a replacement for
[37signals.hey](https://github.com/basecamp/omarchy-hey-plugin). You can
run both; they share hey-cli’s login.

## Outlook

Personal `outlook.com` / `live.com` / `hotmail.com` mailboxes (including
[outlook.live.com](https://outlook.live.com/)) **cannot use IMAP with a
password or app password**. Microsoft retired that path. Use Graph.

Microsoft does not let a desktop mail app ship a shared client id. You
register a tiny public-client app in Azure. That app can live on a
**different** Microsoft account than the mailbox you read; the mailbox
signs in later.

### Graph for personal Outlook.com

A personal Outlook.com login **cannot** register an app from
[entra.microsoft.com](https://entra.microsoft.com/) until it has its own
directory. That site dumps you into the `Microsoft Services` tenant:

```text
Selected user account does not exist in tenant 'Microsoft Services'
and cannot access the application '74658136-14ec-4630-ad9b-26e160ff0fc6'
```

Do **not** try to add yourself as an external user. You do not admin that
tenant. Create your own directory first.

1. Open a **private/incognito** window (so the stuck Microsoft Services
   session is not reused).
2. Create a free Azure account with the mailbox (or any Microsoft
   account you prefer):
   [azure.microsoft.com/free](https://azure.microsoft.com/free/).
   A card is usually required as identity check. App registration is
   free. Do not create VMs, databases, or Copilot add-ons.
3. After signup, open the [Azure portal](https://portal.azure.com/) —
   **not** entra.microsoft.com.
4. Search **App registrations** → **New registration**.
5. Name it e.g. `you-got-mail`. Supported accounts: **Personal Microsoft
   accounts only** (or **any org and personal** if you also have work
   mail).
6. Authentication → Add a platform → **Mobile and desktop applications**.
   Tick `http://localhost` and
   `https://login.microsoftonline.com/common/oauth2/nativeclient`.
   Under Advanced: **Allow public client flows** = Yes.
7. API permissions → Microsoft Graph → Delegated: `User.Read`,
   `Mail.ReadWrite`, `offline_access`.
8. Copy the **Application (client) ID** from Overview. That is the only
   value the wizard needs (no client secret).
9. In a terminal:

   ```bash
   $PLUGIN accounts add outlook
   # Auth method: graph
   # Client ID:    <paste>
   # Tenant:       consumers
   ```

   A browser tab opens. Sign in as the **mailbox** (`you@outlook.com`)
   and accept mail access.

The Azure tenant is only where the app object lives. `consumers` is the
login tenant for a personal mailbox. For work/school mail use `common`
and “any org and personal” (or the org directory) on the app.

If browser sign-in fails, the wizard falls back to device-code login.
New Azure tenants often block device code; the browser flow is the one
that works.

### IMAP (not Outlook.com)

Only for leftover hosts that still accept an app password.

```text
host: outlook.office365.com
port: 993
```

`$PLUGIN accounts add outlook` and choose `imap`, or add a generic IMAP
account with that host.

## Fastmail

Uses JMAP with an API token.

1. Fastmail → Settings → Privacy & Security → Integrations → API tokens.
2. Create a token with mail read and write.
3. `$PLUGIN accounts add fastmail` and paste the token (it is not echoed).

Clicking a message opens it in Fastmail’s web app.

## IMAP (any host)

Works with Fastmail, iCloud (app password), university mail, and similar.
Not personal Outlook.com (see [Outlook](#outlook)).

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
      "id": "outlook",
      "provider": "outlook",
      "label": "Outlook",
      "email": "you@outlook.com"
    },
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

Optional HEY field: `"hey_account": "12345"` to pin one linked mailbox.

`secrets/fastmail.json`:

```json
{ "token": "…" }
```

`secrets/work.json`:

```json
{ "password": "…" }
```

`secrets/outlook.json` (Graph) — prefer the wizard, which runs the
browser login:

```json
{
  "client_id": "…",
  "tenant": "consumers",
  "refresh_token": "…"
}
```

Use `"tenant": "common"` for work/school. Do not paste a refresh token
you did not just receive from Microsoft.

## More than one account

The badge is the sum of unread. The panel is newest-first across every
account. When more than one account is configured, the account label is
shown as a chip on each row. Right-click (open webmail search) is only
wired when a single account is present — there is no combined search URL.

## Troubleshooting

| What you see | What it usually is | What to do |
|---|---|---|
| Entra: account does not exist in tenant `Microsoft Services` (app `74658136-…`) | Personal Microsoft account has no Azure directory | Private window → [azure.microsoft.com/free](https://azure.microsoft.com/free/) → then [portal.azure.com](https://portal.azure.com/). Do not use entra.microsoft.com first. |
| Azure wants a credit card | Identity check for a free directory | Normal. App registration is free. Do not provision paid resources. |
| Outlook IMAP login fails for `@outlook.com` | Password IMAP is retired | Use Graph. |
| `hey-cli not found` / `gws: command not found` | Binary not on the bar’s PATH | Install into `~/.local/bin` or mise shims; middle-click the icon to retry. |
| Google **Access blocked / access_denied** | Unverified OAuth client | Add yourself as a test user, or use `-s gmail` only. |
| Badge in the hundreds, Gmail web shows 2 | The other Gmail bar plugin, or raw `UNREAD` | Disable `jankeesvw.gmail-inbox` if it is still on the bar. This plugin counts Inbox + your labels, not Trash. |
| Added Outlook and Gmail disappeared | `accounts.json` created without Gmail | Current builds keep Gmail. If an older build already dropped it: `$PLUGIN accounts add gmail`. |
| HEY lists nothing | Looking at Feed / Paper Trail | Only Imbox unseen is unread. Confirm `hey box imbox --json`. |
| Outlook signed in but rows wrap into a wall of text | Old plugin build | Update: Graph `bodyPreview` has line breaks; current builds flatten them. |
| `accounts add` refuses to run | Needs a real terminal | Run `$PLUGIN accounts add …` in a terminal, not piped. |

Test without the panel:

```bash
$PLUGIN accounts
$PLUGIN list
```

`list` prints one JSON object. `unread` is the badge; each message has
`account`, `subject`, `from`, `snippet`, and an `https` `url`.

## Revoking access

```bash
$PLUGIN accounts remove <id>
```

That deletes the plugin secret file for that id. It does **not** sign
out the upstream CLI:

- Gmail: `gws auth logout`
- HEY: `hey auth logout`
- Outlook Graph: also remove **you-got-mail** under
  [account.live.com/consent](https://account.live.com/consent) (personal)
  or the app registration in Azure
- Fastmail / IMAP: revoke the token or app password at the provider
