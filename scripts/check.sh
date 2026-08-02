#!/usr/bin/env bash
# Full validation suite: format, lint, typecheck, tests.
# Run this before every commit/push (see AGENTS.md); CI runs it too. Usage: scripts/check.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "==> ruff format --check"
uv run ruff format --check .

echo "==> ruff check"
uv run ruff check .

echo "==> ty check"
uv run ty check

echo "==> pytest"
uv run pytest

echo "All checks passed."
