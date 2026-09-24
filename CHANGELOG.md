# Changelog

Versions match `manifest.json`. Git tags are created at release time.

## 2.9.0

An optional "You've got mail!" sound when new unread mail arrives.

- Off by default. Turn it on with the `soundEnabled` widget setting.
  `soundCooldownSec`, `soundVolume` and `soundFile` set the quiet time
  between sounds, the volume, and your own sound file. Mail that arrives
  during the quiet time gets one sound when it is up. A `soundFile` that
  can't be played falls back to the bundled clip.
- It plays once per refresh that finds new mail, and only once even with a
  bar on several monitors. Starting or reloading the plugin, paging, and
  reading other mail never play it. Do Not Disturb silences it.
- Mail that arrived during sleep or a network outage gets one sound, on
  the next successful refresh.
- `you-got-mail chime` plays the sound now, as a test. It honours Do Not
  Disturb.
- Playback uses `pw-play`, falling back to `paplay`. If the sound can't
  play, for example while PipeWire restarts, it tries again a few times
  over the next minute and a half. The bundled voice is AI-generated.
- IMAP message times now come from when the server received the mail
  (INTERNALDATE), falling back to the `Date:` header, so the merged list
  sorts in delivery order.
- Accounts, credentials and existing settings are unchanged.

## 2.8.0

Reliable read actions and small controls for the same unread-only pile.

- Accounts (`m`) shows unread totals and last successful checks per account,
  with individual Open inbox actions, Add account, and the setup guide.
  Add account opens the existing wizard in a floating terminal.
- Help (`?`) lists keyboard and mouse controls inside the panel. Escape
  returns from either view to unread mail; Tab still switches bar panels.
- `r` and the refresh button check mail. Relative check times update without
  fetching. Failed accounts retain their last successful time and say
  Unavailable; a partial success never advances the last full check.
- `list` adds stable `id` fields on every inbox and Unix-seconds `checkedAt`
  timestamps on successful inboxes. Credentials and settings are unchanged.
- Read actions also recover when the CLI cannot start. A provider process
  that exits unsuccessfully cannot report a successful action.
- Parse action JSON as well as the process result; a successful exit alone
  does not mean the provider marked the message read.
- Failed actions restore the row and count, then refresh. Other queued reads
  continue. Old in-flight refreshes cannot overwrite newer actions.
- Pending reads and action errors survive closing the panel. Dismiss errors
  with the × button or `x`; the bar tooltip also surfaces them.
- Action notices show the account once and replace older warnings or errors.
  A successful mark-all without warnings clears the notice.
- Bulk actions and page changes wait for queued reads to finish.
- Add executable panel state tests to CI.
- No notification service or notification settings are added.

## 2.7.0

Sign-in hints in the panel are buttons, not text to retype.

- A failed account shows its message and, under it, the exact sign-in
  command. Click the command or ▶ to run it in a floating Omarchy
  terminal; ⧉ copies it. It works for Gmail, Outlook, Fastmail, IMAP
  and HEY, including when every account has failed.
- "isn't installed for this bar" now comes with **Open setup guide**,
  which opens that provider's section of `docs/ACCOUNTS.md`.
- A missing Fastmail token said `run: you-got-mail accounts add fastmail`,
  which doesn't run (and would add a second account). It is now a
  sign-in failure with the working `accounts login <id>` command.
- `list` gives each failed inbox an `id`, a short `message` and, when
  there is a fix, an `action`: `signin` with the command, or `setup`
  with the guide URL. `error` and `warning` are unchanged.

## 2.6.3

The sign-in hint is a command you can actually run.

- The panel said `In a terminal: you-got-mail accounts login gmail`, but
  the plugin never installs `you-got-mail` on PATH, so pasting it gave
  `command not found`.
- The hint now names the plugin's script, e.g.
  `~/.config/omarchy/plugins/bvisagie.you-got-mail/bin/you-got-mail accounts login gmail`.
  It uses the short `you-got-mail` only when that name on PATH resolves to
  this plugin.
- The Gmail provider's own message uses the same rule and the real
  account id instead of always saying `gmail`.

## 2.6.2

Expired mail logins no longer look like an empty mailbox.

- `gws_list` (and the unread-count follow-up) ran inside `$(...)`. `die`
  exits 0, so that only ended the subshell; `list` parsed the error JSON
  as zero messages and the panel said you were caught up.
- `list` and `read-all` now assign those responses in the main shell so
  an expired `gws` token surfaces instead of unread 0.
- Copy is plain language: `{Provider} needs you to sign in again. In a
  terminal: you-got-mail accounts login {id}`. Missing `gws`/`hey` and
  unreachable hosts get their own short lines, not OAuth soup.
- Failed accounts stay in `inboxes` with `ok: false` and `needsSignIn`.
  The bar dims, shows a `!` when the pile is empty or every account failed
  (not the last good count), and the panel title becomes "Sign-in needed"
  instead of "0 unread" / "You're all caught up."

