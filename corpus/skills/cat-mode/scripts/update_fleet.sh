#!/bin/bash
# Put every machine on one Invoker release and the current catstack.
#
#   update_fleet.sh [--version <tag>] [--hosts <id,id>] [--skip-invoker]
#                   [--skip-catstack] [--with-app] [--dry-run]
#
# --version     release tag to install (default: newest daily-* release)
# --hosts       subset of remoteTargets ids (default: all of them)
# --with-app    also replace /Applications/Invoker.app on the Mac. This quits
#               a running Invoker, which is the live owner on that machine.
# --dry-run     resolve versions and print the table; change nothing.
#
# Every host gets one row. A row that could not be checked says so; it never
# reads as ok. Exit is non-zero if any row failed.
set -uo pipefail

REPO="${INVOKER_RELEASE_REPO:-Neko-Catpital-Labs/Invoker}"
CONFIG="${INVOKER_CONFIG:-$HOME/.invoker/config.json}"
APP_DIR="${INVOKER_APP_DIR:-/Applications}"
VERSION=""
HOSTS=""
DO_INVOKER=1
DO_CATSTACK=1
WITH_APP=0
DRY_RUN=0
WORK_DIR="$(mktemp -d)"
STATUS_ROWS=()
FAILED=0

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:?--version needs a tag}"; shift 2 ;;
    --hosts) HOSTS="${2:?--hosts needs a comma list}"; shift 2 ;;
    --skip-invoker) DO_INVOKER=0; shift ;;
    --skip-catstack) DO_CATSTACK=0; shift ;;
    --with-app) WITH_APP=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "fail    unknown argument: $1" >&2; exit 64 ;;
  esac
done

row() { STATUS_ROWS+=("$1"$'\t'"$2"$'\t'"$3"$'\t'"$4"); [ "$1" = "fail" ] && FAILED=1; return 0; }

need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "fail    missing required command: $1" >&2
  exit 1
}
need curl
need python3
need gh

if [ -z "$VERSION" ]; then
  VERSION="$(gh release list --repo "$REPO" --limit 20 2>/dev/null \
    | awk '$0 ~ /daily-/ {for (i=1;i<=NF;i++) if ($i ~ /^daily-[0-9]+$/) {print $i; exit}}')"
  if [ -z "$VERSION" ]; then
    echo "fail    could not resolve the newest daily-* release from $REPO" >&2
    exit 1
  fi
fi
echo "release $VERSION  (repo $REPO)"

RELEASE_VERSION="$(gh release view "$VERSION" --repo "$REPO" --json assets \
  -q '[.assets[].name | capture("invoker-cli-(?<v>[0-9][^-]*)-") .v] | first' 2>/dev/null)"
if [ -z "$RELEASE_VERSION" ]; then
  echo "fail    release $VERSION has no invoker-cli asset to read a version from" >&2
  exit 1
fi
echo "version $RELEASE_VERSION"

# Which SSH targets exist. Read the same config the owner reads, not a guess.
targets() {
  python3 - "$CONFIG" "$HOSTS" <<'PY'
import json, sys
path, wanted = sys.argv[1], sys.argv[2]
try:
    cfg = json.load(open(path))
except OSError as exc:
    sys.exit(f"cannot read {path}: {exc}")
except ValueError as exc:
    sys.exit(f"{path} is not valid JSON: {exc}")
keep = {h for h in wanted.split(",") if h} if wanted else None
for tid, t in (cfg.get("remoteTargets") or {}).items():
    if keep and tid not in keep:
        continue
    host, user = t.get("host"), t.get("user")
    if not host or not user:
        sys.exit(f"remoteTarget {tid} has no host/user")
    print(f"{tid}\t{user}\t{host}")
PY
}

TARGET_LIST="$(targets)" || { echo "fail    $TARGET_LIST" >&2; exit 1; }
if [ -z "$TARGET_LIST" ]; then
  echo "fail    no remoteTargets matched" >&2
  exit 1
fi

