#!/usr/bin/env bash

set -euo pipefail

TOOL_NAME="${TOOL_NAME:-}"
FILE_PATH="${FILE_PATH:-}"
LOG_FILE="${HOME}/.claude/logs/read-guard-blocks.jsonl"

[[ "$TOOL_NAME" != "Read" ]] && exit 0

if [[ -z "$FILE_PATH" ]]; then
  echo "Read path is empty" >&2
  exit 1
fi

if [[ "$FILE_PATH" =~ ^~/ ]]; then
  FILE_PATH="${HOME}/${FILE_PATH#\~/}"
fi

if [[ ! -e "$FILE_PATH" ]]; then
  mkdir -p "$(dirname "$LOG_FILE")"
  jq -nc --arg path "$FILE_PATH" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{path: $path, timestamp: $ts, reason: "not_found"}' >> "$LOG_FILE"

  DIR=$(dirname "$FILE_PATH")
  BASE=$(basename "$FILE_PATH")

  echo "Read blocked: $FILE_PATH does not exist" >&2

  if [[ -d "$DIR" ]]; then
    echo "Directory exists. Similar files:" >&2
    find "$DIR" -maxdepth 1 -type f -name "*${BASE:0:3}*" 2>/dev/null | head -5 || true
  else
    echo "Parent directory does not exist: $DIR" >&2
  fi

  exit 1
fi

exit 0
