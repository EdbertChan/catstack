#!/bin/bash
# Single source of truth for "run every test suite in this repo." Discovers
# every directory containing Python test files instead of hand-listing them,
# while leaving Markdown-only skill trigger fixtures to their dedicated gate.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

status=0
while IFS= read -r dir; do
  echo "=== $dir ==="
  python3 -m unittest discover -s "$dir" -v || status=1
done < <(find . -type f -name 'test*.py' -not -path "./.worktrees/*" -not -path "*/__pycache__/*" -not -path "./node_modules/*" -exec dirname {} \; | sort -u)

exit "$status"
