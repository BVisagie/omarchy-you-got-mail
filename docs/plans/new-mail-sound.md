# Plan: "You've got mail" sound on new mail

Status: **planned.** The clip is in `sounds/`; nothing else is
implemented yet. This file goes away (or moves into the README/CHANGELOG)
once the feature ships.

## Goal

Play a short "You've got mail!" voice clip when genuinely new unread mail
arrives. Never on startup, reload, paging, or every refresh, and never
because the user read other mail. One chime per new mail, even with a bar on
several monitors. Silent while notifications are silenced.

## Audio

- **Bundled clip:** the maintainer's own AI-voice recording of the phrase.
  `sounds/README.md` says it is an AI voice.
- **Bring your own file:** the `soundFile` setting points at any local
  sound file instead.

### Bundled file

| | |
|---|---|
| Path | `sounds/you-got-mail.oga` (14 KB) |
| Format | Ogg Vorbis, mono, 48 kHz (`pw-play` and `paplay` decode it through libsndfile) |
| Length | 0.95 s: about 0.2 s of silence first, trailing silence trimmed |
| Loudness | −15.8 LUFS integrated, true peak −2.7 dBTP |
| Source | the maintainer's 48 kHz stereo WAV (both channels identical), kept outside the repo |

The leading silence stays on purpose: an output waking from suspend (HDMI,
Bluetooth) can cut off the first moment of a sound, and that would be the
"You've".

How it was made:

```bash
# Measure the take as it sounds on two speakers (I: −21.3 LUFS here).
ffmpeg -i take.wav -af ebur128=peak=true -f null -

# Mono, trim trailing silence, fixed gain of (−16 − measured I) dB.
ffmpeg -i take.wav -af "pan=mono|c0=0.5*c0+0.5*c1,areverse,\
silenceremove=start_periods=1:start_threshold=-50dB,areverse,volume=5.3dB" \
  -ar 48000 -c:a libvorbis -q:a 5 sounds/you-got-mail.oga

# Check: dualmono measures a mono file as it sounds on two speakers.
ffmpeg -i sounds/you-got-mail.oga -af ebur128=peak=true:dualmono=true -f null -
```

A fixed gain is used instead of `loudnorm`, whose one-pass mode changes
the gain over time. That suits long recordings, not a one-second clip.

## Behaviour

### What counts as new mail

Detection runs in `applyPayload` (`Panel.qml`) after `acceptsList` has
accepted the payload and `dismissedIds` has filtered the rows. The decision
lives in a pure function in `MailState.js` so the Node tests can exercise it.

State is kept per account, keyed by the account ID before the `:` in each
row ID, as `finishRead` does. `row.account` is a display label, and two
accounts can share one.

For each account the state holds:

- `seen`: IDs seen on page 1, keeping the most recent 200. It is not
  trimmed to what page 1 shows now, so a message that leaves page 1 and
  comes back is still known.
- `mark`: the high-water `ts`. It only rises, and never above `now + 300` s,
  so one misdated message cannot silence an account.

Plus one shared value:

- `floor`: the oldest `ts` on the previous page 1 if that page was full
  (`nextPage` set); otherwise none.

A row counts as an arrival only when **all** of these hold:

1. The payload is reachable and for page 1 (`pageToken === ""`). Paging
   never chimes and never changes the state.
2. Its account already has a baseline, meaning an earlier successful page-1
   list in this session. An account's first successful page-1 list (after
   start, reload, being added, or failing since start) only records one.
3. Its ID is not in the account's `seen`.
4. Its `ts` is at or after the account's `mark`, if it has one. This stops
   old mail that is marked unread again from counting as new.
5. Its `ts` is newer than `floor`, if there is one. An older unseen row
   came up from page 2 because the user read other mail; it is not new.
   This matters for an account whose unread mail is all older than page 1,
   which has no rows there and so no `seen` or `mark` of its own.

After deciding, update the state:

- For each account that is `ok` in this payload: add its page-1 row IDs to
  `seen` and raise `mark` to its newest row's `ts` (capped as above).
- A failed account keeps its state unchanged. It is not re-baselined when it
  recovers: its old mail is already below its `mark`, and mail that arrived
  while it was failing is genuinely new.
- Set `floor` from this page.
- Drop accounts that are no longer in `inboxes`.

The unread count is not used: reading one mail while another arrives
leaves it unchanged, and mark-read failures move it.

### When it plays

