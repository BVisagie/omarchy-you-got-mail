# You've Got Mail

An Omarchy bar widget for **unread mail only**. The sealed envelope sits in
the bar with a count; the panel is the pile you have not opened yet — Inbox
and skip-inbox labels together. Click a row to open that message in the
browser. Read mail is never listed.

v1 talks to Gmail through the [Google Workspace CLI][gws]. Other providers
are a later iteration; the widget only knows `list` and `read`.

## Requirements

- [Omarchy](https://omarchy.org/)
- `jq`
- `gws` installed and authenticated with the `gmail.modify` scope (opening a
  message drops the unread flag so the badge stays honest):

  ```bash
  gws auth login -s gmail
  gws auth status   # "token_valid": true
  ```

`gws` owns the OAuth token. Nothing in this plugin sees a credential.

## Install

```bash
omarchy plugin add https://github.com/BVisagie/omarchy-you-got-mail
omarchy plugin enable bvisagie.you-got-mail
omarchy bar move bvisagie.you-got-mail --section right
```

Private clones work the same with SSH:

```bash
omarchy plugin add git@github.com:BVisagie/omarchy-you-got-mail.git --enable
```

## Using it

| | |
|---|---|
| Click the bar icon | open the panel |
| Right-click the bar icon | open Gmail's unread search in the browser |
| Middle-click the bar icon | refresh now |
| Click a message | open that thread and take it off the pile |
| `↑` `↓` or `j` `k` | move through the list |
| `Enter`, `Space` or `o` | open the message under the cursor |
| `n` / `p` | next page, previous page |
| `Esc` | close |

The panel refreshes every minute, and again when you open it or click a row.

The search is:

```text
is:unread -in:spam -in:trash -in:drafts -in:chats (in:inbox OR has:userlabels)
```

That is unread in Inbox, plus unread on labels you created (skip-inbox
included). It does **not** use Gmail's raw `UNREAD` count, which also
covers trash and archived Promotions/Updates mail that the web UI does
not show next to Inbox or your labels.

User-label chips on each row say which pile caught it. New skip-inbox
labels show up on their own the first time unread mail lands on them.

Clicking a message opens `#all/<threadId>` so skip-inbox mail resolves, and
removes the Gmail `UNREAD` label.

## Configuration

`~/.config/omarchy-you-got-mail/config`:

```ini
# v1 only has gmail. Later iterations add other providers here.
provider = gmail

# Messages per page, 1 to 50.
max = 25
```

Every key is optional. Changes land on the next refresh.

## Removing it

```bash
omarchy plugin remove bvisagie.you-got-mail
```

Cache (subject, sender, snippet, label names) lives in
`~/.cache/omarchy-you-got-mail/`. Delete it if the machine is changing hands.
Signing `gws` out is separate: `gws auth logout`.

## License

MIT

[gws]: https://github.com/googleworkspace/cli
