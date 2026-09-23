# You've Got Mail

An Omarchy bar widget for **unread mail only**. One pile, across every
account you add. Click a row to open that message in the browser. Read
mail is never listed.

Gmail, HEY, Outlook, Fastmail and generic IMAP are built in. Adding
another provider is documented in [docs/PROVIDERS.md](docs/PROVIDERS.md).
**Account setup lives in [docs/ACCOUNTS.md](docs/ACCOUNTS.md)** — start
there for Outlook.com, Gmail OAuth, or HEY.

## Preview

Version 2.8.0 using sample mail only.
The overview is composed from the individual screenshots below.

<p align="center">
  <img src="preview.png" alt="You've Got Mail — unread mailbox, Accounts, and Shortcuts overview" width="960">
</p>

<p align="center">
  <img src="docs/screenshots/accounts.png" alt="Accounts with unread totals, check times, individual inbox links, and Add account" width="360">
  &nbsp;&nbsp;
  <img src="docs/screenshots/help.png" alt="In-panel keyboard and mouse shortcut help" width="360">
</p>

<p align="center">
  <img src="docs/screenshots/paging.png" alt="Page 2 when the pile is longer than one screen" width="360">
  &nbsp;&nbsp;
  <img src="docs/screenshots/caught-up.png" alt="Empty panel when everything is read" width="360">
</p>

## Requirements

