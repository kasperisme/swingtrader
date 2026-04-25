---
name: screen-agent
schedule: "*/15 * * * *"
timezone: UTC
---

Process all active scheduled stock screenings. Query Supabase for due
screenings, run each through the Ollama LLM agent with data query tools,
evaluate trigger conditions, generate alert summaries, and deliver
triggered results to users via Telegram. Non-triggered runs are persisted
for audit history.
