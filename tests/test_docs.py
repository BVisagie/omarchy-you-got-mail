"""Relative links and #anchors in the Markdown docs point at something that exists."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from support import ROOT

LINK = re.compile(r"\]\(([^)\s]+)\)|<img[^>]*\bsrc=\"([^\"]+)\"")


def _anchors(path: Path) -> set[str]:
    # GitHub's heading ids: lower case, punctuation dropped, spaces to dashes.
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"#{1,6}\s+(.*)", line)
        if heading:
            text = re.sub(r"[`*]", "", heading.group(1)).strip().lower()
            found.add(re.sub(r"[^\w\- ]", "", text).replace(" ", "-"))
    return found


class DocLinkTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self) -> None:
        docs = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]
        for doc in docs:
            for match in LINK.finditer(doc.read_text(encoding="utf-8")):
                target = match.group(1) or match.group(2)
                if re.match(r"[a-z]+:", target):
                    continue  # https:, mailto:
                path, _, anchor = target.partition("#")
                resolved = (doc.parent / path).resolve() if path else doc
                self.assertTrue(resolved.exists(), f"{doc.name}: {target}")
                if anchor and resolved.suffix == ".md":
                    self.assertIn(anchor, _anchors(resolved), f"{doc.name}: {target}")

    def test_readme_keeps_install_and_removal(self) -> None:
        # The plugin marketplace requires both in the root README.
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("omarchy plugin add https://github.com/BVisagie/omarchy-you-got-mail.git", readme)
        self.assertIn("omarchy plugin remove bvisagie.you-got-mail", readme)


if __name__ == "__main__":
    unittest.main()