ssh_to() { ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$1" "${@:2}"; }

fetch_asset() {
  # fetch_asset <asset-name> -> path in WORK_DIR, checksum-verified
  local name="$1"
  gh release download "$VERSION" --repo "$REPO" -D "$WORK_DIR" -p "$name" -p 'SHA256SUMS' --clobber >/dev/null 2>&1 || return 1
  [ -f "$WORK_DIR/SHA256SUMS" ] || return 1
  local sumcmd
  if command -v shasum >/dev/null 2>&1; then sumcmd="shasum -a 256"; else sumcmd="sha256sum"; fi
  local want got
  want="$(awk -v n="$name" '$2 == n || $2 == "*"n {print $1}' "$WORK_DIR/SHA256SUMS" | head -1)"
  got="$($sumcmd "$WORK_DIR/$name" | awk '{print $1}')"
  if [ -z "$want" ] || [ "$want" != "$got" ]; then
    echo "fail    checksum mismatch for $name (want ${want:-<missing>}, got $got)" >&2
    return 1
  fi
  printf '%s' "$WORK_DIR/$name"
}

# ---------------------------------------------------------------- local Mac
local_invoker() {
  local before after arch asset tarball link
  before="$(invoker-cli --version 2>/dev/null || echo none)"
  if [ "$DRY_RUN" = 1 ]; then row ok local "invoker $before -> $RELEASE_VERSION (dry-run)" ""; return 0; fi
  case "$(uname -s)/$(uname -m)" in
    Darwin/arm64) arch="darwin-arm64" ;;
    Darwin/x86_64) arch="darwin-x64" ;;
    Linux/x86_64) arch="linux-x64" ;;
    Linux/aarch64) arch="linux-arm64" ;;
    *) row fail local "unsupported platform $(uname -s)/$(uname -m)" ""; return 1 ;;
  esac
  asset="invoker-cli-$RELEASE_VERSION-$arch.tar.gz"
  tarball="$(fetch_asset "$asset")" || { row fail local "could not fetch $asset" ""; return 1; }
  mkdir -p "$HOME/.invoker/cli"
  if ! tar -xzf "$tarball" -C "$HOME/.invoker/cli"; then
    row fail local "extract failed: $asset" ""; return 1
  fi
  link="$(command -v invoker-cli || true)"
  if [ -z "$link" ]; then
    mkdir -p "$HOME/.local/bin"; link="$HOME/.local/bin/invoker-cli"
  fi
  ln -sfn "$HOME/.invoker/cli/invoker-cli-$RELEASE_VERSION-$arch/invoker-cli" "$link"
  after="$("$link" --version 2>/dev/null || echo none)"
  if [ "$after" != "$RELEASE_VERSION" ]; then
    row fail local "invoker $before -> $after (wanted $RELEASE_VERSION)" "$link"; return 1
  fi
  row ok local "invoker $before -> $after" "$link"
}

restore_parked_app() {
  local backup="$1"
  [ -d "$backup" ] || return 0
  rm -rf "$APP_DIR/Invoker.app"
  mv "$backup" "$APP_DIR/Invoker.app"
}

local_app() {
  local dmg mount app before after backup
  [ "$(uname -s)" = "Darwin" ] || { row skip local "app: not macOS" ""; return 0; }
  before="$(defaults read "$APP_DIR/Invoker.app/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo none)"
  if [ "$DRY_RUN" = 1 ]; then row ok local "app $before -> $RELEASE_VERSION (dry-run)" ""; return 0; fi
  case "$(uname -m)" in
    arm64) dmg="Invoker-$RELEASE_VERSION-arm64.dmg" ;;
    *) dmg="Invoker-$RELEASE_VERSION-x64.dmg" ;;
  esac
  dmg="$(fetch_asset "$dmg")" || { row fail local "could not fetch $dmg" ""; return 1; }
  # This quits the live owner on this machine. Only reached behind --with-app.
  osascript -e 'tell application "Invoker" to quit' >/dev/null 2>&1
  mount="$WORK_DIR/mnt"; mkdir -p "$mount"
  if ! hdiutil attach "$dmg" -mountpoint "$mount" -nobrowse >/dev/null; then
    row fail local "could not mount $dmg" ""; return 1
  fi
  app="$(find "$mount" -maxdepth 1 -type d -name '*.app' | head -1)"
  if [ -z "$app" ]; then
    hdiutil detach "$mount" >/dev/null 2>&1
    row fail local "no .app inside $dmg" ""; return 1
  fi
  backup="$APP_DIR/Invoker.app.replacing.$$"
  if [ -d "$APP_DIR/Invoker.app" ] && ! mv "$APP_DIR/Invoker.app" "$backup"; then
    hdiutil detach "$mount" >/dev/null 2>&1
    row fail local "app: could not move $APP_DIR/Invoker.app aside; nothing replaced" ""; return 1
  fi
  if ! cp -R "$app" "$APP_DIR/"; then
    hdiutil detach "$mount" >/dev/null 2>&1
    rm -rf "$APP_DIR/Invoker.app"
    if ! restore_parked_app "$backup"; then
      row fail local "app: copy failed and the only bundle left is $backup" "$backup"; return 1
    fi
    row fail local "app $before unchanged: could not copy the new bundle into $APP_DIR" ""; return 1
  fi
  hdiutil detach "$mount" >/dev/null 2>&1
  after="$(defaults read "$APP_DIR/Invoker.app/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo unknown)"
  if [ "$after" != "$RELEASE_VERSION" ]; then
    rm -rf "$APP_DIR/Invoker.app"
    if ! restore_parked_app "$backup"; then
      row fail local "app $before -> $after (wanted $RELEASE_VERSION); the only bundle left is $backup" "$backup"; return 1
    fi
    row fail local "app $before unchanged: copied bundle read $after (wanted $RELEASE_VERSION)" ""; return 1
  fi
  rm -rf "$APP_DIR/Invoker.app.old"
  if [ -d "$backup" ]; then mv "$backup" "$APP_DIR/Invoker.app.old"; fi
  row ok local "app $before -> $after" "relaunch it to restore the owner"
}

