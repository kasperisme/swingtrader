---
name: nis-chat-reel
description: >-
  Turn a market story into a vertical reel that looks like a text conversation:
  it opens on a phone lockscreen with a wallpaper, a Messages notification
  springs in, the viewer taps it, and NIS explains the story to them as a casual
  back-and-forth — typing indicators, blue and grey bubbles, emoji, a pasted
  ticker list. Use when the user wants a "chat reel", "text message reel",
  "iMessage reel", "notification reel", "DM-style video", "conversation reel",
  or asks to explain a week/story "as a chat" or "as a text conversation".
  Pairs with nis-daily-note (same device chrome, different conceit — that one is
  a Notes screenshot, this one is a conversation). NOT a static ad
  (nis-ad-image) and NOT the notepad/Notes reel (nis-daily-note).
---

# NIS Chat Reel

A market recap nobody asked for is a lecture. The same recap arriving as a text
from someone who noticed something is a conversation — and people finish
conversations. This skill renders that: **the viewer's own phone lights up, and
NIS walks them through the week in messages.**

It reuses the device metrics, fonts, chrome and emoji from **`nis-daily-note`**
(imported, not copied), so the phone in this reel and the phone in the Notes reel
are the same phone.

## The three acts

| Act | What's on screen | Length |
|---|---|---|
| **1 · Lockscreen** | wallpaper + heart motif dead centre, date and clock above, then a Messages banner springs up from the bottom | `--lock-seconds` (default 1.6s) |
| **2 · Tap** | the finger dot lands, the banner flashes and opens into the thread | ~0.3s |
| **3 · Thread** | bubbles land one at a time, NIS types before each of its own, the viewer composes on a real keyboard, the thread auto-scrolls | the rest |

### The compose beat — what happens on every `"from": "you"` message

This is automatic; there is nothing to author for it. Each outgoing message plays
the full gesture, because a message that just *appears* reads as a mockup while a
message you watch someone send reads as a screen recording:

1. **The keyboard rises** (~0.24s) and shoves the whole thread upward — that
   shove is most of what sells it.
2. **The text types itself into the field**, letter by letter, with a blinking
   blue caret. The field scrolls to keep the caret visible, and the predictive bar
   above the keys tracks the word being typed.
3. **The send button lights up** — it sits dimmed and grey while the field is
   empty, and turns blue the moment there's text.
4. **The finger dot lands on send** and the button flashes.
5. **The bubble springs into the thread**, the field clears.
6. **The keyboard drops** — but only when NIS is about to reply. Two outgoing
   messages in a row keep it up, exactly like real texting.

Budget roughly **1.5s of overhead per outgoing message** on top of reading time;
the renderer already weights the timeline for it, but a thread with many short
`you` replies needs a longer `--seconds` than the message count suggests.

## Step 1 — Get the story (don't invent one)

The conversation is a *retelling*, so the facts must already exist. Source them
the same way the Notes reel does:

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-daily-note/scripts/fetch_week_notes.py \
    --days 7 --limit 18 --out output/chats/<date>/rows.json
