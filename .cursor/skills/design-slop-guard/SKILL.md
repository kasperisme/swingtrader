---
name: design-slop-guard
description: "Project-specific UI guardrails for SwingTrader to prevent generic AI-generated design drift. Use when editing UI, charts, layout, tokens, or component styling."
---

# SwingTrader Design Slop Guard

Use this skill for any UI work in `code/ui` to enforce a consistent, intentional visual system.

## Canonical Design System (SwingTrader)

Use these as the default source of truth unless the user explicitly requests an override.

### Brand style direction

- Product style: **editorial-finance minimalism**
- Tone: focused, calm, high-signal, low-noise
- Visual principle: **content-first** (layout and hierarchy over decoration)
- Avoid: generic SaaS glow-heavy visuals, random gradients, and excessive card stacks

### Color system

- Light mode baseline: warm-neutral canvas (not pure white)
- Dark mode baseline: deep slate (already primary experience)
- Primary accent: amber
- Secondary accent: violet (sparingly, for contrast context only)
- Sentiment semantics:
  - positive: green
  - negative: red
  - neutral: muted foreground
- Chart colors must use token palette (`--chart-*`, `--primary`, `--accent`) and semantic mapping

### Typography

- Font family: Plus Jakarta Sans
- Headings: tight tracking, high contrast, medium-to-bold weight
- Body: readable density, avoid tiny paragraph text for core content
- Micro labels: uppercase tracking only for section/control metadata
- Do not make entire control bars `text-xs`; reserve `text-xs` for secondary metadata

### Spacing and rhythm

- Use consistent spacing scale (Tailwind defaults are fine; avoid one-off arbitrary spacing)
- Separation hierarchy:
  1. whitespace
  2. muted background shift
  3. border/divider (only when necessary)
- Prefer fewer vertical dividers; use only for meaningful section boundaries

### Containers and layering

- Default: flat content sections (minimal boxes)
- Use containers only when highlighting:
  - primary proof/snapshot panel
  - critical CTA
  - key comparison/highlight module
- Do not nest boxes inside boxes unless there is a clear semantic reason
- Decorative layers (glows, extra gradients, background meshes) are opt-in and rare

### Flat hierarchy first (priority rule)

- Prefer a **flat visual hierarchy** over stacked cards and nested surfaces.
- Primary separation order:
  1. spacing
  2. typography contrast
  3. minimal divider (only when needed)
  4. container/background (last resort)
- Avoid multi-level elevation patterns (card inside card inside section).
- Keep shadows subtle and sparse; no decorative shadow layering.
- If two adjacent sections are both boxed, remove at least one box unless both are critical highlights.
- Default list/item treatment should be unboxed unless emphasis is required.

### Components

- Favor shared primitives and repeated wrappers over inline style duplication
- Dense control areas must be grouped and labeled
- Keep interaction styles subtle and stable (no layout-shifting hover gimmicks)

### Charts and data UI

- Primary narrative lines first; overlays are subordinate
- Secondary metrics (e.g., article count) must be legible but not dominant
- Tooltip hierarchy is required:
  1. x-axis bucket label
  2. critical context metrics (e.g., article count)
  3. sorted series values
- Axis strategy must be explicit when mixing different units

## Purpose

Prevent "AI slop" patterns:
- random hex colors
- generic spacing/typography
- ad-hoc control bars
- inconsistent chart styling
- z-index hacks

## Scope

Apply to:
- `code/ui/app/**`
- `code/ui/components/**`
- `code/ui/app/protected/**`
- `code/ui/app/globals.css`
- `code/ui/tailwind.config.ts`

## Non-Negotiable Rules

### 1) Token-first colors only

- Use semantic tokens, not raw hex values.
- Prefer `hsl(var(--...))` and Tailwind semantic utilities:
  - `bg-background`, `bg-card`, `text-foreground`, `text-muted-foreground`
  - `border-border`, `ring-ring`
  - `hsl(var(--chart-1..5))`, `hsl(var(--primary))`, `hsl(var(--accent))`