- [Omarchy](https://omarchy.org/) 4.0 or later (plugin `schemaVersion` 1)
- `python3` (and `jq` for the Gmail provider)
- **Gmail:** [Google Workspace CLI][gws] — `gws auth setup` (or a Desktop
  OAuth client JSON), then
  `GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file gws auth login -s gmail`.
  Full steps in [docs/ACCOUNTS.md](docs/ACCOUNTS.md#gmail).
- **HEY:** [hey-cli][hey-cli] — `hey auth login`
- **Outlook:** a Microsoft Graph app registration *you* own. Personal
  `outlook.com` mailboxes need OAuth; this plugin supports it through Graph,
  not its password-based IMAP provider. Creating the Azure directory
  usually asks for a card; app registration itself is free. Details in
  [docs/ACCOUNTS.md](docs/ACCOUNTS.md#outlook).
- **Fastmail / IMAP:** an API token or app password

The bar is not a login shell. The plugin already looks in
`~/.local/share/mise/shims`, `~/.local/bin`, and `~/.bun/bin` for `gws`
and `hey`.

## Install

```bash
omarchy plugin add https://github.com/BVisagie/omarchy-you-got-mail.git --enable
omarchy bar move bvisagie.you-got-mail --section right
```

No sudo or pkexec is required. Omarchy clones the repo, validates the
manifest, and enables the widget. Review the checkout before enabling if
you did not pass `--enable`.

## Update

```bash
omarchy plugin update bvisagie.you-got-mail
```

Omarchy fetches the latest commit and prints a diff of what would
change. If that opens a pager, space pages through the diff and `q`
leaves it. After the diff, confirm the update.

To skip the diff and confirmation:

```bash
omarchy plugin update bvisagie.you-got-mail --yes
```

That fast-forwards the git checkout in
`~/.config/omarchy/plugins/bvisagie.you-got-mail/`. It does not rewrite
`~/.config/omarchy-you-got-mail/` (accounts and secrets). See
[CHANGELOG.md](CHANGELOG.md) for what changed in each release.

Version 2.9.0 uses your existing accounts and widget settings; no migration
or new sign-in is required unless a provider's login has expired. Plugin
changes reload automatically. Last-check times start fresh after a reload.

## Accounts

```bash
PLUGIN=~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail

$PLUGIN accounts add gmail
$PLUGIN accounts add hey
$PLUGIN accounts add outlook
$PLUGIN accounts add fastmail
$PLUGIN accounts add imap
$PLUGIN accounts login gmail
$PLUGIN accounts
```

Use **Accounts (`m`) → Add account** to open the existing setup wizard in
a floating terminal. You can also run `accounts add` and `accounts login`
in a **terminal**. The panel never handles credentials. Outlook opens a
browser tab; Gmail and HEY sign in through their own CLIs.
`accounts login` re-authenticates an existing id in place
when a token expires.

If you never add an account, a single Gmail account is assumed. The first
*extra* account (Outlook, HEY, …) writes that implicit Gmail into
`accounts.json` so it stays on the pile.

## Using it

| | |
|---|---|
| Click the bar icon | open or close the panel |
| Right-click the bar icon | open each inbox that currently has unread (one tab per account) |
| Middle-click the bar icon, refresh button, or `r` | refresh now |
| Accounts button or `m` | account counts, individual inbox links, Add account, setup guide |
| Help button or `?` | keyboard and mouse controls |
| Header envelope-open or `A` | mark all unread as read (click or press twice to confirm) |
| `a` | mark the message under the cursor as read, without opening it |
| Header external-link or `i` | same as right-click |
| Click a message | open **that** thread in the browser and take it off the pile |
| `↑` `↓` or `j` `k` | move through mail or account actions; scroll help |
| `Enter`, `Space` or `o` | open the selected message or account action |
| `n` / `p` | next page, previous page |
| `Tab` / `Shift+Tab` | switch to the next or previous bar panel |
| `x` or action-error × | dismiss an action error |
| `Esc` | return from Accounts/Help, cancel mark-all confirm, or close |

The bar tooltip shows the unread count, or why mail needs attention. A
`!` on the mailbox means mail needs attention, not unread mail.

The widget can also say "You've got mail!" when new mail arrives. It is
off by default; see [Sound](#sound).

**Accounts** keeps the merged unread list as your main view. It shows each
account's current count and opens just that inbox, even if it has no unread
mail. Accounts without a webmail URL cannot be opened. Failed accounts say
**Unavailable** rather than displaying a zero count.

The panel and tooltip show the **last full check**. Accounts lists each
mailbox's last successful check; a failed mailbox keeps its previous time.
Partial success never advances the full-check time. These times are held in
memory and start fresh when the plugin reloads. Press `r` or the refresh button
to check again; changing relative time labels does not fetch mail.

The panel refreshes on the interval from widget settings (default one
minute), and again when you open it or click a row. With more than one
account the badge is the sum of unread, rows are newest-first, and each
row shows an account chip. If one account fails, the others still show
and the panel names the failure, including when the healthy mailboxes
are empty. Expired OAuth tokens become **Gmail needs you to sign in
again** plus the sign-in command
(`~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail accounts login gmail`,
or `you-got-mail accounts login gmail` once you have linked it onto
PATH), not the raw `invalid_grant` dump. Click the command (or ▶) to run
it in a floating terminal, or ⧉ to copy it. This works for every
provider. When a provider's CLI is missing, **Open setup guide** opens
its section of [docs/ACCOUNTS.md](docs/ACCOUNTS.md).

If marking a message read fails, its row and count are restored and the panel
shows the error, including after reopening. Browser opening still happens
immediately. The latest action warning or error replaces the previous notice.
Dismiss it with × or `x`; a successful mark-all without warnings also clears it.

The unread badge is the provider's mailbox total, not just the rows on
this page. Merged paging walks a cap of 200 newest messages across
accounts. Mark-all as read uses the same mailbox total: it is not limited
to the current page.

## Configuration

Page size, refresh interval, and the new-mail sound are **bar widget
settings** on the `bvisagie.you-got-mail` entry in
`~/.config/omarchy/shell.json` (Omarchy's widget settings UI writes the
same keys):

| Key | Default | Range |
|---|---|---|
| `max` | 25 | 1–50 (messages per panel page) |
| `refreshIntervalSec` | 60 | 15–3600 |
| `soundEnabled` | `false` | `true` plays the [new-mail sound](#sound) |
| `soundCooldownSec` | 60 | 0–3600 (seconds before the sound can play again) |
| `soundVolume` | 100 | 0–100 |
| `soundFile` | empty | path to your own sound file (empty plays the bundled clip) |

Accounts, tokens, and passwords stay in
`~/.config/omarchy-you-got-mail/` — they do not belong in `shell.json`.
An optional leftover `~/.config/omarchy-you-got-mail/config` with
`max = 25` is still honoured by the CLI when you run `list` without
`--limit`; the panel always passes `--limit` from widget settings.

CLI also honours `YOU_GOT_MAIL_MAX`. See [docs/ACCOUNTS.md](docs/ACCOUNTS.md)
and [docs/PROVIDERS.md](docs/PROVIDERS.md) for `YOU_GOT_MAIL_IMAP_PASSWORD`
and provider environment.

## Sound

The widget can say "You've got mail!" when new unread mail arrives. It is
off by default. Set `soundEnabled` to `true` in the widget settings to turn
it on, and `soundVolume` to make it quieter.

It plays once when a refresh finds new mail, however many messages
arrived, and only once even with a bar on several monitors. It stays quiet
when the plugin starts or reloads, when you page, and when reading mail
brings older unread into view. Mail that arrived while the computer slept
or was offline gets one sound, on the next successful refresh. It plays at
most once every `soundCooldownSec` seconds, and never while Do Not Disturb
is on.

To use your own sound, set `soundFile` to a local audio file. Use a full
path or one starting with `~`, such as `~/Music/ding.oga`. Sounds longer
than 15 seconds are cut off. Leave it empty for the bundled clip, which
also stands in for a file that can't be played. Playback uses `pw-play`
(PipeWire), or `paplay` if `pw-play` is missing.

To hear it now, run:

```bash
~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail chime
```

(`you-got-mail chime` once you have linked it onto PATH.) It plays the
bundled clip; add `--file` with your `soundFile` path to test that, or
`--volume 0-100` to try a different volume. If your file can't be played,
you hear the bundled clip and the output says why under `fallback`. While
Do Not Disturb is on it prints `{"ok": true, "skipped": "dnd"}` instead. If
it prints that with Do Not Disturb off, `omarchy-shell notifications isDnd`
is failing; the sound needs Omarchy 4.0 or later.

The sound comes with the next refresh, so it can lag new mail by up to one
refresh interval. Mail you read elsewhere before then never plays it.

The bundled voice is AI-generated; see [sounds/README.md](sounds/README.md).

## Removing it

```bash
omarchy plugin remove bvisagie.you-got-mail
```

That does not delete `~/.config/omarchy-you-got-mail/` (accounts and
secrets) or `~/.cache/omarchy-you-got-mail/`. Remove those yourself if
the machine is changing hands.

| Provider | Sign out |
|---|---|
| Gmail | `gws auth logout` |
| HEY | `hey auth logout` |
| Outlook Graph | delete `secrets/outlook.json` and remove the app at [account.live.com/consent](https://account.live.com/consent) (personal) or the Azure app's permissions |

## License

MIT

[gws]: https://github.com/googleworkspace/cli
[hey-cli]: https://github.com/basecamp/hey-cli
