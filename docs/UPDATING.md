# Updating

```bash
omarchy plugin update bvisagie.you-got-mail
```

Omarchy fetches the latest commit and shows a diff of what would change. If
that opens a pager, space pages through it and `q` leaves it; then confirm.
Add `--yes` to skip the diff and the question.

The update fast-forwards the checkout in
`~/.config/omarchy/plugins/bvisagie.you-got-mail/`. It does not touch
`~/.config/omarchy-you-got-mail/` (accounts and secrets), and no new sign-in
is needed unless a provider's login has expired.

**Run `omarchy restart shell` afterwards.** The shell keeps the old widget
code until it restarts. Last-check times start fresh after that.

See [CHANGELOG.md](../CHANGELOG.md) for what changed in each release.

## Staying on Omarchy 4.0

Version 3.0.0 needs Omarchy 4.5, and `omarchy plugin add` and `update`
always take the newest commit. On Omarchy 4.0, pin the checkout to 2.10.0,
the last release that supports it.

Installing fresh: add the plugin without enabling it (answer **No** if it
asks to enable), pin it, then enable it.

```bash
omarchy plugin add https://github.com/BVisagie/omarchy-you-got-mail.git
git -C ~/.config/omarchy/plugins/bvisagie.you-got-mail checkout v2.10.0
omarchy plugin enable bvisagie.you-got-mail
omarchy bar move bvisagie.you-got-mail --section right
```

Already installed: pin the checkout instead of updating.

```bash
git -C ~/.config/omarchy/plugins/bvisagie.you-got-mail fetch origin tag v2.10.0
git -C ~/.config/omarchy/plugins/bvisagie.you-got-mail checkout v2.10.0
omarchy restart shell
```

`omarchy plugin update` moves the checkout to the newest version again, so
leave this plugin out of it until you are on Omarchy 4.5.
