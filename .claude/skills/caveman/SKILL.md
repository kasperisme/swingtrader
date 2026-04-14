---
name: caveman
description: "Ultra-compressed content writing style reducing word count ~75% while keeping technical accuracy exact. Use when writing cavemanBody fields in Sanity blog posts and documentation pages. Drops articles, filler, hedging. Fragments OK. Pattern: [thing] [action] [reason]. [next step]."
triggers:
  - "caveman mode"
  - "caveman version"
  - "write caveman"
  - "cavemanBody"
  - "less words"
  - "/caveman"
  - "write blog post"
  - "write doc"
  - "write documentation"
---

# Caveman Skill

Write compressed content. Less word. More understand.

## Core Rules

Drop all of these:
- Articles: a / an / the
- Filler: just, really, basically, actually, simply, essentially, generally
- Hedging: might, could, perhaps, it seems, it appears, arguably
- Pleasantries: note that, keep in mind, it's worth mentioning, feel free to
- Weak openers: "In this post we'll explore...", "Welcome to...", "This guide covers..."

Keep all of these:
- Technical terms (exact, unchanged)
- Code blocks (verbatim, never compress code)
- Numbers and data
- Product/feature names

## Pattern

```
[thing] [action] [reason]. [next step].
```

Bad: "In order to get started with the screener, you'll first need to make sure that you have created an account and logged in."
Good: "Sign in first. Screener needs auth."

Bad: "The news impact score is calculated based on several factors including sentiment, volume, and relevance to the asset."
Good: "News impact score = sentiment + volume + asset relevance."

## Intensity Levels

**lite** — Drop filler/hedging, keep articles, keep full sentences. Use for shorter docs.

**full** (default) — Drop articles and filler, allow fragments, use short synonyms. Use for most blog posts.

**ultra** — Abbreviate terms (config/auth/API), strip conjunctions, use arrows for causality (X → Y). Use only when explicitly requested.

## Content Writing Rules

When writing `cavemanBody` for Sanity:

1. Take the full `body` content as source
2. Apply caveman compression to all prose
3. Keep headings short (2–4 words max)
4. Lists: one fragment per bullet, no punctuation at end
5. Code examples: unchanged
6. Numbers/statistics: always keep
7. Links and CTAs: keep but shorten text ("Read more →" not "Click here to read more about this topic")

### Heading compression
Bad: "How to Get Started with the News Impact Screener"
Good: "Getting Started"

Bad: "Understanding How Sentiment Scores Are Calculated"  
Good: "Sentiment Score Math"

### Intro compression
Bad: "In this post, we're going to take a deep dive into how the News Impact Screener works and why it can be a powerful tool for retail investors who are looking to stay ahead of the market."
Good: "News Impact Screener. Connects headlines to stocks. Retail investors. No terminal needed."

### Body compression
Bad: "When a news event occurs, our system analyzes the article using a large language model to extract the key themes, the sentiment, and the potential impact on related assets."
Good: "News event hits. LLM extracts: themes, sentiment, asset impact."

## When Writing Blog Posts

Always produce two outputs:

**Normal body** (`body` field):
- Full prose, complete sentences
- SEO-friendly headings
- Conversational but professional tone

**Caveman body** (`cavemanBody` field):
- Apply full-intensity caveman rules to all prose from the normal body
- Same structure, headings, and code — just compressed
- Target: ~70% shorter than normal body

## When Writing Documentation

Always produce two outputs:

**Normal body** (`body` field):
- Complete explanations with context
- Step-by-step format where relevant
- Examples with explanation

**Caveman body** (`cavemanBody` field):
- Steps only, no explanation of why unless critical
- "Do X. See Y. Fix with Z." format
- Numbered steps stay numbered, but text compressed
- Remove all background/context paragraphs

## Sanity Schema Reference

Both fields use `blockContent` (Portable Text). When outputting content for Sanity:
- Headings → appropriate heading level (h2/h3/h4)
- Paragraphs → normal blocks
- Code → code blocks (language specified)
- Lists → bullet or numbered arrays
- `cavemanBody` follows same structure as `body` but with compressed text nodes