# ------------------------------------------------------------------ remotes
# Remote work ships as a file and runs by path. A heredoc piped through ssh
# inside a command substitution gets re-parsed on the way, and the payload
# arrives truncated at the first metacharacter.
write_payloads() {
  cat > "$WORK_DIR/remote_invoker.sh" <<'PAYLOAD'
#!/bin/bash
# args: <asset-path> <version> <arch>
set -uo pipefail
ASSET="$1"; VER="$2"; ARCH="$3"
case "$ARCH" in
  x86_64) A=linux-x64 ;;
  aarch64|arm64) A=linux-arm64 ;;
  *) echo "UNKNOWN_ARCH=$ARCH"; exit 1 ;;
esac
DIR="$HOME/.local/opt/invoker-cli-$VER-$A"
mkdir -p "$HOME/.local/opt" "$HOME/.local/bin"
rm -rf "$DIR"
if ! tar -xzf "$ASSET" -C "$HOME/.local/opt"; then
  echo "EXTRACT_FAILED=$ASSET"
  exit 1
fi
chmod +x "$DIR/invoker-cli"
ln -sfn "$DIR/invoker-cli" "$HOME/.local/bin/invoker-cli"
# Prefer the system path so every PATH resolves the new build; fall back to
# ~/.local/bin, which a non-interactive ssh shell only sees via .bashrc.
if sudo -n true 2>/dev/null; then
  sudo ln -sfn "$DIR/invoker-cli" /usr/bin/invoker-cli
else
  MARK='# invoker-cli local bin'
  if ! grep -qF "$MARK" "$HOME/.bashrc" 2>/dev/null; then
    printf '%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$MARK" > "$HOME/.bashrc.new"
    cat "$HOME/.bashrc" >> "$HOME/.bashrc.new" 2>/dev/null
    mv "$HOME/.bashrc.new" "$HOME/.bashrc"
  fi
fi
rm -f "$ASSET"
echo "VERSION=$("$DIR/invoker-cli" --version 2>/dev/null || echo none)"
PAYLOAD

  cat > "$WORK_DIR/remote_catstack.sh" <<'PAYLOAD'
