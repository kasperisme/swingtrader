#!/usr/bin/env bash
# run_arena.sh — the arena's nightly job, for the Mac Mini crontab.
#
#   fill (yesterday's orders at today's open) -> mark (to today's close)
#   -> decide (each agent places orders for the next session)
#
# Usage: run_arena.sh [--force]
#
# WHY A WRAPPER AND NOT `cli.py run-day` DIRECTLY. `run_decide` has no guard
# against deciding a session twice: it runs every agent unconditionally for
# whatever session it is handed, and `place_order` INSERTS. So a second run on
# the same session places a SECOND set of orders on top of the first. Two ways
# that happens by accident:
#
#   * A market holiday. `run-day` takes its session from the last PRINTED
#     close, so on Thanksgiving it re-runs Wednesday — re-deciding a day that
#     has already traded.
#   * An overrun. A roster pass is 10-20 minutes, but a stalled Ollama backend
#     has taken far longer, and the next trigger would start mid-write.
#
# Both are SKIPS, not failures: exit 0 with a line in the log. A cron that
# emails on every market holiday gets muted, and a muted cron is not a cron.
# A genuinely missed night is caught by the watchdog instead — `--heartbeat`
# registers the run in `job_health`, which scripts/watchdog.py polls.

set -euo pipefail

ANALYTICS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="$ANALYTICS_DIR/output/.arena_run.lock"
mkdir -p "$ANALYTICS_DIR/output"

FORCE="${1:-}"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] arena: $*"; }

# Pinned here as well as in code. gemma4:31b-cloud is the hard default in
# decide.py, but if this machine's profile ever exports ARENA_MODEL for
# something else the roster would silently split across two models — which is
# the one thing this competition cannot survive. See _MODEL_ENV in decide.py.
export ARENA_MODEL="${ARENA_MODEL_OVERRIDE:-gemma4:31b-cloud}"

PYTHON="$ANALYTICS_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$ANALYTICS_DIR/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3"
cd "$ANALYTICS_DIR"

# ── Guard 1: weekends ───────────────────────────────────────────────────────
if [ "$(date +%u)" -ge 6 ] && [ "$FORCE" != "--force" ]; then
    log "weekend — nothing to do."
    exit 0
fi

# ── Guard 2: one run at a time ──────────────────────────────────────────────
# mkdir is atomic; macOS has no flock.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    OWNER="$(cat "$LOCK_DIR/pid" 2>/dev/null || echo unknown)"
    if [ "$OWNER" != "unknown" ] && ! kill -0 "$OWNER" 2>/dev/null; then
        log "stale lock from dead pid $OWNER — reclaiming."
        rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR"
    else
        log "another run is in progress (pid $OWNER) — skipping."
        exit 0
    fi
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

# ── Guard 3: a session actually closed today ────────────────────────────────
# Asks the same price feed run-day uses, so a holiday, a half-day with no
# printed bar, and a stalled feed all give the same answer: not today, skip.
# This also absorbs the DST drift between Copenhagen and New York — for the two
# weeks a year when the offset is an hour off, an early trigger simply skips.
SESSION="$(PYTHONPATH=. "$PYTHON" - <<'PY' 2>/dev/null || true
from services.arena.scheduler import last_closed_session
s = last_closed_session()
print(s.isoformat() if s else "")
PY
)"
TODAY="$(date +%F)"
if [ "$FORCE" != "--force" ]; then
    if [ -z "$SESSION" ]; then
        log "could not determine the last closed session (price feed down?) — skipping."
        exit 0
    fi
    if [ "$SESSION" != "$TODAY" ]; then
        log "last closed session is $SESSION, not $TODAY (holiday, or bars not printed yet) — skipping."
        exit 0
    fi
fi

# ── The run ─────────────────────────────────────────────────────────────────
log "run-day for session $SESSION (model $ARENA_MODEL)"
PYTHONPATH=. "$PYTHON" -u -m services.arena.cli run-day --heartbeat
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
    log "run-day FAILED with exit $STATUS"
    exit "$STATUS"
fi

PYTHONPATH=. "$PYTHON" -m services.arena.cli standings
log "done."
