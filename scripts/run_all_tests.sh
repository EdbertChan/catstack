#!/bin/bash
# Single source of truth for "run every test suite in this repo." Discovers
# every directory containing Python test files instead of hand-listing them,
# while leaving Markdown-only skill trigger fixtures to their dedicated gate.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

node_toolchain_state() {
  python3 - "$REPO_DIR" <<'PY'
import json
import os
import sys

root = sys.argv[1]
manifest_path = os.path.join(root, "package.json")
if not os.path.exists(manifest_path):
    print("absent")
    raise SystemExit(0)
try:
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    required = [
        name
        for section in ("dependencies", "devDependencies")
        for name in manifest.get(section, {})
    ]
except (OSError, ValueError, AttributeError) as exc:
    print(f"unreadable {exc}")
    raise SystemExit(0)
missing = [
    name
    for name in required
    if not os.path.exists(os.path.join(root, "node_modules", name, "package.json"))
]
print("missing " + " ".join(missing) if missing else "ready")
PY
}

ensure_node_toolchain() {
  local state
  if ! state="$(node_toolchain_state)"; then
    echo "unchecked: could not inspect the Node toolchain, so a dependency error would stand in for a verdict" >&2
    return 1
  fi
  case "$state" in
    absent|ready)
      return 0
      ;;
    unreadable*)
      echo "unchecked: package.json is unreadable (${state#unreadable }), so the Node-backed tests cannot be trusted" >&2
      return 1
      ;;
  esac

  echo "=== node toolchain: installing${state#missing} ==="
  if ! command -v npm >/dev/null 2>&1; then
    echo "unchecked: npm is not on PATH, so${state#missing} cannot be installed and the Node-backed tests cannot run" >&2
    return 1
  fi

  local installer
  if [[ -f package-lock.json ]]; then
    installer=(npm ci)
  else
    installer=(npm install)
  fi
  if ! "${installer[@]}"; then
    echo "unchecked: ${installer[*]} failed, so the Node-backed tests cannot run" >&2
    return 1
  fi
  if ! state="$(node_toolchain_state)" || [[ "$state" != ready ]]; then
    echo "unchecked: ${installer[*]} finished but the toolchain is still not ready ($state)" >&2
    return 1
  fi
}

if ! ensure_node_toolchain; then
  exit 1
fi

status=0
while IFS= read -r dir; do
  echo "=== $dir ==="
  python3 -m unittest discover -s "$dir" -v || status=1
done < <(find . -type f -name 'test*.py' -not -path "./.worktrees/*" -not -path "*/__pycache__/*" -not -path "./node_modules/*" -exec dirname {} \; | sort -u)

exit "$status"
