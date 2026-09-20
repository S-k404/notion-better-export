#!/usr/bin/env bash
# Convenience launcher: ./run.sh [auto|export|fix|init|test] [flags]
# The CLI reads NOTION_TOKEN from the environment, ./.env, or `nbe init` on its own,
# so this script never parses or exports secrets.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v uv >/dev/null 2>&1; then
  exec uv run python -m notion_better_export.cli "$@"
elif [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m notion_better_export.cli "$@"
else
  exec python3 -m notion_better_export.cli "$@"
fi
