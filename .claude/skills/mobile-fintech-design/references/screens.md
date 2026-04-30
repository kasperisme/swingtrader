# Screen Specifications — newsimpactscreener.com

## 1. Feed Screen (primary)

The main screen. Users land here. Most time is spent here.

**Layout**
- Sticky top: market regime bar (see below)
- Sticky top below regime: filter chip row (scrollable horizontal, single line)
- Scrollable card list below
- Fixed bottom nav

**Market Regime Bar**
```
[ BULL CONFIRMED  FTD day 4 ]  [ SPY 593.40  ▲ +1.14% | mini sparkline ]
```
- Full width, dark surface, 56 px height
- Left side: regime label (monospace, accent green for bull / coral for bear / amber for watch)
- Right side: SPY price + delta + 8-bar sparkline (4 px bars)
- Tapping opens market regime detail modal

**Filter chips** (scrollable row, no wrapping)
- ALL | BULL | BEAR | WATCH | >0.8 SCORE | MY WATCHLIST
- Active chip: accent border + tint background
- 32 px height, 10 px horizontal padding, monospace 10 px

**News Impact Card**
```
┌─[green strip]──────────────────────────────┐
│ NVDA                              [RS 97]  │
│ Nvidia Corp                                │
│ "Blackwell Ultra yields exceed targets"    │
│ [supply chain ↑] [pricing power] [EPS ↑]  │
│ IMPACT ▓▓▓▓▓▓▓▓░░░░  0.88          4m ago │
└────────────────────────────────────────────┘
```
- 3 px left border strip: green (bull) / coral (bear) / amber (neutral)
- Ticker: 15 px Space Mono bold
- RS badge: top right, 10 px mono, blue tinted pill
- Headline: 12 px DM Sans, 2-line clamp, muted colour
- Factor pills: 9 px mono, coloured by direction
- Impact bar: 3 px height, full-width, colour matches signal direction
- Score: 10 px mono, right-aligned
- Timestamp: 9 px, most muted colour, right-aligned bottom
- Tap: expands to full factor breakdown (accordion, no navigation)

**Pull-to-refresh**: Custom animation — a thin accent-coloured line that fills left-to-right
**Empty state**: Monospace message "NO SIGNALS ABOVE THRESHOLD" with filter hint

---

## 2. Ticker Detail Screen

Reached by tapping a card and then "Full analysis →" within the expanded card.

**Header**
- Back chevron (left) + ticker (center, large mono) + watchlist star (right)
- Price + delta below ticker, large mono

**Price Chart Stub**
- 200 px height placeholder with skeleton animation until loaded
- Date range tabs: 1D | 5D | 1M | 3M (monospace, 10 px)

**Factor Breakdown Section**
- Section label: "FACTOR EXPOSURE" — small mono, muted, uppercase
- Each factor as a row: factor name (left) + score bar (center) + score value (right)
- Bars coloured by direction (green/coral/amber)
- Group factors by cluster: MACRO | FUNDAMENTAL | SUPPLY CHAIN | SENTIMENT

**News List**
- Chronological, compact
- Each item: headline (2-line clamp) + source + time
- Tapping opens source URL

**Minervini Checklist** (if data available)
- Compact checklist: ✓/✗ for each Trend Template criterion
- Monospace, 12 px, green checkmark / coral X

---

## 3. Screener Results Screen

Full market scan results. Accessed from bottom nav.

**Sort controls**
- Horizontal scrollable: IMPACT ↓ | RS RANK ↓ | SIGNAL DATE ↓ | ALPHABETICAL
- Right side: count badge "24 results"

**Compact list rows** (denser than feed cards)
```
[strip] NVDA  Nvidia Corp          RS 97  0.88 ▓▓▓▓▓
        supply chain ↑  pricing power  +2.3%
```
- 64 px row height
- Left strip: signal direction
- Two-line layout: ticker + company + RS badge + score (line 1), top 2 factors + price change (line 2)

---

## 4. Settings / Filters Screen

**Threshold sliders**
- Impact score minimum: slider 0.0–1.0, step 0.05
- RS rank minimum: slider 0–100, step 5
- Market cap filter: toggle chips (Mega | Large | Mid | Small)

**Dimension toggles**
- Each news impact dimension as a toggle row
- Group by cluster (same as Factor Breakdown above)
- Toggle: custom styled, accent colour when on

**Data source section**
- FMP API status indicator (green dot = connected)
- Last sync timestamp
- Manual refresh button

---

## 5. Landing Page (newsimpactscreener.com)

Target: organic traffic from swing trading search terms. Mobile conversion.

**Hero section**
- Headline: bold, large, 2 lines max — "Know before the crowd."
- Sub: 14 px, muted — "AI-scored news impact on your watchlist. Built for Minervini traders."
- CTA button: "Get early access" — full width on mobile, accent green
- Below CTA: sample screener card (static, real-looking data)
- No hero image/illustration — let the card be the visual

**Social proof strip**
- 3 compact stats: "24 dimensions scored" | "Real-time FMP data" | "Minervini methodology"
- Mono font, small, separated by thin vertical dividers

**How it works** (3 steps)
- Icon (inline SVG, 20 px) + heading + 1-sentence description
- Single column on mobile
- No numbered circles — use left-border accent strip

**Feature section**
- 2-column grid on mobile (2 × compact feature tiles)
- Each tile: small icon + feature name + 1-line description
- Dark card, subtle border

**Footer**
- Minimal: logo + nav links + "Built with Hans / Ollama / Claude"
- No cookie banners, no newsletter signup on first load

---

## Navigation (bottom bar, all screens)

```
[ Feed ]  [ Screener ]  [ Watchlist ]  [ Settings ]
```
- 4 items
- Icon (inline SVG, 20 px) + 9 px mono label
- Active: accent colour + 3 px accent dot below label
- Inactive: muted colour
- No background colour change on active — only text/icon colour + dot
- Height: 60 px + safe area inset (for iPhone home bar)
