---
name: mobile-fintech-design
description: >
  Anti-slop mobile UI design for financial screeners, trading tools, and data-dense fintech
  dashboards. Use this skill whenever the user needs to design or improve a mobile interface for
  newsimpactscreener, Hans, or any financial/trading product — including landing pages, screener
  cards, news feeds, market regime indicators, watchlists, or Telegram-facing web views. Triggers
  on phrases like "design the mobile UI", "make it accessible on mobile", "improve the screener
  layout", "build the frontend", "make the site look good on phone", "redesign for mobile",
  or any mention of the newsimpactscreener.com website. Also triggers when the user shares a
  screenshot or URL of a financial UI and wants it improved.
---

# Mobile Fintech Design Skill

Produces distinctive, production-grade mobile UI for financial screeners and trading tools.
Avoids every generic AI-slop pattern. Outputs working HTML/CSS/JS or React — never wireframes
or descriptions alone.

## Step 0 — Read the platform context

newsimpactscreener.com is a news impact screener forked from a swing trading project (Hans).
It uses the Minervini/O'Neil methodology (VCP, RS rank, Stage Analysis, Trend Template).
The audience is active traders who check signals on mobile between market hours.
The tone is: **data terminal, not consumer app**. Think Bloomberg on a phone, not Robinhood.

## Step 1 — Commit to an aesthetic direction

Before writing a line of code, answer these four questions in a comment block:

1. **Tone**: Pick one — dark terminal / editorial light / brutalist raw / cinematic dark / ink on paper
2. **Unforgettable detail**: What single thing will the user remember? (e.g. a pulsing live dot, a score bar colour system, a monospace ticker ticker, a left-border signal strip)
3. **Typography pair**: One display/mono font for data + one humanist sans for prose. Never Inter, Roboto, Arial.
4. **Colour system**: One dominant dark surface + one sharp signal accent (not purple gradient). Green for bullish, red/coral for bearish — always. Secondary accent for RS rank or confidence scores.

## Step 2 — Mobile-first constraints (hard rules)

Apply all of these before touching aesthetics:

| Constraint | Value |
|---|---|
| Minimum tap target | 44 × 44 px |
| Max content width | 390 px (iPhone 15 Pro baseline) |
| Bottom nav placement | Fixed bottom — thumb zone |
| Max nav items | 4–5 |
| Font size floor | 11 px (labels), 13 px (body), 15 px (ticker), 18 px+ (hero numbers) |
| Touch scroll direction | Single axis per region — never both H + V |
| Card layout columns | 1 column full-width cards (data-dense) or 2-col metric tiles max |
| Loading states | Skeleton screens, not spinners |
| Gesture support | Pull-to-refresh on feed, swipe-to-dismiss on cards |

## Step 3 — Anti-slop rules

These are the specific patterns that make AI-generated UIs look generic. Violating any of them
is a hard failure.

### Typography anti-slop
- **Never** use Inter, Roboto, Arial, system-ui as a primary font
- Use a monospace font (`Space Mono`, `JetBrains Mono`, `IBM Plex Mono`) for all tickers, scores, prices, RS ranks, timestamps
- Use a humanist sans (`DM Sans`, `Plus Jakarta Sans`, `Bricolage Grotesque`) for headlines and body
- Letter-spacing must signal hierarchy: tight (`-0.02em`) on hero numbers → slightly open (`0.04em`) on badge labels → wide (`0.08em–0.1em`) on section headers
- Never use the same letter-spacing value twice in a layout

### Shadow anti-slop
- Every element gets a different shadow treatment based on its elevation, or no shadow at all
- Flat dark UI: use `border: 0.5px solid` + subtle left/top accent strip instead of box-shadows
- Cards that are "above" should use a `1px solid` border at higher opacity than background cards
- No uniform `box-shadow: 0 2px 8px rgba(0,0,0,0.1)` applied indiscriminately

