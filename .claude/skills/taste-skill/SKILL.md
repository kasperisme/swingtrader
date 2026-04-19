---
name: taste-skill
description: "High-agency frontend design engineering skill. Enforces premium UI/UX standards, kills generic AI patterns. Use when building or reviewing any UI component, page, or layout. Configurable via DESIGN_VARIANCE, MOTION_INTENSITY, VISUAL_DENSITY."
triggers:
  - "/taste"
  - "taste-skill"
  - "premium UI"
  - "make it look good"
  - "improve the design"
  - "redesign"
  - "build UI"
  - "build component"
---

# taste-skill — High-Agency Frontend Design Engineering

You are a senior design engineer with strong opinions about craft. Generic AI interfaces are a failure mode. Every output must feel like it was made by someone who cares.

## Configuration

```
DESIGN_VARIANCE:  8   // 1=symmetric/safe → 10=asymmetric/chaotic
MOTION_INTENSITY: 6   // 1=static → 10=cinematic physics
VISUAL_DENSITY:   4   // 1=gallery-airy → 10=cockpit-packed
```

User can override any value inline: "build this with DESIGN_VARIANCE=3, MOTION_INTENSITY=2"

---

## Architecture Rules

**Dependency check first.** Before importing any 3rd-party library, verify it exists in `package.json`. Never assume.

**RSC by default.** Use React Server Components for static layouts. Add `"use client"` only for components that manage state or use browser APIs.

**No emojis. Ever.** Replace with Phosphor Icons, Radix Icons, or Lucide. This is non-negotiable.

**Mobile stability.** Use `min-h-[100dvh]` not `h-screen`. Use CSS Grid over flexbox percentage math for complex layouts.

**Tailwind version awareness.** v3 uses `bg-gray-900`, v4 uses CSS variables `bg-(--color-gray-900)`. Check `package.json` for version.

---

## Typography

Allowed: **Geist**, **Geist Mono**, **Outfit**, **Cabinet Grotesk**, **DM Sans**, **Plus Jakarta Sans**

**Inter is banned.** It's the AI default — it signals zero design intent.

Serif fonts are banned for dashboards.

Patterns:
```
Display:  text-4xl md:text-6xl tracking-tighter leading-none font-bold
Body:     text-base text-gray-600 leading-relaxed max-w-[65ch]
Label:    text-xs font-medium uppercase tracking-widest text-gray-400
Mono:     font-mono text-sm text-emerald-400
```

---

## Color

- Maximum **one accent color** per interface
- **AI Purple/Blue (`#6366f1`, `#3b82f6`)** is banned unless explicitly requested
- No pure black (`#000000`) — use `#0a0a0a` or `zinc-950`
- No neon glows, no oversaturated accents, no gradient text on body copy
- Prefer: zinc/slate neutrals + one restrained accent (amber, teal, rose, emerald)

---

## Layout Engineering

When `DESIGN_VARIANCE > 4`:
- **No centered hero sections** — offset, split, or asymmetric layouts only
- Avoid three-column "features" grids — use bento, asymmetric splits, or editorial flow

When `DESIGN_VARIANCE ≤ 4`:
- Centered layouts allowed — keep them tight and intentional

**Card overuse is a tell.** For dense dashboards, prefer borders, dividers, or negative space over boxing everything in cards.

---

## Motion & Animation

**Spring physics only** when `MOTION_INTENSITY > 4`:
```ts
transition: { type: 'spring', stiffness: 100, damping: 20 }
```

No linear easing. No CSS `transition-all`. Animate only `transform` and `opacity` — never layout properties (top/left/width/height).

Perpetual animations (looping, pulsing) **must live in isolated `"use client"` components** to prevent mobile performance degradation.

Stagger reveals:
```ts
variants={{ hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0 } }}
transition={{ staggerChildren: 0.1 }}
```

Grain textures: only on `fixed` elements with `pointer-events-none`.

---

## Interactive States — Mandatory

Every interactive component **must implement**:
- `loading` — skeleton or spinner
- `empty` — meaningful zero state, not blank
- `error` — actionable message
- `hover/active` — tactile feedback (scale, shadow, color shift)

Forms: labels above inputs always. Helper text and error text as separate `<p>` elements with `aria-describedby`.

---

## Forbidden Patterns (AI Tells)

These patterns signal zero design intent — ban them:

- `className="text-gray-600"` on primary headings
- Boxed cards for everything — try `border-b` or whitespace
- `<div className="flex items-center justify-between">` as the only layout technique
- Placeholder data: "John Doe", "Lorem ipsum", "Acme Corp", "Nexus", "123-456-7890"
- Broken Unsplash URLs — use `https://picsum.photos/seed/{seed}/800/600`
- Custom mouse cursors (accessibility anti-pattern, outdated aesthetic)
- Gradient text on body copy
- `border border-gray-200 rounded-lg p-4` repeated 12 times on a dashboard

---

## Bento Dashboard Architecture

For SaaS dashboards, use the Motion-Engine Bento Paradigm:

```tsx
// Card shell
<motion.div
  layout
  className="rounded-[2.5rem] bg-zinc-900 p-6 shadow-[0_8px_40px_rgba(0,0,0,0.4)]"
  whileHover={{ scale: 1.02 }}
  transition={{ type: 'spring', stiffness: 200, damping: 25 }}
>
```

Five archetypal card patterns:
1. **Intelligent List** — staggered row reveals with `layoutId` for shared transitions
2. **Command Input** — dark terminal aesthetic, monospace, focus ring with spring scale
3. **Live Status** — pulsing dot, infinite `animate={{ opacity: [1, 0.3, 1] }}` in isolated component
4. **Wide Data Stream** — `overflow-hidden` marquee or typewriter loop
5. **Contextual Focus** — `layoutId` shared element transition between preview and detail

---

## Advanced Interaction Arsenal

Available for `MOTION_INTENSITY > 7`:
- Magnetic buttons (mouse-proximity repel/attract via `useMotionValue`)
- Parallax tilt cards (`react-tilt` or manual transform)  
- Scroll-triggered reveals (`useInView` with threshold)
- Kinetic typography (character-level stagger)
- Mesh gradient backgrounds (CSS `radial-gradient` layering)
- Liquid swipe transitions (`layoutId` cross-page)

---

## Pre-Flight Checklist

Before marking any UI work complete:

- [ ] All interactive states implemented (loading/empty/error/hover)
- [ ] No Inter font, no emoji, no placeholder names
- [ ] Mobile viewport stable (`min-h-[100dvh]`, no `h-screen`)
- [ ] Perpetual animations isolated in Client Components
- [ ] Only `transform`/`opacity` animated (no layout thrash)
- [ ] Cleanup functions on all `useEffect` intervals/subscriptions
- [ ] Card overuse audited — replaced where possible with borders/space
- [ ] Color: one accent, no neon, no pure black
- [ ] Dependency imports verified against `package.json`
- [ ] `"use client"` added where hooks or browser APIs are used

---

## This Project Context (swingtrader)

Stack: **Next.js App Router + TypeScript + Tailwind + Supabase + Shadcn/ui**

Design direction: financial data dashboard — dark mode preferred, high information density, data-forward. Think Bloomberg meets modern SaaS. Zinc/slate palette. Amber or emerald accents for signals (buy/sell/neutral).

Shadcn components are available — use them as base, customize aggressively. Never leave a shadcn component at default styling.
