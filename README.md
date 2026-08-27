# You've Got Mail

An Omarchy bar widget for **unread mail only**. One pile, across every
account you add. Click a row to open that message in the browser. Read
mail is never listed.

Gmail, Outlook, Fastmail, generic IMAP, and HEY are built in. Adding
another provider is documented in [docs/PROVIDERS.md](docs/PROVIDERS.md).
**Account setup lives in [docs/ACCOUNTS.md](docs/ACCOUNTS.md)** — start
there for Outlook.com, Gmail OAuth, or HEY.

## Requirements

- [Omarchy](https://omarchy.org/) 4.0 or later (plugin `schemaVersion` 1)
- `python3` (and `jq` for the Gmail provider)
- **Gmail:** [Google Workspace CLI][gws] — `gws auth login -s gmail`
- **HEY:** [hey-cli][hey-cli] — `hey auth login`
- **Outlook:** a Microsoft Graph app registration *you* own. Personal
  `outlook.com` mailboxes cannot use IMAP. Creating the Azure directory
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

The GitHub repository must be public for that HTTPS URL to work for
other people. Review the checkout before enabling if you did not pass
`--enable`.

## Update

```bash
omarchy plugin update bvisagie.you-got-mail
```

That fast-forwards the git checkout in
`~/.config/omarchy/plugins/bvisagie.you-got-mail/`. It does not rewrite
`~/.config/omarchy-you-got-mail/` (accounts and secrets). See
[CHANGELOG.md](CHANGELOG.md) for what changed in each release.

## Accounts

```bash
PLUGIN=~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail

$PLUGIN accounts add gmail
$PLUGIN accounts add hey
$PLUGIN accounts add outlook
$PLUGIN accounts add fastmail
$PLUGIN accounts add imap
$PLUGIN accounts
```

Run `accounts add` in a **terminal**, not from the bar. Outlook opens a
browser tab; Gmail and HEY sign in through their own CLIs.

If you never add an account, a single Gmail account is assumed. The first
*extra* account (Outlook, HEY, …) writes that implicit Gmail into
`accounts.json` so it stays on the pile.

## Using it

| | |
|---|---|
| Click the bar icon | open the panel |
| Right-click the bar icon | open each inbox that currently has unread (one tab per account) |
| Middle-click the bar icon | refresh now |
| Header external-link or `i` | same as right-click |
| Click a message | open **that** thread in the browser and take it off the pile |
| `↑` `↓` or `j` `k` | move through the list |
| `Enter`, `Space` or `o` | open the message under the cursor |
| `n` / `p` | next page, previous page |
| `Tab` / `Shift+Tab` | switch to the next or previous bar panel |
| `Esc` | close |

The bar tooltip shows the unread count, or why mail is unreachable.

The panel refreshes on the interval from widget settings (default one
minute), and again when you open it or click a row. With more than one
account the badge is the sum of unread, rows are newest-first, and each
row shows an account chip. If one account fails, the others still show
and the panel names the failure.

The unread badge is the provider's mailbox total, not just the rows on
this page. Merged paging walks a cap of 200 newest messages across
accounts.

## Configuration

Page size and refresh interval are **bar widget settings** on the
`bvisagie.you-got-mail` entry in `~/.config/omarchy/shell.json` (Omarchy's
widget settings UI writes the same keys):

| Key | Default | Range |
|---|---|---|
| `max` | 25 | 1–50 (messages per panel page) |
| `refreshIntervalSec` | 60 | 15–3600 |

Accounts, tokens, and passwords stay in
`~/.config/omarchy-you-got-mail/` — they do not belong in `shell.json`.
An optional leftover `~/.config/omarchy-you-got-mail/config` with
`max = 25` is still honoured by the CLI when you run `list` without
`--limit`; the panel always passes `--limit` from widget settings.

CLI also honours `YOU_GOT_MAIL_MAX`. See [docs/ACCOUNTS.md](docs/ACCOUNTS.md)
and [docs/PROVIDERS.md](docs/PROVIDERS.md) for `YOU_GOT_MAIL_IMAP_PASSWORD`
and provider environment.

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
