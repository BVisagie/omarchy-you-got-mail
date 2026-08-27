# You've Got Mail

An Omarchy bar widget for **unread mail only**. One pile, across every
account you add. Click a row to open that message in the browser. Read
mail is never listed.

Gmail, Outlook, Fastmail, generic IMAP, and HEY are built in. Adding
another provider is documented in [docs/PROVIDERS.md](docs/PROVIDERS.md).
**Account setup lives in [docs/ACCOUNTS.md](docs/ACCOUNTS.md)** — start
there for Outlook.com, Gmail OAuth, or HEY.

This is not [jankeesvw/omarchy-gmail-inbox](https://github.com/jankeesvw/omarchy-gmail-inbox)
and not [37signals.hey](https://github.com/basecamp/omarchy-hey-plugin).
Those can sit on the bar next to this widget; they do not share its pile.

## Requirements

- [Omarchy](https://omarchy.org/)
- `python3` (and `jq` for the Gmail provider)
- **Gmail:** [Google Workspace CLI][gws] — `gws auth login -s gmail`
- **HEY:** [hey-cli][hey-cli] — `hey auth login`
- **Outlook:** a Microsoft Graph app registration *you* own. Personal
  `outlook.com` mailboxes cannot use IMAP. Creating the Azure directory
  usually asks for a card; app registration itself is free. Details in
  [docs/ACCOUNTS.md](docs/ACCOUNTS.md#outlook).
- **Fastmail / IMAP:** an API token or app password

The bar is not a login shell. The plugin already looks in
`~/.local/share/mise/shims` and `~/.local/bin` for `gws` and `hey`.

## Install

```bash
omarchy plugin add git@github.com:BVisagie/omarchy-you-got-mail.git --enable
omarchy bar move bvisagie.you-got-mail --section right
```

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
| Right-click the bar icon | open that account's webmail (one account only) |
| Middle-click the bar icon | refresh now |
| Click a message | open that thread and take it off the pile |
| `↑` `↓` or `j` `k` | move through the list |
| `Enter`, `Space` or `o` | open the message under the cursor |
| `n` / `p` | next page, previous page |
| `Esc` | close |

The panel refreshes every minute, and again when you open it or click a
row. With more than one account the badge is the sum of unread, rows are
newest-first, and each row shows an account chip.

## Configuration

`~/.config/omarchy-you-got-mail/config` (optional):

```ini
max = 25
```

`max` is the page size (1–50). Accounts themselves are **not** in this
file. See [docs/ACCOUNTS.md](docs/ACCOUNTS.md).

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
