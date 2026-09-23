# Plan: "You've got mail" sound on new mail

Status: **planned — waiting on the audio file.** Nothing here is implemented
yet. This file goes away (or moves into the README/CHANGELOG) once the
feature ships.

## Goal

Play a short "You've got mail!" voice clip when genuinely new unread mail
arrives. Never on startup, reload, paging, account recovery, or every
refresh. Silent while notifications are silenced.

## Audio

### Source and rights

- **Do not ship the original AOL recording.** AOL (owned by Bending Spoons
  since January 2026) holds the copyright in Elwood Edwards' 1989 recording.
  Redistributing it in an MIT repo invites a DMCA takedown.
- **Do not clone or imitate Edwards' voice.** Post-mortem publicity rights
  and AI voice laws (e.g. Tennessee's ELVIS Act) make that the one risky
  option.
- **Default clip: a stock AI text-to-speech voice** (OpenAI TTS) reading the
  phrase in a generic, friendly delivery. OpenAI assigns output rights to
  the user. Its usage policies require telling listeners the voice is AI,
  so `sounds/README.md` says so.
- **Bring your own file:** a setting points at any local sound file, so
  users who own the original can use it. The repo and README never host or
  link to the AOL clip.

### File the maintainer will add

| | |
|---|---|
| Path | `sounds/you-got-mail.oga` (a `.wav` is fine too) |
| Format | Ogg Vorbis, mono, 48 kHz |
| Length | ~1–2 s, leading and trailing silence trimmed |
| Loudness | normalised to about −16 LUFS, true peak ≤ −1.5 dBTP |
| Provenance | `sounds/README.md`: tool, voice name, date, and the line "AI-generated voice, not a human recording." |

Reference post-processing:

```bash
ffmpeg -i take.wav -af "\
silenceremove=start_periods=1:start_threshold=-50dB,areverse,\
silenceremove=start_periods=1:start_threshold=-50dB,areverse,\
loudnorm=I=-16:TP=-1.5:LRA=11" \
  -ac 1 -ar 48000 -c:a libvorbis -q:a 5 sounds/you-got-mail.oga
```

## Behaviour

### What counts as new mail

Detection runs in `applyPayload` (`Panel.qml`) after `dismissedIds` has
filtered the rows. The decision lives in a pure function in `MailState.js` so
the Node tests can exercise it.

A message counts as an arrival only when **all** of these hold:

1. The payload is for page 1 (`pageToken === ""`). Paging never chimes.
2. A baseline already exists. The first successful list after start or
   reload only records one and plays nothing.
3. Its account was `ok` on the previous refresh too. An account that
   recovers from a failure or sign-in gets a fresh baseline instead of
   chiming for its whole inbox.
4. Its `id` has not been seen before **and** its `ts` is at or after that
   account's high-water mark. This stops old mail that is marked unread
   again from counting as new.

The unread count is not used: reading one mail while another arrives
leaves it unchanged, and mark-read failures move it.

### When it plays

- **Once per refresh**, however many arrivals there are.
- **Cooldown**: at most once per `soundCooldownSec` (default 60 s).
- **Do Not Disturb**: skipped while notifications are silenced.
- **Off by default.** Surprise audio from a bar widget is unwelcome; the
  README explains how to turn it on.

### Known limits

- Mail read elsewhere before the next poll never chimes (acceptable for an
  unread-only tool).
- Latency is up to one refresh interval (default 60 s).
- Mail with a `Date` older than the account's high-water mark (a delayed
  delivery) does not chime.
- Arrivals beyond page 1 between two refreshes still chime only once, which
  is the intended outcome anyway.

## Implementation

### `MailState.js`

- `arrivals(state, inboxes, messages)` returns `{ state, fresh }`. `state`
  holds `baselineReady`, the per-account `seen` IDs (pruned to what page 1
  currently shows) and the per-account high-water `ts`. It is pure and has
  no timers.
