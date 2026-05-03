#!/usr/bin/env bash
#
# Pre-commit guard for the RAG layer.
#
# Runs the unit + integration tests when any file that could affect the RAG
# layer or its consumers is staged. Skips silently for unrelated commits
# (e.g. UI-only changes) so the hook stays fast.
#
# Wire-up:
#   ln -sf ../../code/analytics/scripts/precommit_rag_tests.sh \
#          .git/hooks/pre-commit
#

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
ANALYTICS_DIR="$REPO_ROOT/code/analytics"
PYTHON_BIN="$ANALYTICS_DIR/.venv/bin/python"

# Paths whose changes should trigger the RAG test suite.
WATCH_PATTERN='^code/analytics/(services/(rag|agent|video|news/narrative|news/scoring)/|shared/llm/|tests/(test_rag_|test_.*_integration\.py))'

staged="$(git diff --cached --name-only --diff-filter=ACMR)"
if [[ -z "$staged" ]] || ! grep -qE "$WATCH_PATTERN" <<< "$staged"; then
  exit 0
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "pre-commit: $PYTHON_BIN not found — skipping RAG tests" >&2
  exit 0
fi

echo "pre-commit: running RAG test suite..."
cd "$ANALYTICS_DIR"
"$PYTHON_BIN" -m pytest \
  tests/test_rag_taxonomy.py \
  tests/test_rag_graph.py \
  tests/test_rag_sentiment.py \
  tests/test_rag_screening.py \
  tests/test_rag_tools.py \
  tests/test_agent_rag_integration.py \
  tests/test_video_rag_integration.py \
  tests/test_narrative_rag_integration.py \
  tests/test_impact_scorer_llm_integration.py \
  --quiet --no-header