```

Then get **real price moves** for the tickers you'll name (never estimate them):

```python
from services.viral_reels.data_sources import price_history
```

If a `nis-daily-note` recap for the same week already exists
(`output/notes/<date>/summary.json`), reuse its story and numbers — the chat reel
is a second cut of the same truth, not a second opinion.

## Step 2 — Write the conversation (`chat.json`)

```json
{
  "slug": "2026-08-12-which-side-of-the-invoice",
  "theme": "light",
  "clock": "9:41",
  "contact": "NIS",
  "avatar": "NIS",
  "day_stamp": "Today 9:41",
  "lock": {
    "date": "Wednesday, 12 August",
    "title": "NIS",
    "when": "now",
    "preview": "google's cloud grew 82% this quarter. the stock fell 8%.",
    "gradient": ["#12203A", "#05070D"],
    "motif": "nis_heart",
    "wallpaper": "wallpaper.jpg"
  },
  "messages": [
    {"from": "nis", "text": "google's cloud grew 82% this quarter. the stock fell 8%."},
    {"from": "you", "text": "that can't be right"},
    {"from": "nis", "text": "look at who went up instead", "rows": [
      {"label": "PLTR", "value": "+39.2%"},
      {"label": "NVDA", "value": "+5.3%"}
    ]},
    {"from": "nis", "text": "there it is 👀", "typing": false}
  ],
  "design": {"format": "chat_reel", "voice": "casual_dm", "topic": "ai_capex", "variant": "chat_v1"}
}
```

- **`from`** — `"nis"` (grey, left) or `"you"` (blue, right).
- **`rows`** — a pasted ticker list inside a bubble; `+`/`-` colours the value.
  Green/red only appear on incoming bubbles (on blue they'd be unreadable, so
  they render white).
- **`typing`** — set `false` to suppress the typing indicator before an incoming
  message (use it for a quick one-word follow-up in the same breath).
- **`lock.wallpaper`** — a real photo next to the spec. Omit it and a deep
  gradient with a soft glow is generated from `lock.gradient`.
- **`lock.motif`** — `"nis_heart"` (default) fills a glowing heart with the NIS
  brand artwork at the **centre** of the screen: the heart is a window onto the
  mark (cover-fit and clipped to the silhouette), not a frame around a tile, so
  the flames run out to the edges. It's the wallpaper of someone who likes the
  product. The notification sits below it (iOS 17 stacks lockscreen
  notifications at the bottom), so nothing covers the artwork. `"none"` leaves the gradient bare. The mark is
  found automatically at `code/analytics/scripts/assets/icon.png`; override with
  `lock.logo`. A `lock.wallpaper` photo replaces the motif entirely.
- **`day_stamp`** — the centred divider above the first bubble.

### Writing the voice — this is the whole skill

The renderer only does layout. What makes it work is that it reads like two
people texting, not like copy:

- **Lowercase, short lines, one idea per bubble.** Break a long thought into two
  bubbles instead of one paragraph.
- **The viewer is the smart one.** Let *them* land the punchline — "hold on,
  those all sell TO google and amazon" — and have NIS confirm it ("there it is").
  A viewer who reaches the conclusion themselves believes it.
- **Open on the contradiction, in the first message**, because that message is
  also the lockscreen preview and the thumbnail. "cloud grew 82%. the stock fell
  8%." is the hook.
- **Real reactions**: "wait what", "that can't be right", "ok that's a good
  point". Emoji sparingly — one or two across the whole thread.
- **Never make the viewer say something a real person wouldn't**, especially not
  the CTA. NIS mentions the site once, at the end, plainly.
- **Every number is real.** Same rule as every other skill here: no invented
  moves, no rounded-up growth rates.

Length: **16–20 messages ≈ 30s**. The renderer distributes time by message
length, so you don't hand-time anything.

## Step 3 — Render

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-chat-reel/scripts/build_chat_reel.py \
    --spec output/chats/<date>/chat.json \
    --out output/chats/<date>/9x16 --seconds 30 --fps 30
```

Outputs next to `--out`:
- `chat_reel.mp4` — 1080×1920, h264
- `chat_reel_poster.png` — the lockscreen frame (a good thumbnail)
- `chat_reel_preview_{06,20,55,92}.png` — one still per act, for review

Options: `--seconds`, `--fps`, `--lock-seconds` (how long act 1 holds).

**Review all four previews before shipping** — the lockscreen, the opening
bubbles, the middle, and the ending.

## Step 4 — Caption + publish

Write `caption.txt` next to the spec (the nis-daily-note captions are the voice
reference), then publish via the existing last mile:

```bash
.venv/bin/python -m services.social_publishing.cli publish --ticker <folder> --dry-run
```

## Authenticity rules the renderer already enforces

These are the tells that give away a fake screenshot, so they're handled in code
— don't fight them in the spec:

- Typing indicators only ever precede an **incoming** message — you never watch
  yourself type in a bubble; you watch yourself type on the keyboard.
- The keyboard only dismisses when the **next** message is incoming.
- The send button is dimmed until the field has text.
- A bubble tail is drawn only on the **last** message of a same-sender run.
- The thread is **bottom-anchored** — a short conversation sits at the bottom of
  an empty screen and only scrolls once it outgrows the viewport.
- "Delivered" appears once, under the final outgoing bubble.
- Timestamps are a centred day divider, not a stamp per bubble.
- All bottom chrome is positioned inside the 9:16 crop, not the taller device
  canvas — otherwise the input bar and the newest bubble get cropped away.

## Notes

- **The lockscreen is the hook, but keep it SHORT.** `lock.preview` is the first
  thing anyone reads and it doubles as the thumbnail — make it the contradiction,
  not a greeting. The act is deliberately ~1.6s (banner lands ~0.5s, tap ~1.2s);
  every extra `--lock-seconds` becomes dead dwell on a screen nobody is touching,
  which is the fastest way to lose the first three seconds.
- **A real photo wallpaper beats the gradient.** Blurring a flat gradient for the
  banner material yields grey; a photo gives the banner something to refract.
- **Dark theme** (`"theme": "dark"`) suits an after-hours story; light is the
  default and reads better in-feed.
- Device geometry lives in `nis-daily-note/scripts/build_notes_meme.py`. Change
  it there and both reels follow.
