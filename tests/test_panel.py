from __future__ import annotations

import json
import math
import re
import unittest

from support import ROOT


class PanelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qml = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        cls.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_passes_limit_from_widget_settings(self) -> None:
        self.assertIn('setting("max", 25)', self.qml)
        self.assertIn('setting("refreshIntervalSec", 60)', self.qml)
        self.assertIn('"--limit"', self.qml)

    def _property(self, name: str) -> str:
        # A readonly property's binding: a `{ ... }` block or the rest of its line.
        pattern = rf"^  readonly property \w+ {name}: (\{{.*?^  \}}|.*?$)"
        found = re.search(pattern, self.qml, re.M | re.S)
        self.assertIsNotNone(found, name)
        return found.group(1)

    def test_reads_and_clamps_sound_settings(self) -> None:
        enabled = self._property("soundEnabled")
        self.assertIn('setting("soundEnabled", false)', enabled)
        self.assertIn('value === true || value === "true" || value === 1', enabled)
        cooldown = self._property("soundCooldownSec")
        self.assertIn('parseInt(setting("soundCooldownSec", 60), 10)', cooldown)
        self.assertIn("if (!(n >= 0)) n = 60", cooldown)
        self.assertIn("Math.max(0, Math.min(3600, n))", cooldown)
        volume = self._property("soundVolume")
        self.assertIn('parseInt(setting("soundVolume", 100), 10)', volume)
        self.assertIn("if (!(n >= 0)) n = 100", volume)
        self.assertIn("Math.max(0, Math.min(100, n))", volume)
        self.assertIn('String(setting("soundFile", "") || "").trim()', self._property("soundFile"))

    def _function(self, name: str) -> str:
        # The same shape tests/panel_harness.cjs extracts.
        found = re.search(rf"^  function {name}\([^\n]*\) \{{.*?^  \}}", self.qml, re.M | re.S)
        self.assertIsNotNone(found, name)
        return found.group(0)

    def test_header_sound_button_sits_before_accounts_in_every_view(self) -> None:
        self.assertIn('readonly property string iconSoundOn: "\\uF028"', self.qml)
        self.assertIn('readonly property string iconSoundOff: "\\uF026"', self.qml)
        row = self.qml.split("id: headerActions")[1].split("id: freshnessRow")[0]
        buttons = row.split("PanelActionButton {")[1:]
        sound = [i for i, b in enumerate(buttons) if "onClicked: root.toggleSound()" in b]
        accounts = [i for i, b in enumerate(buttons) if 'root.showView("accounts")' in b]
        self.assertEqual(len(sound), 1)
        self.assertEqual(sound[0] + 1, accounts[0], "sound button sits right before Accounts")
        button = buttons[sound[0]]
        self.assertNotIn("visible:", button)  # Shown in the mail, Accounts and Help views.
        self.assertIn("iconText: root.soundEnabled ? root.iconSoundOn : root.iconSoundOff", button)
        self.assertRegex(button, r'tooltipText: root\.soundEnabled\s+'
                                 r'\? "Turn off the new-mail sound \(s\)"\s+'
                                 r': "Turn on the new-mail sound \(s\)"')
        self.assertIn("foreground: root.soundEnabled ? root.accent : root.foreground", button)
        self.assertIn("hoverColor: root.accent", button)

    def test_s_toggles_sound_in_every_view(self) -> None:
        keys = self._function("handleTextKey")
        self.assertIn('if (t === "s") { toggleSound(); return }', keys)
        self.assertLess(keys.index('t === "s"'), keys.index('if (auxiliaryView !== "")'))

    def test_toggle_sound_persists_and_previews_through_the_manual_test(self) -> None:
        toggle = self._function("toggleSound")
        self.assertIn("var next = !root.soundEnabled", toggle)
        self.assertIn("persistSettings({ soundEnabled: next })", toggle)
        self.assertIn('[root.script, "chime", "--volume", String(root.soundVolume)]', toggle)
        self.assertIn('if (root.soundFile !== "") argv.push("--file", root.soundFile)', toggle)
        # No `--` and no IDs: the manual test ignores the cooldown and dedupe.
        self.assertNotIn('"--"', toggle)
        self.assertNotIn("--cooldown", toggle)
        # Turning it off drops a chime still waiting for the cooldown or a retry.
        self.assertIn('Util.execArgv([root.script, "chime", "--cancel"])', toggle)

    def test_toggle_sound_ignores_a_repeat_within_300_ms(self) -> None:
        self.assertIn("property double lastSoundToggle: 0", self.qml)
        toggle = self._function("toggleSound")
        self.assertIn("Date.now()", toggle)
        self.assertIn("< 300", toggle)

    def test_settings_write_is_guarded_and_keeps_existing_keys(self) -> None:
        persist = self._function("persistSettings")
        self.assertIn("var entry = { id: root.moduleName }", persist)
        self.assertIn('if (existing !== "id") entry[existing] = root.settings[existing]', persist)
        self.assertIn("root.settings = entry", persist)
        self.assertEqual(self.qml.count("updateEntryInline("), 1)
        self.assertIn(
            'if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")\n'
            "      root.bar.shell.updateEntryInline(root.moduleName, entry)",
            persist,
        )

    def test_manifest_declares_sound_settings(self) -> None:
        widget = self.manifest["barWidget"]
        schema = {item["key"]: item for item in widget["schema"]}
        self.assertEqual(schema["soundEnabled"]["type"], "boolean")
        self.assertEqual(schema["soundCooldownSec"]["type"], "integer")
        self.assertEqual(schema["soundVolume"]["type"], "integer")
        self.assertEqual(schema["soundFile"]["type"], "path")
        cooldown = schema["soundCooldownSec"]
        self.assertEqual((cooldown["min"], cooldown["max"], cooldown["step"]), (0, 3600, 15))
        volume = schema["soundVolume"]
        self.assertEqual((volume["min"], volume["max"], volume["step"]), (0, 100, 1))
        expected = {"soundEnabled": False, "soundCooldownSec": 60, "soundVolume": 100,
                    "soundFile": ""}
        for key, value in expected.items():
            self.assertIs(type(widget["defaults"][key]), type(value), key)
            self.assertEqual(widget["defaults"][key], value, key)
            self.assertIs(type(schema[key]["defaultValue"]), type(value), key)
            self.assertEqual(schema[key]["defaultValue"], value, key)

    def test_surfaces_partial_warning(self) -> None:
        self.assertIn("property string warningText", self.qml)
        self.assertIn("data.warning", self.qml)
        self.assertIn("id: failureList", self.qml)
        self.assertIn("model: root.failures", self.qml)
        self.assertIn("FailureNotice {", self.qml)

    def test_failures_survive_total_failure(self) -> None:
        # The every-account-failed payload has ok=false; its actions still show.
        apply = self.qml.split("function applyPayload(text)")[1]
        self.assertLess(apply.index("failures = failed"), apply.index("if (!reachable) return"))
        self.assertIn("reported[f].ok === false", apply)

    def test_sign_in_runs_in_terminal_with_a_validated_id(self) -> None:
        run = self.qml.split("function runSignIn(id)")[1].split("function copyCommand")[0]
        self.assertIn("if (!validAccountId(id)) return", run)
        self.assertIn('"omarchy-launch-floating-terminal-with-presentation"', run)
        self.assertIn('Util.shellQuote(root.script) + " accounts login " + id', run)
        self.assertIn("/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/", self.qml)

    def test_copy_uses_wl_copy_argv(self) -> None:
        self.assertIn('Util.execArgv(["wl-copy", "--", value])', self.qml)

    def test_setup_guide_opens_through_https_check(self) -> None:
        self.assertIn("if (root.openBrowser(url)) root.close()", self.qml)

    def test_failure_notice_is_plain_text_with_run_and_copy(self) -> None:
        notice = (ROOT / "FailureNotice.qml").read_text(encoding="utf-8")
        texts = notice.count("\n  Text {") + notice.count("\n      Text {")
        self.assertEqual(notice.count("textFormat: Text.PlainText"), texts)
        self.assertIn('action.kind === "signin"', notice)
        self.assertIn('action.kind === "setup"', notice)
        self.assertIn("Sign in in a terminal", notice)
        self.assertIn("Copy command", notice)
        self.assertIn("Open setup guide", notice)
        self.assertIn("wrapMode: Text.WrapAnywhere", notice)

    def test_error_banner_wraps_and_empty_state_does_not_repeat(self) -> None:
        self.assertIn("id: staleWarning", self.qml)
        self.assertIn("wrapMode: Text.WordWrap", self.qml)
        self.assertIn(
            '"Fix sign-in from a terminal, then middle-click the icon."',
            self.qml,
        )
        empty = self.qml.split("You're all caught up.")[1].split("textFormat:")[0]
        self.assertNotIn("root.errorText", empty)
        self.assertIn("root.warningText === \"\" || !root.reachable", self.qml)

    def test_empty_partial_failure_uses_warning_not_caught_up(self) -> None:
        self.assertIn("function barTooltip()", self.qml)
        self.assertIn("Sign-in needed", self.qml)
        self.assertIn('text: root.showAlertBadge ? "!" : root.badgeCount', self.qml)
        self.assertIn("property bool needsSignIn", self.qml)
        self.assertIn("readonly property bool hasAlert", self.qml)
        self.assertIn("opacity: root.hasAlert ? 0.5 : 1", self.qml)
        self.assertIn("font.pixelSize: Style.font.body", self.qml)

    def test_total_failure_alert_ignores_stale_unread(self) -> None:
        # applyPayload returns before touching unread when ok is false.
        self.assertIn(
            "showAlertBadge: hasAlert && (unread === 0 || !reachable)", self.qml
        )
        self.assertIn(
            'if (root.needsSignIn && (root.unread === 0 || !root.reachable)) return "Sign-in needed"',
            self.qml,
        )

    def test_keyboard_and_tooltip(self) -> None:
        self.assertIn("onTabRequested", self.qml)
        self.assertIn('t === "i"', self.qml)
        self.assertIn("tooltipText:", self.qml)
        self.assertIn("Open unread in browser (i)", self.qml)

    def test_chips_are_capped(self) -> None:
        self.assertIn("elide: Text.ElideRight", self.qml)
        self.assertIn("Style.space(64)", self.qml)
        self.assertIn("Math.max(Style.space(40)", self.qml)

    def test_readme_uses_https_install(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/BVisagie/omarchy-you-got-mail.git", readme)
        self.assertIn("omarchy plugin update bvisagie.you-got-mail", readme)
        self.assertIn("omarchy plugin update bvisagie.you-got-mail --yes", readme)
        self.assertIn("`q`", readme)
        self.assertIn("~/.bun/bin", readme)
        self.assertIn("YOU_GOT_MAIL_IMAP_PASSWORD", readme)
        self.assertIn("gws auth setup", readme)
        self.assertIn("accounts login", readme)
        self.assertIn("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file", readme)
        self.assertIn("No sudo or pkexec is required", readme)
        self.assertNotIn("must be public", readme)
        self.assertTrue((ROOT / "preview.png").is_file(), "marketplace listing wants root preview.png")
        self.assertIn("preview.png", readme)

    def test_changelog_matches_manifest(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {self.manifest['version']}", changelog)

    def test_bar_icon_uses_adaptive_colors(self) -> None:
        self.assertNotIn("active: root.opened", self.qml)
        self.assertIn("color: button.foreground", self.qml)
        self.assertIn("flagColor: button.foreground", self.qml)
        self.assertIn("hasMail: root.hasUnread && root.reachable", self.qml)
        self.assertIn("Qt.rgba(button.foreground.r, button.foreground.g,", self.qml)
        self.assertNotIn("button.activeColor", self.qml)
        self.assertNotIn("color: Color.background", self.qml)
        self.assertNotIn(
            "flagColor: (root.hasUnread && root.reachable) ? button.activeColor : button.foreground",
            self.qml,
        )
        self.assertNotIn("color: root.opened ? root.accent : root.foreground", self.qml)
        self.assertNotIn(
            "flagColor: (root.hasUnread && root.reachable) ? root.accent : root.foreground",
            self.qml,
        )

    def test_mark_all_confirm_and_busy(self) -> None:
        self.assertIn("Mark all unread as read (A)", self.qml)
        self.assertIn("Click again to confirm", self.qml)
        self.assertIn("Press A again to mark ", self.qml)
        self.assertIn("Marking unread mail as read…", self.qml)
        self.assertIn("Refreshing unread mail…", self.qml)
        self.assertIn('t === "a"', self.qml)
        self.assertIn('t === "A"', self.qml)
        self.assertIn("function markCursorRead()", self.qml)
        self.assertIn("function enqueueRead(", self.qml)
        self.assertIn("function pumpRead()", self.qml)
        self.assertIn("property var dismissedIds", self.qml)
        self.assertIn("property var readQueue", self.qml)
        self.assertIn("property bool markAllArmed", self.qml)
        self.assertIn("property bool markAllBusy", self.qml)
        self.assertIn("property bool reconciling", self.qml)
        self.assertIn("!root.reachable || listProc.running", self.qml)
        self.assertIn("property string actionWarning", self.qml)
        self.assertIn('readAllProc.command = [root.script, "read-all"]', self.qml)
        self.assertIn("applyReadAllPayload", self.qml)
        self.assertIn("root.actionWarning", self.qml)
        self.assertIn("opacity: (root.markAllBusy || root.reconciling) ? 0.4 : 1", self.qml)
        self.assertIn("enabled: !root.markAllBusy && !root.reconciling", self.qml)
        self.assertNotIn("unread = 0", self.qml)
        self.assertNotIn("messages = []", self.qml)
        self.assertRegex(self.qml, r't === "a"\)\s+root\.markCursorRead\(\)')
        self.assertRegex(self.qml, r't === "A"\)\s+root\.requestMarkAll\(\)')
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Header envelope-open or `A`", readme)
        self.assertIn("mark the message under the cursor as read, without opening it", readme)

    def test_refresh_requests_are_coalesced(self) -> None:
        self.assertIn("property bool refreshPending", self.qml)
        self.assertIn("if (listProc.running) {", self.qml)
        self.assertIn("root.refreshPending = true", self.qml)
        self.assertIn("root.refreshPending = false", self.qml)
        self.assertIn("onExited: if (root.refreshPending) root.refresh()", self.qml)

    def test_first_message_is_keyboard_ready(self) -> None:
        self.assertIn("if (cursor < 0 && messages.length > 0) cursor = 0", self.qml)

    def test_reconciliation_waits_for_latest_refresh(self) -> None:
        self.assertIn("if (!root.refreshPending) root.reconciling = false", self.qml)
        self.assertGreaterEqual(self.qml.count("root.reconciling = true"), 2)
        self.assertIn("root.markAllBusy || root.reconciling", self.qml)

    def test_mailbox_is_stroked_and_contained(self) -> None:
        icon = (ROOT / "MailSlotIcon.qml").read_text(encoding="utf-8")
        self.assertIn("ctx.arc(", icon)
        self.assertIn("ctx.lineWidth", icon)
        self.assertIn("flagAmount", icon)
        self.assertIn("up / 1.42", icon)
        self.assertNotIn("layer.enabled", icon)

    def test_flag_poses_stay_inside_canvas(self) -> None:
        for size in (12, 16, 20, 24, 32):
            for dpr in (1.0, 1.5, 2.0):
                geom = mailbox_geometry(size, dpr)
                self.assertGreater(geom["flagLen"], 0, msg=f"size={size} dpr={dpr}")
                self.assertLessEqual(geom["postY"] + geom["postH"], size + 0.51)
                for amount in (0.0, 0.25, 0.5, 0.75, 1.0):
                    for x, y in flag_corners(geom, amount):
                        self.assertGreaterEqual(x, -0.51, msg=f"size={size} t={amount}")
                        self.assertGreaterEqual(y, -0.51, msg=f"size={size} t={amount}")
                        self.assertLessEqual(x, size + 0.51, msg=f"size={size} t={amount}")
                        self.assertLessEqual(y, size + 0.51, msg=f"size={size} t={amount}")


def _snap(value: float, dpr: float) -> float:
    return round(value * dpr) / dpr


def _snap_stroke(value: float, dpr: float) -> float:
    return max(1, round(value * dpr)) / dpr


def mailbox_geometry(icon_size: float, dpr: float = 1.0) -> dict[str, float]:
    stroke = _snap_stroke(max(1.5, icon_size * 0.12), dpr)
    pad = _snap(max(stroke / 2, 0.5), dpr)
    min_flag = stroke * 1.8
    body_w = _snap(min(icon_size * 0.66, icon_size - pad * 2 - min_flag), dpr)
    arch_r = _snap(body_w / 2, dpr)
    post_h = _snap(max(stroke * 1.2, icon_size * 0.14), dpr)
    max_h = icon_size - pad * 2 - post_h - arch_r
    body_rect_h = _snap(max(stroke * 2, min(icon_size * 0.26, max_h)), dpr)
    body_h = _snap(arch_r + body_rect_h, dpr)
    body_x = _snap(pad, dpr)
    body_y = _snap(max(pad, icon_size - pad - post_h - body_h), dpr)
    pivot_x = _snap(body_x + body_w - stroke * 0.2, dpr)
    pivot_y = _snap(body_y + arch_r * 0.42, dpr)
    up = max(0.0, pivot_y - pad)
    right = max(0.0, icon_size - pad - pivot_x)
    left = max(0.0, pivot_x - pad)
    flag_len = _snap(max(0.0, min(icon_size * 0.30, up / 1.42, right, left)), dpr)
    stem_thick = _snap(min(flag_len, max(1.6, min(icon_size * 0.14, flag_len * 0.46))), dpr)
    cloth_thick = _snap(min(flag_len, max(2.0, min(icon_size * 0.18, flag_len * 0.58))), dpr)
    return {
        "size": icon_size,
        "postY": body_y + body_h,
        "postH": post_h,
        "pivotX": pivot_x,
        "pivotY": pivot_y,
        "flagLen": flag_len,
        "stemThick": stem_thick,
        "clothThick": cloth_thick,
    }


def flag_corners(geom: dict[str, float], amount: float) -> list[tuple[float, float]]:
    pivot_x = geom["pivotX"]
    pivot_y = geom["pivotY"]
    stem = geom["flagLen"]
    cloth = geom["flagLen"]
    stem_thick = geom["stemThick"]
    cloth_thick = geom["clothThick"]
    theta = -math.pi / 2 * amount
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    def xform(lx: float, ly: float) -> tuple[float, float]:
        return (
            pivot_x + lx * cos_t - ly * sin_t,
            pivot_y + lx * sin_t + ly * cos_t,
        )

    return [
        xform(0, -stem_thick / 2),
        xform(0, stem_thick / 2),
        xform(stem, -stem_thick / 2),
        xform(stem, stem_thick / 2),
        xform(stem - cloth_thick, -cloth),
        xform(stem, -cloth),
        xform(stem, 0),
        xform(stem - cloth_thick, 0),
    ]


if __name__ == "__main__":
    unittest.main()
