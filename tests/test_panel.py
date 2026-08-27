from __future__ import annotations

import json
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

    def test_surfaces_partial_warning(self) -> None:
        self.assertIn("property string warningText", self.qml)
        self.assertIn("data.warning", self.qml)
        self.assertIn("partialWarning", self.qml)

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
        self.assertIn("~/.bun/bin", readme)
        self.assertIn("YOU_GOT_MAIL_IMAP_PASSWORD", readme)

    def test_changelog_matches_manifest(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {self.manifest['version']}", changelog)


if __name__ == "__main__":
    unittest.main()
