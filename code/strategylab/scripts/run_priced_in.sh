#!/usr/bin/env bash
# run_priced_in.sh — shell wrapper for the macOS crontab (Mac Mini).
#
# Drives the priced-in programme unattended over the NYSE + NASDAQ universe.
# Three modes, on three cadences, because the three jobs cost wildly different
# amounts and answer to different clocks.
#
#   resolve  (daily, ~seconds)
#       Settle every Tier-3 prediction that has come due, and report the score
#       against its base rate. No LLM: the resolvers are arithmetic over FMP and
#       Wikimedia, and the database refuses a second resolution, so a repeated
#       run is safe by construction. This is the cheapest and most valuable of
#       the three — the forward record only accrues if something resolves it.
#
#   batch    (nightly, hours)
#       One bounded pass over the queue: reconstruct, persist, and promote a row
#       only when it is valid AND something it is about moved. Resumable — every
#       completed name is marked in Supabase before the next one starts, so a
#       pass killed at 3am costs nothing but the ticker in flight.
#
#   universe (weekly, ~minutes)
#       Refresh size and coverage from Supabase, then spend a bounded number of
#       FMP calls re-checking analyst coverage on names whose verdict is stale.
#
# Sizing the nightly pass: ~725 names are eligible and a reconstruction takes
# ~110s on glm-5.1:cloud, so a 7-day refresh cycle needs ~105 names a night,
# about three hours. PRICED_IN_LIMIT and PRICED_IN_MAX_SECONDS are the two knobs;
# the time budget is a ceiling, not a target, and a pass that hits it simply
# resumes tomorrow where it stopped.
#
# Add to crontab (crontab -e), using the real absolute path to this repo:
#
#   # settle due predictions, 06:10 daily
#   10 6 * * *  /Users/<you>/projects/swingtrader/code/strategylab/scripts/run_priced_in.sh resolve  >> /Users/<you>/projects/swingtrader/logs/priced-in.log 2>&1
#   # one reconstruction pass, 22:00 daily
#   0 22 * * *  /Users/<you>/projects/swingtrader/code/strategylab/scripts/run_priced_in.sh batch    >> /Users/<you>/projects/swingtrader/logs/priced-in.log 2>&1
#   # refresh the universe, 04:00 Sunday
#   0 4 * * 0   /Users/<you>/projects/swingtrader/code/strategylab/scripts/run_priced_in.sh universe >> /Users/<you>/projects/swingtrader/logs/priced-in.log 2>&1
#
# Env: loaded from code/strategylab/.env (falling back to code/analytics/.env).
#   STRATEGYLAB_LLM_BACKEND=ollama        route the pipeline through Ollama
#   STRATEGYLAB_OLLAMA_MODELS=glm-5.1:cloud
#   OLLAMA_URL                            default http://localhost:11434
#   PRICED_IN_LIMIT                       names per nightly pass (default 105)
#   PRICED_IN_DUE_DAYS                    refresh cycle in days (default 7)
#   PRICED_IN_MAX_SECONDS                 wall-clock ceiling (default 21600 = 6h)
#   PRICED_IN_CHECK_LIMIT                 FMP eligibility calls/week (default 300)
#
# NOTE: `batch` promotes rows to the PUBLIC quote pages when the gate passes.
# Run it once by hand with --dry-run, and once with --no-publish, before the
# first scheduled pass.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${LAB_DIR}/.venv/bin/python"

if [[ ! -f "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

cd "$LAB_DIR"

MODE="${1:-batch}"
LIMIT="${PRICED_IN_LIMIT:-105}"
DUE_DAYS="${PRICED_IN_DUE_DAYS:-7}"
MAX_SECONDS="${PRICED_IN_MAX_SECONDS:-21600}"
CHECK_LIMIT="${PRICED_IN_CHECK_LIMIT:-300}"

echo "=== priced-in ${MODE} $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

case "$MODE" in
  resolve)
    "$VENV_PYTHON" -m strategylab.social.cli predict resolve
    "$VENV_PYTHON" -m strategylab.social.cli predict status
    ;;
  batch)
    "$VENV_PYTHON" -m strategylab.social.cli batch \
      --limit "$LIMIT" --due-days "$DUE_DAYS" --max-seconds "$MAX_SECONDS"
    ;;
  universe)
    "$VENV_PYTHON" -m strategylab.social.cli universe seed
    "$VENV_PYTHON" -m strategylab.social.cli universe check --limit "$CHECK_LIMIT"
    ;;
  *)
    echo "usage: $(basename "$0") {resolve|batch|universe}" >&2
    exit 2
    ;;
esac
