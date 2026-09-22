# Marketplace preview artwork

`../preview.png` was composed with the built-in imagegen tool. Its bold
monospaced typography, square borders, and grid take inspiration from
[Omapicks](https://omapicks.com/).

All five images in `screenshots/` are rendered from the plugin's QML with
sample mail and the installed **Tokyo Night** theme. The shell's `monospace`
font resolves to JetBrainsMono Nerd Font on the capture machine. The panels
use square corners and a 2px blue border, captured at twice their display size.

| Theme role | Color |
|---|---|
| Panel background | `#1a1b26` |
| Text | `#a9b1d6` |
| Accent and border | `#7aa2f7` |
| Bright hero text | `#c0caf5` |

Re-render every screenshot from the same theme before refreshing the hero.
Use these inputs in order:

1. `screenshots/unread-pile.png`
2. `screenshots/accounts.png`
3. `screenshots/help.png`
4. A capture of Omapicks in dark mode, for typography and layout reference only.

Keep `screenshots/paging.png` and `screenshots/caught-up.png` on that theme too.
Check all hero UI text against the actual screenshots before replacing it.

## Generation prompt

```text
Use case: compositing.
Asset type: landscape GitHub repository and Omarchy marketplace preview.png, approximately 16:9 at high resolution.
Task: build a new polished preview for the unread-only Omarchy widget You've Got Mail. Use the REAL screenshots supplied in the user's CURRENT Tokyo Night theme. The previous preview was rejected for an ornate serif headline and green palette; the replacement must use bold monospaced typography and this new navy/blue/lavender theme throughout.
Inputs and roles:
Image 1: unread-panel screenshot, the main product insert. Preserve its contents.
Image 2: Accounts screenshot, supporting product insert. Preserve its contents.
Image 3: Shortcuts screenshot, supporting product insert. Preserve its contents.
Image 4: Omapicks website screenshot, STYLE REFERENCE ONLY for bold monospace heading, tidy grid, flat navy surfaces, thin rules and square edges. Do not insert any Omapicks content, ranking interface, branding, words, counts or controls.
Typography: use a crisp heavyweight modern MONOSPACED typeface for the headline, like JetBrains Mono Bold or Cascadia Mono Bold, closely matching the large heading in Image 4. Letterforms must be recognizably fixed-width and terminal-like, with simple blocky geometry. NO SERIF FONT anywhere, no calligraphy, no elegant editorial display font. Small copy is also clean monospace. Use lowercase for the marketing title and bracketed section labels inspired by Omapicks.
Palette: exact flat Tokyo Night navy background #1a1b26, slightly lifted panels #24283b where appropriate, lavender foreground #c0caf5 and #a9b1d6, muted #949bb5, thin divider #414868, blue accent #7aa2f7. The screenshots' original navy surfaces and bright blue square borders must remain. No green/teal surfaces, mint, cream, gold or orange. No gradients, grain, paper texture, neon, glow, shine or decorative illustrations.
Layout: organized, sharply aligned, flat and spacious. A large left-aligned monospace title and short subtitle above a product gallery. The unread panel is substantially larger and the clear focus; Accounts and Shortcuts sit beside it as smaller supporting views. Preserve the screenshot panels' aspect ratios and internal layout, use rectangular square corners, no perspectives or warping. Do not stretch the screenshots, rewrite their text, simplify their icons, duplicate a row, invent features, or change counts. If needed use a clean crop of the Shortcuts view that ends between complete rows. Avoid overlapping any useful content. The result should read clearly as an attractive app preview even as a thumbnail, with generous outer margins and crisp UI text.
Exact marketing text:
small eyebrow: "[ omarchy bar plugin ]"
large headline: "you've got mail"
subtitle: "Unread mail only. One pile, across every account."
section labels: "[ unread ]", "[ accounts ]", "[ shortcuts ]"
footer: "Gmail · Outlook · Fastmail · IMAP · HEY"
small footer note: "Tokyo Night · sample mail"
No other marketing text, URLs, browser chrome, window titlebars, fake desktop, logos, version numbers, notification features, compose buttons, AI badges or watermark.
Deliver one finished full-bleed landscape preview image with the clear monospace visual character of Omapicks and the exact current-theme screenshots.
```

## Text correction prompt

```text
Use case: text-localization.
Image 1 is the edit target: the finished You've Got Mail preview.
Image 2 is a reference showing the real Accounts panel and the correct spelling.
Make exactly one small correction to Image 1: in the middle Accounts panel, the final blue link under "Setup guide" currently incorrectly reads "Open suide". It must read EXACTLY "Open guide" (O p e n, space, g u i d e), matching Image 2. Make the lowercase g unambiguous. Preserve the blue link color, size and monospaced font.
Do not change the rest of the image. Keep the large bold monospaced "you've got mail" heading, Tokyo Night navy/blue/lavender palette, all other wording and numbers, panel positions, dimensions, margins, square borders, footer and sample mail exactly unchanged. No other edits or new text.
```
