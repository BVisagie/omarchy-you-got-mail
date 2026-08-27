# You've Got Mail

An Omarchy bar widget for **unread mail only**. One pile, across every
account you add. Click a row to open that message in the browser. Read
mail is never listed.

Gmail, Outlook, Fastmail, and generic IMAP are built in. Adding another
provider is documented in [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Requirements

- [Omarchy](https://omarchy.org/)
- `python3`, `jq`
- For Gmail: [Google Workspace CLI][gws] (`gws auth login -s gmail`)

## Install

```bash
omarchy plugin add git@github.com:BVisagie/omarchy-you-got-mail.git --enable
omarchy bar move bvisagie.you-got-mail --section right
```

## Accounts

```bash
PLUGIN=~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail

$PLUGIN accounts add gmail
$PLUGIN accounts add fastmail
$PLUGIN accounts add outlook
$PLUGIN accounts add imap
$PLUGIN accounts
```

Full setup for each provider (Azure app, Fastmail token, IMAP app
password, file layout) is in [docs/ACCOUNTS.md](docs/ACCOUNTS.md).

If you never add an account, a single Gmail account is assumed.

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

The panel refreshes every minute, and again when you open it or click a row.

## Configuration

`~/.config/omarchy-you-got-mail/config` (optional):

```ini
max = 25
```

Accounts themselves are **not** in this file. See
[docs/ACCOUNTS.md](docs/ACCOUNTS.md).

## Removing it

```bash
omarchy plugin remove bvisagie.you-got-mail
```

That does not delete `~/.config/omarchy-you-got-mail/` (accounts and
secrets) or `~/.cache/omarchy-you-got-mail/`. Remove those yourself if
the machine is changing hands. Gmail sign-out is `gws auth logout`.

## License

MIT

[gws]: https://github.com/googleworkspace/cli
