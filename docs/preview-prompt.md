# Marketplace preview artwork

`../preview.png` was composed with the built-in imagegen tool. The individual
screenshots in `screenshots/` are rendered from the plugin's QML with sample
mail. Use these inputs in order when refreshing the overview:

1. `screenshots/unread-pile.png`
2. `screenshots/accounts.png`
3. `screenshots/help.png`

Check all UI text against those screenshots before replacing the overview.

## Generation prompt

```text
Use case: compositing / ads-marketing.
Asset type: a polished landscape GitHub repository and Omarchy plugin marketplace preview.png, 1920x1080.
Primary request: turn the supplied REAL current product screenshots into an attractive, restrained product hero for "You've Got Mail", an unread-only Omarchy bar widget. The main unread list is the clear hero, with Accounts and keyboard Help as smaller supporting views.
Input images: Image 1 is the actual unread mail panel and is the primary compositing insert. Image 2 is the actual Accounts panel, a supporting insert. Image 3 is the actual Shortcuts panel, a supporting insert. Preserve these interfaces, icons, typography, sample messages, account names, counts and wording exactly as provided; treat them as screenshots, not inspiration for a redesigned app. Straight-on flat panels, no perspective or distortion. Supporting views may be smaller and the Help view may be a neatly cropped excerpt, but never obscure or crop a word in half.
Art direction: quietly premium, editorial, warm developer-tool aesthetic suited to Omarchy. Deep charcoal/teal background derived from the screenshots, cream typography, restrained amber accents. Carefully aligned layout with generous margins, subtle fine texture, fine borders and soft subtle shadows that lift the actual screenshot panels. No luminous glow, neon, purple gradient, 3D mailbox, clip art, device frames, browser chrome or busy decoration.
Hierarchy: bold large product name high in the composition, a short descriptive line below, then an artfully balanced arrangement of the real panels with the unread panel substantially larger than either support. Small simple labels outside the panels may read "UNREAD", "ACCOUNTS", "SHORTCUTS". Keep breathing room and make the main title very legible at thumbnail size.
Exact display copy:
small eyebrow: "OMARCHY BAR PLUGIN"
large title: "You've Got Mail"
subtitle: "Unread mail only. One pile, across every account."
small footer: "Gmail · Outlook · Fastmail · IMAP · HEY"
tiny footer note: "Sample mail shown"
Use an elegant clean typographic pairing with a strong title and monospace supporting details compatible with the actual panel. No invented features, notification bubbles, compose buttons, search field, AI badges, logo redesign, release numbers, fake desktop environment, URLs or additional marketing claims. Deliver one finished full-bleed landscape image.
```