- `shouldChime(lastChimeAt, now, cooldownSec, freshCount)`.

### `Panel.qml`

- New properties: `arrivalState`, `lastChimeAt`.
- In `applyPayload`, when the payload is reachable and on page 1, call
  `MailState.arrivals`. If `shouldChime` allows it, run
  `Util.execArgv([root.script, "chime", ...])` as fire-and-forget, the same
  way the panel already opens the browser and runs `wl-copy`.
- Settings are read with `setting(...)` and clamped like `refreshMs`.

### CLI: `you-got-mail chime [--file PATH] [--volume 0-100]`

New `lib/chime.py`, wired into `lib/cli.py` and the `bin/you-got-mail`
header comment.

- Uses `--file` if given, otherwise the bundled `sounds/you-got-mail.oga`.
  It must be an existing regular file; anything else returns
  `{"ok":false,...}`.
- Checks Do Not Disturb, and exits quietly with `{"ok":true,"skipped":"dnd"}`
  while notifications are silenced.
- Plays with `pw-play [--volume V] FILE`, falling back to `paplay`. Uses
  argv lists (no shell) and a timeout.
- Doubles as the user-facing test: running `you-got-mail chime` in a
  terminal plays the sound.

### Settings (`manifest.json` → `barWidget.schema`)

| Key | Type | Default | Range / notes |
|---|---|---|---|
| `soundEnabled` | boolean (or integer 0/1) | off | see open question 3 |
| `soundCooldownSec` | integer | 60 | 0–3600, step 15 |
| `soundVolume` | integer | 100 | 0–100 (optional) |
| `soundFile` | string | empty = bundled clip | may belong in `~/.config/omarchy-you-got-mail/config` instead |

### Docs and release

- README: Configuration table rows, one "Using it" line, and a short
  "Sound" section covering on/off, the bring-your-own file, and the
  AI-voice disclosure.
- CHANGELOG `2.9.0` and a `manifest.json` version bump
  (`test_changelog_matches_manifest` enforces that they match).

## Tests

- `tests/test_mail_state.cjs` for `arrivals`:
  - The first payload sets a baseline and returns no arrivals.
  - One new ID returns one arrival; the same payload again returns none.
  - Paging returns none.
  - A failed-then-recovered account returns none on recovery.
  - Old mail re-marked unread (`ts` below the high-water mark) returns none.
  - A dismissed ID returns none.
  - Two accounts that each receive one message return two arrivals, which
    still means one chime.
- `tests/test_mail_state.cjs` for `shouldChime`: the cooldown boundary and
  zero arrivals.
- `tests/test_chime.py`:
  - Do Not Disturb on means no player is spawned.
  - A missing or invalid file returns `ok:false`.
  - The argv is a list with the file as its own element.
  - Falls back to `paplay` when `pw-play` is absent.
- `tests/test_panel.py`: the panel calls `chime` via `execArgv`, and only
  on page 1.
- Manual:
  - `you-got-mail chime` plays the sound.
  - Send yourself a mail and hear exactly one chime.
  - Reloading the plugin plays nothing.
  - Toggling Do Not Disturb silences it.

## Open questions

1. **Default on or off?** The plan says off.
2. **Do Not Disturb source on Omarchy 4.** Earlier Omarchy used mako
   (`makoctl mode` containing `do-not-disturb`, toggled by
   `omarchy-toggle-notification-silencing`). This needs confirming for the
   4.x Quickshell-based shell before relying on it.
3. **Schema types.** The manifest only uses `integer` today. Confirm whether
   Omarchy's widget settings support `boolean` and `string`. If not, use a
   0/1 integer for the on/off switch and keep `soundFile` in the config file.
4. **A "Play test sound" entry** in the Accounts view, or is the CLI
   command enough?

## Out of scope

- Shipping or linking the AOL recording, or any voice clone.
- Per-account sounds and desktop notification popups (possible later).
