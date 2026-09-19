#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Safely load environment variables without eval/source syntax issues
load_env_file() {
  local env_file="$1"
  if [ -f "$env_file" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      # Strip carriage return and leading/trailing whitespace
      line="$(echo "$line" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
      # Skip comments and empty lines
      if [[ "$line" =~ ^# ]] || [[ -z "$line" ]]; then
        continue
      fi
      # Only export lines with KEY=VALUE
      if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
        key="${line%%=*}"
        val="${line#*=}"
        # Strip surrounding quotes if present
        val="${val#\"}"
        val="${val%\"}"
        val="${val#\'}"
        val="${val%\'}"
        if [ -z "${!key}" ]; then
          export "$key"="$val"
        fi
      fi
    done < "$env_file"
  fi
}

load_env_file ".env"
load_env_file "../Notoma/.env"

exec python3 -m notion_better_export.cli "$@"