## 2.6.1

- Refresh requests that arrive while a mailbox refresh is running are
  coalesced into one follow-up refresh instead of being dropped.
- The first message is selected when mail loads, so keyboard actions work
  immediately without a mouse movement or navigation key.
- Mark-all shows a clear confirmation prompt, then keeps the old list dimmed
  and inactive until the refreshed mailbox state arrives.

## 2.6.0

Expired mail logins are a warning, not a dead widget, and the panel
tells you the terminal command to sign in again.

- `list` stays `ok` when at least one account answers, even if that
  mailbox is empty. A dead sibling is a `warning`, not a full outage.
- OAuth soup (`invalid_grant`, revoked tokens, HTTP 401) maps to
  `{id}: {provider} sign-in expired. In a terminal: …`.
- `you-got-mail accounts login [id]` re-authenticates in place.
- Gmail keeps `gws` stderr instead of discarding it; Outlook serialises
  token refresh with a lock file so two `list` calls cannot rotate the
  refresh token out from under each other.
- Panel error banner wraps; the empty state no longer repeats the dump.
- Docs: Google OAuth clients in Testing revoke refresh tokens after
  7 days. Publish the Desktop client to Production for personal use.

## 2.5.1

- README: `omarchy plugin update` shows a diff (page, then `q` to leave
  the pager) before confirming; `--yes` skips that review.
- Marketplace and widget copy name Gmail, Outlook, Fastmail, IMAP, and
  HEY.

## 2.5.0

IMAP folder discovery follows SPECIAL-USE attributes, not only English
names, and the panel can mark one row as read from the keyboard.

- IMAP skips `\All`, `\Archive`, `\Sent`, `\Trash`, `\Drafts`, `\Junk`,
  `\Flagged`, and `\Important` on the LIST flag list, then still filters
  English folder names for servers that omit SPECIAL-USE.
- IMAP sockets time out after 30s so a hung login fails in the provider
  instead of eating the orchestrator's 45s budget.
- Optional `folders` on an IMAP account is an allow-list: no LIST, no skip
  filters. Edit `accounts.json`; the add wizard is unchanged.
- Panel: `a` marks the cursor row as read without opening it. `A` and the
  header envelope keep two-press mark-all.

## 2.4.2

- Local config, account, secret, and Outlook-cache reads open the file
  once with `O_NOFOLLOW|O_NONBLOCK`, validate a user-owned regular file
  on that descriptor, and cap the read at 64KiB before decoding.

## 2.4.1

- Opening the panel no longer paints the mailbox with `activeColor`
  (theme urgent/red). The icon stays on the bar foreground like other
  widgets; the shell still marks which panel is open.

## 2.4.0

Unread mail is information, not an alarm. The bar count no longer uses
the urgent/red active colour, and the panel can mark every unread
message as read without opening each row.

- Bar badge and mailbox flag use the bar foreground instead of
  `activeColor` (theme red). The mailbox body still turns active only
  while the panel is open.
- `you-got-mail read-all` fans out to every account. Providers snapshot
  matching unread ids first, then mark them with the same skip rules as
  `list`.
- Panel: envelope action and `a` arm a two-click confirm, then parse the
  JSON result. Partial write failures stay visible after the following
  refresh.
- Bound remote HTTP bodies before decode, and write secrets/cache through
  exclusive same-directory temp files with mode 600, fsync, and atomic
  replace.

## 2.3.0

Unread totals, merged paging, widget settings, and the provider contract
are no longer papered over by a single page of rows.

- Fetch enough provider rows for the requested merged offset (capped at
  200) instead of truncating each account to one page.
- Outlook unread uses folder `unreadItemCount`; HEY uses envelope
  `unseen_count` or extra unseen pages; Gmail counts matching message
  ids (Gmail's `resultSizeEstimate` is a coarse bucket, often 201).
- Surface a partial-failure warning when some accounts succeed.
- Fastmail `read` fails unless the id is in `updated` and not in
  `notUpdated`.
- One secret loader: owner, mode 600, parent 700, no symlinks.
- Outlook access tokens are cached until near expiry; folder and profile
  metadata are reused for six hours.
- Panel page size (`max`) and refresh interval are inline widget
  settings. Keyboard: `i` opens unread inboxes, `Tab` switches panels.
  Bar tooltip and capped chips.
- HTTPS install URL, update command, and this changelog.
- Contract tests and GitHub Actions CI (mocked; no live mailboxes).
- Gmail setup documents the OAuth client `gws` now requires, and
  `GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file` so the bar can read the token.
- Bar mailbox uses Omarchy's adaptive bar colors and a stroked rural
  silhouette so it stays visible on transparent bars and mixed wallpapers.

## 2.2.4

Last release before the contract review. Unread pile across Gmail,
Outlook, Fastmail, IMAP, and HEY.