### Color anti-slop
- Never use purple gradients on white backgrounds
- Never use a single color for all interactive elements
- Signal colors must be semantic: green = bullish/positive, red/coral = bearish/negative, amber = neutral/watch, blue = informational (RS rank, confidence)
- Dark mode is the default for this product (traders, dim environments, OLED screens)
- Use left-border accent strips (3–4 px) to encode signal direction on cards — not background fills

### Layout anti-slop
- Never center-align data tables or ticker rows — left-align labels, right-align numbers
- Avoid equal-weight grids; use asymmetric columns (e.g. 2fr 1fr) to create visual hierarchy
- Negative space is intentional — do not fill every pixel
- Section headers should be small-caps monospace at reduced opacity, not bold title-case

### Component anti-slop
- Score/impact bars: use thin (`3–4 px`) coloured fill bars — not fat progress bars or circular dials
- Badges/pills: font-size 9–10 px, monospace, letter-spacing 0.06 em, coloured border + matching tint background — not solid filled rounded rectangles
- Avoid generic card shadows; use border-left signal strips + subtle background tint instead
- Bottom navigation: icon + 9 px mono label, active item gets accent colour dot below label

## Step 4 — Information hierarchy for screener cards

Each screener result card must show (in this priority order):

1. **Ticker** — largest, monospace, always visible
2. **Signal direction** — left-border strip (green/coral/amber)
3. **News headline** — 2-line clamp, muted colour
4. **Factor pills** — which dimensions are triggered (e.g. `supply chain ↑`, `pricing power`, `earnings surprise`)
5. **Impact score bar** — thin colour fill bar + numeric score (0.00–1.00)
6. **RS Rank badge** — top-right, blue tinted
7. **Company name** — smallest, most muted

Never show all data at once — use progressive disclosure: tap card to expand to full factor breakdown.

## Step 5 — Key screens to implement

Read `references/screens.md` for detailed per-screen specs.

Priority order for newsimpactscreener.com:

1. **Feed** — live news impact cards, sorted by impact score
2. **Market regime bar** — persistent top widget (SPY/QQQ, FTD day, regime label)
3. **Screener results** — filterable list of tickers with scores
4. **Ticker detail** — full factor breakdown, price chart stub, news list
5. **Settings / filters** — threshold sliders, dimension toggles
6. **Landing page** — conversion-focused, mobile hero, no fluff

## Step 6 — Performance rules

- Use `font-display: swap` on all Google Fonts imports
- Skeleton screens for any data-dependent card list
- Lazy-load images and charts below the fold
- Use `will-change: transform` only on animated elements
- Avoid importing full icon libraries — use inline SVG or Unicode symbols for trading indicators
- CSS custom properties for all colours and spacing — no hardcoded hex in component styles

## Step 7 — Output format

Always produce **working code**, not descriptions. Default output:

- Single-file HTML (with `<style>` + `<script>` inlined) for standalone screens
- React `.jsx` with Tailwind utility classes for component library integration
- Always include a `<!-- AESTHETIC DIRECTION -->` comment block at the top explaining the four choices from Step 1
- Always test: does it look good at 375 px width? Does every tap target pass the 44 px rule?

## Quick reference: preferred font pairings

| Pairing | Data font | Body font | Vibe |
|---|---|---|---|
| Terminal dark | Space Mono | DM Sans | Bloomberg-esque |
| Editorial light | JetBrains Mono | Libre Baskerville | Newspaper / research |
| Industrial | IBM Plex Mono | IBM Plex Sans | Dense, systematic |
| High signal | Fira Code | Plus Jakarta Sans | Modern SaaS terminal |

## Quick reference: colour system (dark theme default)

```css
--surface-base:    #0a0e14;   /* deepest background */
--surface-card:    #111620;   /* card background */
--surface-raised:  #181e2b;   /* elevated element */
--border-subtle:   #2a3148;   /* default border */
--accent-bull:     #00e5a0;   /* bullish green */
--accent-bear:     #e05c3a;   /* bearish coral */
--accent-watch:    #e8a020;   /* neutral amber */
--accent-info:     #4a9eff;   /* RS rank, confidence */
--text-primary:    #d4daf0;
--text-secondary:  #8a96b8;
--text-muted:      #4a5470;
```
