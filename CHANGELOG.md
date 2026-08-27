# Changelog

Versions match `manifest.json`. Git tags are created at release time.

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
