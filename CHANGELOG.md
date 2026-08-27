# Changelog

Versions match `manifest.json`. Git tags are created at release time.

## 2.3.0

Unread totals, merged paging, widget settings, and the provider contract
are no longer papered over by a single page of rows.

- Fetch enough provider rows for the requested merged offset (capped at
  200) instead of truncating each account to one page.
- Outlook unread uses folder `unreadItemCount`; HEY uses envelope
  `unseen_count` or extra unseen pages; Gmail uses `resultSizeEstimate`.
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

## 2.2.4

Last release before the contract review. Unread pile across Gmail,
Outlook, Fastmail, IMAP, and HEY.
