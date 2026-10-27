#!/bin/bash
set -uo pipefail

self="${BASH_SOURCE[0]}"
if [[ -L $self ]]; then
  self="$(realpath "$self")" || {
    echo "cannot follow the link at ${BASH_SOURCE[0]} to find the repo: realpath is not on PATH" >&2
    exit 1
  }
fi
REPO_DIR="$(cd "$(dirname "$self")/../.." && pwd)"
SHIM_SOURCE="$REPO_DIR/scripts/test/plutil_lint.py"

if [ "$(uname -s)" = "Darwin" ]; then
  echo "ok      macOS ships plutil; no shim needed"
  exit 0
fi

if command -v plutil >/dev/null 2>&1; then
  echo "ok      plutil already on PATH ($(command -v plutil))"
  exit 0
fi

if [ ! -f "$SHIM_SOURCE" ]; then
  echo "fail    $SHIM_SOURCE is missing; plist lint proofs cannot run on a host without plutil" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "fail    python3 not found; the plutil shim cannot run and plist lint proofs cannot run" >&2
  exit 1
fi

target_dir="${CATSTACK_PLUTIL_BIN_DIR:-}"
if [ -z "$target_dir" ]; then
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    if [ -d "$candidate" ] && [ -w "$candidate" ]; then
      target_dir="$candidate"
      if [ "$candidate" = "${HOME:-}/.local/bin" ]; then
        break
      fi
    fi
  done < <(printf '%s\n' "$PATH" | tr ':' '\n')
fi

if [ -z "$target_dir" ]; then
  echo "fail    no writable directory on PATH to install the plutil shim into; add \$HOME/.local/bin to PATH or set CATSTACK_PLUTIL_BIN_DIR" >&2
  exit 1
fi

if ! mkdir -p "$target_dir"; then
  echo "fail    cannot create $target_dir to hold the plutil shim" >&2
  exit 1
fi

if ! cp "$SHIM_SOURCE" "$target_dir/plutil"; then
  echo "fail    cannot write $target_dir/plutil; plist lint proofs cannot run" >&2
  exit 1
fi

if ! chmod +x "$target_dir/plutil"; then
  echo "fail    cannot make $target_dir/plutil executable; plist lint proofs cannot run" >&2
  exit 1
fi

echo "ok      plutil shim installed at $target_dir/plutil"