#!/bin/bash
# No args. Resolves the live checkout, updates it, installs.
set -uo pipefail
# More than one checkout can exist. The live one is whichever the installed
# skill symlinks point into, never the first hit of a directory listing.
live=""
for s in "$HOME"/.claude/skills/*; do
  [ -L "$s" ] || continue
  t="$(readlink "$s")"
  case "$t" in
    */corpus/skills/*) live="${t%%/corpus/skills/*}"; break ;;
    */product/skills/*) live="${t%%/product/skills/*}"; break ;;
    */engine/skills/*) live="${t%%/engine/skills/*}"; break ;;
  esac
done
if [ -z "$live" ]; then
  live="$(ls -d "$HOME/catstack" "$HOME/Documents/GitHub/catstack" 2>/dev/null | head -1)"
fi
if [ -z "$live" ] || [ ! -d "$live" ]; then
  echo "NO_CHECKOUT"
  exit 1
fi
echo "DIR=$live"
cd "$live" || { echo "CANNOT_CD=$live"; exit 1; }
echo "BEFORE=$(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "DIRTY=1"
else
  git fetch origin --quiet || { echo "FETCH_FAILED"; exit 1; }
  git pull --ff-only origin main --quiet || { echo "PULL_FAILED"; exit 1; }
fi
echo "AFTER=$(git rev-parse --short HEAD)"
# install.sh reads stdin; without </dev/null it swallows whatever feeds this script.
./install.sh > /tmp/catstack-install.log 2>&1 </dev/null
echo "INSTALL_EXIT=$?"
PAYLOAD
  chmod +x "$WORK_DIR/remote_invoker.sh" "$WORK_DIR/remote_catstack.sh"
}

remote_invoker() {
  local id="$1" dest="$2" asset tarball out before arch after
  before="$(ssh_to "$dest" 'invoker-cli --version 2>/dev/null || echo none' </dev/null 2>/dev/null || echo unreachable)"
  if [ -z "$before" ] || [ "$before" = "unreachable" ]; then
    row fail "$id" "ssh failed; version unchecked" ""; return 1
  fi
  if [ "$DRY_RUN" = 1 ]; then row ok "$id" "invoker $before -> $RELEASE_VERSION (dry-run)" ""; return 0; fi
  arch="$(ssh_to "$dest" 'uname -m' </dev/null 2>/dev/null)"
  case "$arch" in
    x86_64) asset="invoker-cli-$RELEASE_VERSION-linux-x64.tar.gz" ;;
    aarch64|arm64) asset="invoker-cli-$RELEASE_VERSION-linux-arm64.tar.gz" ;;
    *) row fail "$id" "unknown remote arch: ${arch:-unreadable}" ""; return 1 ;;
  esac
  tarball="$(fetch_asset "$asset")" || { row fail "$id" "could not fetch $asset" ""; return 1; }
  if ! scp -q -o BatchMode=yes -o ConnectTimeout=10 "$tarball" "$WORK_DIR/remote_invoker.sh" "$dest:/tmp/" </dev/null; then
    row fail "$id" "scp failed: $asset" ""; return 1
  fi
  out="$(ssh_to "$dest" "bash /tmp/remote_invoker.sh /tmp/$asset $RELEASE_VERSION $arch" </dev/null 2>&1)"
  after="$(printf '%s' "$out" | sed -n 's/^VERSION=//p')"
  if [ "$after" != "$RELEASE_VERSION" ]; then
    row fail "$id" "invoker $before -> ${after:-unreadable} (wanted $RELEASE_VERSION): ${out##*$'\n'}" ""; return 1
  fi
  row ok "$id" "invoker $before -> $after" ""
}

catstack_on() {
  local id="$1" dest="$2" out dir before after exit_code dirty
  if [ "$DRY_RUN" = 1 ]; then row ok "$id" "catstack: would pull+install" ""; return 0; fi
  if [ "$dest" = "local" ]; then
    out="$(bash "$WORK_DIR/remote_catstack.sh" 2>&1)"
  else
    if ! scp -q -o BatchMode=yes -o ConnectTimeout=10 "$WORK_DIR/remote_catstack.sh" "$dest:/tmp/" </dev/null; then
      row fail "$id" "catstack: scp of the update script failed" ""; return 1
    fi
    out="$(ssh_to "$dest" "bash /tmp/remote_catstack.sh" </dev/null 2>&1)"
  fi
  dir="$(printf '%s' "$out" | sed -n 's/^DIR=//p')"
  before="$(printf '%s' "$out" | sed -n 's/^BEFORE=//p')"
  after="$(printf '%s' "$out" | sed -n 's/^AFTER=//p')"
  exit_code="$(printf '%s' "$out" | sed -n 's/^INSTALL_EXIT=//p')"
  dirty="$(printf '%s' "$out" | sed -n 's/^DIRTY=//p')"
  if [ -z "$dir" ]; then
    row fail "$id" "catstack: no checkout found (${out##*$'\n'})" ""; return 1
  fi
  if [ -z "$exit_code" ]; then
    row fail "$id" "catstack: install did not report an exit code (${out##*$'\n'})" "$dir"; return 1
  fi
  if [ "$exit_code" != "0" ]; then
    row fail "$id" "catstack: install.sh exit $exit_code (see /tmp/catstack-install.log)" "$dir"; return 1
  fi
  if [ -n "$dirty" ]; then
    row warn "$id" "catstack: local edits, left at $before (install ok)" "$dir"; return 0
  fi
  row ok "$id" "catstack $before -> $after" "$dir"
}

write_payloads

[ "$DO_INVOKER" = 1 ] && local_invoker
[ "$DO_INVOKER" = 1 ] && [ "$WITH_APP" = 1 ] && local_app
[ "$DO_CATSTACK" = 1 ] && catstack_on local local

while IFS=$'\t' read -r id user host; do
  [ -n "$id" ] || continue
  [ "$DO_INVOKER" = 1 ] && remote_invoker "$id" "$user@$host"
  [ "$DO_CATSTACK" = 1 ] && catstack_on "$id" "$user@$host"
done <<< "$TARGET_LIST"

printf '\n%-6s  %-26s  %s\n' STATUS HOST DETAIL
for r in "${STATUS_ROWS[@]}"; do
  IFS=$'\t' read -r s h d p <<< "$r"
  printf '%-6s  %-26s  %s%s\n' "$s" "$h" "$d" "${p:+  [$p]}"
done

exit "$FAILED"