- **Once per refresh**, however many arrivals there are.
- **Once per new mail across all widget copies.** Omarchy 4 creates one
  copy of each bar widget per monitor, and each copy polls on its own. They
  all pass their arrival IDs to the `chime` command, which remembers which
  IDs it has already announced.
- **Cooldown**: at most once per `soundCooldownSec` (default 60 s), shared
  across widget copies.
- **Do Not Disturb**: skipped while notifications are silenced.
- **After sleep or a network outage**: mail that arrived meanwhile chimes
  once, when the next refresh succeeds (see open question 2).
- **Off by default.** Surprise audio from a bar widget is unwelcome; the
  README explains how to turn it on.

### Known limits

- Mail read elsewhere before the next poll never chimes (acceptable for an
  unread-only tool).
- Latency is up to one refresh interval (default 60 s), plus the provider's
  own indexing delay.
- A message the provider lists only after a newer one has been seen falls
  below the `mark` and does not chime.
- An account with no unread mail at baseline has no `mark` yet. If page 1 is
  not full, old mail marked unread there can chime.
- Each widget copy still polls the providers on its own; the duplicates are
  only removed at chime time.

## Implementation

### `MailState.js`

- `arrivals(state, inboxes, messages, pageFull, now)` returns
  `{ state, fresh }`, where `fresh` is the list of arrival IDs. It is pure
  and has no timers.

### `Panel.qml`

- New property: `arrivalState`. New read-only settings: `soundEnabled`,
  `soundCooldownSec`, `soundVolume`, `soundFile`.
- In `applyPayload`, when the payload is reachable and on page 1, call
  `MailState.arrivals` and always store the new state. If `soundEnabled`
  and `fresh` is not empty, run
  `Util.execArgv([root.script, "chime", "--cooldown", ..., "--volume", ...,
  ("--file", soundFile,) "--", ...fresh])` as fire-and-forget, the same way
  the panel already opens the browser and runs `wl-copy`. Pass only IDs
  that pass `validId`.
- Settings are read with `setting(...)` and clamped like `refreshMs`.
  `soundEnabled` accepts `true`, `"true"` and `1`, since `shell.json` is
  edited by hand.

### CLI: `you-got-mail chime [--file PATH] [--volume 0-100] [--cooldown SEC] [-- ID ...]`

New `lib/chime.py`, wired into `lib/cli.py` (including `HELP`) and the
`bin/you-got-mail` header comment.

1. Resolve the file: `--file` with a leading `~` expanded, otherwise the
   bundled `sounds/you-got-mail.oga`. It must be an existing regular file;
   anything else returns `{"ok":false,...}`.
2. Check Do Not Disturb with `omarchy-shell notifications isDnd` (prints
   `on` or `off`) and a 2 s timeout. An error or timeout counts as
   silenced.
3. If IDs are given (the panel always passes them), take an `flock` on
   `$XDG_RUNTIME_DIR/you-got-mail/chime.lock` and read `chime.json` (the
   announced IDs with their times, dropped after 24 h, and the last chime
   time). Then:
   - every ID already announced → `{"ok":true,"skipped":"announced"}`;
   - otherwise record the IDs, even if a later step skips, so another
     widget copy does not announce them later;
   - Do Not Disturb on → `{"ok":true,"skipped":"dnd"}`;
   - last chime less than `--cooldown` seconds ago →
     `{"ok":true,"skipped":"cooldown"}`;
   - otherwise record the chime time and release the lock.
4. Play with `pw-play --media-role Notification [--volume V/100] FILE`,
   falling back to `paplay --property=media.role=event
   [--volume V×65536/100] FILE`. `pw-play` defaults to the Music role, and
   the two players take different volume ranges. Uses argv lists (no shell)
   and a timeout.

Without IDs the command is a manual test: it skips the announced-ID check
and the cooldown but still honours Do Not Disturb. Running
`you-got-mail chime` in a terminal plays the sound.

### `providers/imap`

`ts` comes from the sender's `Date:` header today; the other providers use
the time their server received the mail. Fetch `INTERNALDATE` in the same
UID FETCH (`(INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])`),
parse it with `imaplib.Internaldate2tuple`, and use it for `ts`, falling
back to `Date:` if it is missing. Without this, a spam mail dated in the
future would silence the account, mail with a lagging `Date:` would not
chime, and mail with no `Date:` (`ts` 0) would never chime. It also makes
the merged sort order match delivery order.

### Settings (`manifest.json` → `barWidget.schema`)

