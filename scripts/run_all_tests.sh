#!/bin/bash
# Single source of truth for "run every test suite in this repo." Discovers
# every directory containing Python test files instead of hand-listing them,
# while leaving Markdown-only skill trigger fixtures to their dedicated gate.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

missing_node_deps() {
  python3 - <<'PY'
import json
import os
import sys

try:
    with open("package.json", encoding="utf-8") as handle:
        package = json.load(handle)
except (OSError, ValueError) as exc:
    print(f"package.json is unreadable: {exc}", file=sys.stderr)
    sys.exit(2)

names = []
for field in ("dependencies", "devDependencies"):
    names.extend(package.get(field) or {})

for name in names:
    if not os.path.isdir(os.path.join("node_modules", *name.split("/"))):
        print(name)
PY
}

ensure_node_deps() {
  if [ ! -f package.json ]; then
    return 0
  fi

  local missing
  missing="$(missing_node_deps)"
  if [ -z "$missing" ]; then
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "run_all_tests: the Node-backed suites need these packages, which are not installed:" >&2
    echo "$missing" | sed 's/^/  - /' >&2
    echo "run_all_tests: npm is not on PATH, so they cannot be installed here." >&2
    echo "run_all_tests: refusing to run half-equipped -- those suites would report" >&2
    echo "run_all_tests: module-resolution errors as test failures. Install Node and rerun." >&2
    return 1
  fi

  echo "=== installing Node dependencies for the Node-backed suites ==="
  if [ -f package-lock.json ]; then
    npm ci >&2
  else
    npm install >&2
  fi

  missing="$(missing_node_deps)"
  if [ -n "$missing" ]; then
    echo "run_all_tests: npm finished but these packages are still absent:" >&2
    echo "$missing" | sed 's/^/  - /' >&2
    return 1
  fi
}

ensure_node_deps

status=0
while IFS= read -r dir; do
  echo "=== $dir ==="
  python3 -m unittest discover -s "$dir" -v || status=1
done < <(find . -type f -name 'test*.py' -not -path "./.worktrees/*" -not -path "*/__pycache__/*" -not -path "./node_modules/*" -exec dirname {} \; | sort -u)

exit "$status"
