"""The plugin's own text lives in i18n/en.json, and every string in the code matches it."""

from __future__ import annotations

import json
import re
import unittest

from support import ROOT

SOURCES = ("Panel.qml", "FailureNotice.qml", "PanelMenu.qml", "MailState.js")
STR = r'"((?:[^"\\]|\\.)*)"'
SINGLE = re.compile(r"(?:\btr|\bT\.t|root\.tr)\(\s*" + STR + r"\s*,\s*" + STR)
PLURAL = re.compile(
    r"(?:\btrn|\bT\.n|root\.trn)\(\s*" + STR + r"\s*,\s*(.+?),\s*" + STR + r"\s*,\s*" + STR + r"\s*\)",
    re.S,
)


def _unquote(text: str) -> str:
    return json.loads('"' + text + '"')


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads((ROOT / "i18n" / "en.json").read_text(encoding="utf-8"))
        cls.used: dict[str, list] = {}
        for name in SOURCES:
            text = (ROOT / name).read_text(encoding="utf-8")
            for key, english in SINGLE.findall(text):
                cls.used.setdefault(key, []).append(_unquote(english))
            for key, _count, one, other in PLURAL.findall(text):
                cls.used.setdefault(key, []).append({"one": _unquote(one), "other": _unquote(other)})

    def test_every_string_in_the_code_is_in_the_catalog_with_the_same_english(self) -> None:
        for key, values in self.used.items():
            self.assertIn(key, self.catalog, key)
            for value in values:
                self.assertEqual(self.catalog[key], value, key)

    def test_every_catalog_entry_is_used(self) -> None:
        self.assertEqual(sorted(set(self.catalog) - set(self.used)), [])

    def test_plural_entries_have_english_forms_and_a_number(self) -> None:
        for key, value in self.catalog.items():
            if isinstance(value, dict):
                self.assertEqual(set(value), {"one", "other"}, key)
                self.assertTrue(all("%1" in form for form in value.values()), key)
            else:
                self.assertIsInstance(value, str, key)

    def test_no_bare_english_is_shown(self) -> None:
        # Text, tooltips and headers take their words from the catalog.
        shown = re.compile(r'^\s*(?:text|tooltipText|title|detail|action):\s*"[^"]*[A-Za-z]{2}', re.M)
        for name in ("Panel.qml", "FailureNotice.qml", "PanelMenu.qml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertEqual(shown.findall(text), [], name)

    def test_qml_property_names_start_lower_case(self) -> None:
        # QML refuses the whole file otherwise, which no unit test here would see.
        for name in ("Panel.qml", "FailureNotice.qml", "PanelMenu.qml", "MailSlotIcon.qml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"^\s*(?:readonly\s+)?property\s+\S+\s+([A-Z]\w*)", text, re.M), [], name)

    def test_the_panel_reads_its_catalogs_with_translations(self) -> None:
        qml = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn('Translations { directory: Qt.resolvedUrl("i18n") }', qml)
        self.assertIn("I18n.formatNumber(count)", qml)
        self.assertIn("toLocaleDateString(Qt.locale(I18n.formatLocale), Locale.ShortFormat)", qml)
        self.assertNotIn("Qt.formatDate", qml)
        self.assertIn('iconPrev: I18n.rightToLeft ? "\\uF054" : "\\uF053"', qml)
        self.assertIn('iconNext: I18n.rightToLeft ? "\\uF053" : "\\uF054"', qml)


if __name__ == "__main__":
    unittest.main()