- Do not introduce new hex colors inside TSX unless there is a documented exception.

### 2) Warm canvas baseline (light mode)

- Keep a warm-neutral light background (not pure white).
- Preserve layered surfaces:
  - canvas (`--background`)
  - raised surface (`--card` / `--popover`)
  - muted layer (`--muted`)

### 3) Control hierarchy pattern (required)

For dense control bars (filters/toggles/series):
- Wrap in a container surface: rounded + border + subtle card fill.
- Group controls into labeled blocks with uppercase micro-labels:
  - ex: "Granularity", "Smoothing", "Series Mode", "Overlay"
- Avoid a flat row of identical `text-xs` controls with no grouping.

### 4) Chart styling system

- Use tokenized palette for all lines/bars.
- Keep interaction affordances consistent:
  - subtle grid
  - clear tooltip hierarchy
  - reference line at zero for sentiment charts
- If adding secondary metrics (like article count):
  - expose readable axis strategy
  - avoid near-invisible overlays
  - keep bars/lines visually subordinate to primary narrative signal

### 5) Z-index discipline

- Do not use extreme z-index values like `z-[9999]`.
- Use a small scale (`z-10`, `z-20`, `z-30`, `z-40`, `z-50`) and keep overlays predictable.

### 6) Reuse primitives, avoid ad-hoc style fragments

- Prefer shared UI primitives (`components/ui/*`) and existing shell patterns.
- New repeated patterns should be extracted into reusable wrappers.

### 7) Container discipline (landing pages and marketing pages)

- Default to minimal layering: text and spacing first, containers second.
- Use bordered/filled containers only for high-signal content:
  - hero proof block
  - key CTA
  - critical comparison/highlight module
- Do not wrap every section item in its own card/box.
- Avoid decorative background layers unless they add clear information hierarchy.
- If a section reads clearly without a box, keep it unboxed.

### 8) Flat hierarchy enforcement

- Treat "flat first" as default for all pages, not only landing pages.
- Before adding a border/background wrapper, justify what information priority it adds.
- If priority is not explicit, remove the wrapper and rely on spacing + type hierarchy.

## SwingTrader-specific UI Patterns

### News Trends chart

- Primary: cluster trend lines.
- Secondary: benchmark and article-count overlays.
- Tooltip order:
  1. bucket label
  2. article count (if present)
  3. sorted metric rows

### Header shell

- Sticky header should use sane z-index and translucent surface.
- Keep nav links and action zones balanced left/right.

## PR / Edit Checklist

Before finalizing UI edits, verify:

- [ ] No new hardcoded hex colors in TSX
- [ ] New visual styles map to existing tokens
- [ ] Controls are grouped with clear labels (not flat dense row)
- [ ] Chart overlays remain legible and subordinate
- [ ] No z-index hacks
- [ ] Container count is minimal; boxes only where emphasis is intentional
- [ ] Flat hierarchy preserved (no unnecessary nested surfaces/elevation)
- [ ] Light + dark mode both readable
- [ ] `npm run build` succeeds for `code/ui`

## Anti-patterns (reject these)

- "Make it clean and modern" without style constraints.
- Pure white canvas + default gray borders + random blue accents.
- Copy-paste card/button classes across files without shared primitives.
- Chart color choices that differ per page for the same semantic role.
- Boxing every list item/section by default with no hierarchy rationale.
- Stacking multiple decorative layers (gradients/glows/shadows) to create perceived depth without information value.

## Suggested Prompt Add-on

When requesting UI edits, prepend:

`Apply design-slop-guard skill. Token-first styling, grouped control hierarchy, chart token palette, and no ad-hoc hex.`

## Extended Prompt Template (Recommended)

Use this fuller prompt when you want highly consistent output:

`Apply design-slop-guard skill. Use SwingTrader editorial-finance minimalism with a flat hierarchy first. Warm-neutral light canvas, token-only colors, minimal containers, sparse dividers, and no unnecessary nested surfaces. Keep charts tokenized with clear primary-vs-secondary hierarchy. Group dense controls with labels and avoid flat text-xs bars.`