| Key | Type | Default | Range / notes |
|---|---|---|---|
| `soundEnabled` | boolean | false | |
| `soundCooldownSec` | integer | 60 | 0–3600, step 15 |
| `soundVolume` | integer | 100 | 0–100 |
| `soundFile` | path | empty = bundled clip | a leading `~` is expanded |

Omarchy 4.0.4 passes `schema` through unchanged, and its own manifests
already use `boolean` (the Indicators widget's `alwaysShow`) and `path`.

### Docs and release

- README: Configuration table rows, one "Using it" line, and a short
  "Sound" section covering on/off, your own file,
  `you-got-mail chime` as the test, and one line saying the bundled voice
  is AI-generated.
- CHANGELOG `2.9.0` (including the IMAP timestamp change) and a
  `manifest.json` version bump (`test_changelog_matches_manifest` enforces
  that they match).

## Tests

- `tests/test_mail_state.cjs` for `arrivals`:
  - The first page-1 payload sets a baseline and returns no arrivals.
  - One new ID returns one arrival; the same payload again returns none.
  - Paging returns none and leaves the state unchanged.
  - Old mail marked unread again (`ts` below `mark`) returns none.
  - The newest message, read elsewhere and then marked unread again,
    returns none (its ID is still in `seen`).
  - Two accounts, the busy one filling page 1: reading its mail brings the
    quiet account's older rows onto page 1 and returns none (`floor`).
  - A future-dated row cannot raise `mark` past `now + 300`; a real arrival
    after it still counts.
  - An account that fails and recovers: mail that arrived meanwhile counts,
    its old rows do not.
  - An account seen for the first time (just added, or failing since start)
    only records a baseline.
  - Two accounts with the same label keep separate state.
  - A dismissed ID returns none.
  - Two accounts that each receive one message return two arrivals, which
    still means one chime.
- `tests/test_panel_behavior.cjs`, which runs the real `Panel.qml`
  functions with `Util.execArgv` stubbed (add the new properties to
  `tests/panel_harness.cjs`):
  - The panel calls `chime` with the arrival IDs, only on page 1.
  - Nothing is called while `soundEnabled` is off, but the state still
    updates.
  - A payload rejected by `acceptsList` leaves the arrival state unchanged.
- `tests/test_chime.py`:
  - A second call with the same IDs (another monitor's widget) spawns no
    player.
  - The cooldown applies across calls.
  - Do Not Disturb on, or `omarchy-shell` failing or timing out, spawns no
    player, and the IDs are still recorded.
  - A missing or non-regular file returns `ok:false`; a leading `~` is
    expanded.
  - The argv is a list with the file as its own element. `pw-play` gets
    `--media-role Notification` and a 0–1.0 volume; the `paplay` fallback
    gets `media.role=event` and a 0–65536 volume.
- `tests/test_providers.py`: IMAP `ts` comes from `INTERNALDATE`, and falls
  back to `Date:`.
- `tests/test_panel.py`: the manifest schema declares the four keys with
  the types above.
- Manual:
  - `you-got-mail chime` plays the sound.
  - Send yourself a mail and hear exactly one chime, also with bars on two
    monitors.
  - Reloading the plugin plays nothing.
  - Reading mail in the panel never chimes.
  - Toggling Do Not Disturb silences it.

## Checked against Omarchy 4.0.4

- **Do Not Disturb** belongs to the shell's notifications service, not
  mako. `omarchy-toggle-notification-silencing` calls
  `omarchy-shell notifications toggleDnd`, and `isDnd` reads it. QML cannot
  read it directly: `firstPartyServiceFor("omarchy.notifications")` returns
  `null` for ordinary bar widgets. The README requires Omarchy 4.0 or later,
  so there is no mako fallback.
- **Setting types**: `boolean` and `path` are fine (see Settings).
- **One widget copy per monitor**: the bar creates a copy of each widget for
  every screen (plus a zero-size placeholder for anchored centre modules),
  hence the de-duplication in `chime`.

## Open questions

1. **Default on or off?** The plan says off.
2. **Chime after sleep?** This design chimes once for mail that arrived
   during sleep or a network outage, when the next refresh succeeds. The
   alternative is to re-baseline after any failure, which makes the result
   depend on whether the network is back before the first refresh.
3. **A "Play test sound" entry** in the Accounts view? Proposed: no, the CLI
   command is enough for a first version.

## Out of scope

- Per-account sounds and desktop notification popups (possible later).
- Sharing one poller across monitors, so that widget copies stop polling
  the providers separately.
