#!/bin/bash
# Single source of truth for "run every test suite in this repo." Discovers
# every directory containing Python test files instead of hand-listing them,
# while leaving Markdown-only skill trigger fixtures to their dedicated gate.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

NODE_DEP_DIR="node_modules/@neko-catpital-labs/drafter-core"
if [ ! -d "$NODE_DEP_DIR" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "run_all_tests: npm is required for the draft-pr node suites and is not installed" >&2
    exit 1
  fi
  echo "=== installing node toolchain (npm ci) ==="
  if ! npm ci; then
    echo "run_all_tests: npm ci failed; refusing to report a pass on a partial suite" >&2
    exit 1
  fi
fi

status=0
while IFS= read -r dir; do
  echo "=== $dir ==="
  python3 -m unittest discover -s "$dir" -v || status=1
done < <(find . -type f -name 'test*.py' -not -path "./.worktrees/*" -not -path "*/__pycache__/*" -not -path "./node_modules/*" -exec dirname {} \; | sort -u)

exit "$status"
