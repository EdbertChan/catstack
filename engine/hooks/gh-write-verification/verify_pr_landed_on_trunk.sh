#!/usr/bin/env bash
set -euo pipefail

EXIT_OK=0
EXIT_FAIL=1
EXIT_UNCHECKED=3
EXIT_USAGE=64

usage() {
  echo "usage: verify_pr_landed_on_trunk.sh [--repo <owner/name>] <pr-number | pr-url> [trunk-branch]" >&2
  echo "  asserts the PR's merge commit is an ancestor of origin/<trunk-branch> (default: main)" >&2
  echo "  exit ${EXIT_OK}  OK         the merge commit is on origin/<trunk-branch>" >&2
  echo "  exit ${EXIT_FAIL}  FAIL       the PR merged, but not onto origin/<trunk-branch>" >&2
  echo "  exit ${EXIT_UNCHECKED}  UNCHECKED  the check could not run; nothing is proven" >&2
  echo "  exit ${EXIT_USAGE} usage error" >&2
  exit "$EXIT_USAGE"
}

unchecked() {
  echo "UNCHECKED: $*" >&2
  exit "$EXIT_UNCHECKED"
}

trap 'unchecked "unexpected failure at line ${LINENO}"' ERR

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

SLUG_RE='^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$'
PR_URL_RE='^https?://(www\.)?github\.com/([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)/pull/([0-9]+)([/?#].*)?$'
REMOTE_RE='^(https?://([^@/]+@)?github\.com/|ssh://git@github\.com(:[0-9]+)?/|git@github\.com:)([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)$'

origin_slug() {
  local url
  url="$(git config --get remote.origin.url)" || return 1
  url="${url%/}"
  url="${url%.git}"
  [[ "$url" =~ $REMOTE_RE ]] || return 1
  printf '%s' "${BASH_REMATCH[4]}"
}

REPO_FLAG=""
TARGET=""
TRUNK=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      [ "$#" -ge 2 ] || usage
      REPO_FLAG="$2"
      shift 2
      ;;
    --repo=*)
      REPO_FLAG="${1#--repo=}"
      shift
      ;;
    -*)
      usage
      ;;
    *)
      if [ -z "$TARGET" ]; then
        TARGET="$1"
      elif [ -z "$TRUNK" ]; then
        TRUNK="$1"
      else
        usage
      fi
      shift
      ;;
  esac
done

[ -n "$TARGET" ] || usage
TRUNK="${TRUNK:-main}"
if [ -n "$REPO_FLAG" ] && ! [[ "$REPO_FLAG" =~ $SLUG_RE ]]; then
  usage
fi

URL_SLUG=""
if [[ "$TARGET" =~ $PR_URL_RE ]]; then
  URL_SLUG="${BASH_REMATCH[2]}"
  PR_NUMBER="${BASH_REMATCH[3]}"
elif [[ "$TARGET" =~ ^[0-9]+$ ]]; then
  PR_NUMBER="$TARGET"
else
  usage
fi

if [ -n "$REPO_FLAG" ] && [ -n "$URL_SLUG" ] && [ "$(lower "$REPO_FLAG")" != "$(lower "$URL_SLUG")" ]; then
  unchecked "ambiguous repo: --repo names ${REPO_FLAG} but the PR URL names ${URL_SLUG}"
fi

command -v gh >/dev/null 2>&1 || unchecked "gh is not installed or not on PATH"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  unchecked "$(pwd) is not a git checkout; the ancestry check needs a clone of the PR's repo"
fi

if ! ORIGIN_SLUG="$(origin_slug)"; then
  unchecked "cannot read a GitHub owner/name from this checkout's origin remote"
fi

if [ -n "$REPO_FLAG" ] || [ -n "$URL_SLUG" ]; then
  SLUG="${REPO_FLAG:-$URL_SLUG}"
  if [ "$(lower "$SLUG")" != "$(lower "$ORIGIN_SLUG")" ]; then
    unchecked "the PR is in ${SLUG} but this checkout's origin is ${ORIGIN_SLUG}; run from a clone of ${SLUG}"
  fi
else
  if ! SLUG="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"; then
    unchecked "gh cannot resolve a repository here; pass --repo <owner/name> or a PR URL"
  fi
  if [ "$(lower "$SLUG")" != "$(lower "$ORIGIN_SLUG")" ]; then
    unchecked "ambiguous repo: gh resolves PR #${PR_NUMBER} to ${SLUG} but this checkout's origin is ${ORIGIN_SLUG}; pass --repo <owner/name> or a PR URL"
  fi
fi

if ! FIELDS="$(gh api "repos/${SLUG}/pulls/${PR_NUMBER}" \
  --jq '[.merged, .base.ref, (.merge_commit_sha // "none")] | @tsv')"; then
  unchecked "cannot read PR #${PR_NUMBER} from ${SLUG}"
fi
read -r MERGED BASE_REF MERGE_SHA <<<"$FIELDS"

echo "pr=#${PR_NUMBER} repo=${SLUG} merged=${MERGED} base=${BASE_REF} merge_commit=${MERGE_SHA}"

if [ "$MERGED" != "true" ]; then
  unchecked "PR #${PR_NUMBER} in ${SLUG} is not merged; there is no landing to check"
fi

if [ "$MERGE_SHA" = "none" ] || [ -z "$MERGE_SHA" ]; then
  unchecked "PR #${PR_NUMBER} in ${SLUG} reports merged with no merge commit sha"
fi

if ! git fetch --quiet origin "$TRUNK"; then
  unchecked "cannot fetch origin/${TRUNK}"
fi

if ! git cat-file -e "${MERGE_SHA}^{commit}" 2>/dev/null; then
  if ! git fetch --quiet origin "$MERGE_SHA"; then
    unchecked "merge commit ${MERGE_SHA} is not fetchable from origin"
  fi
fi

if ! git cat-file -e "${MERGE_SHA}^{commit}" 2>/dev/null; then
  unchecked "merge commit ${MERGE_SHA} is not present in this clone after fetching"
fi

ANCESTRY=0
git merge-base --is-ancestor "$MERGE_SHA" "origin/${TRUNK}" || ANCESTRY=$?

if [ "$ANCESTRY" -eq 0 ]; then
  echo "OK: ${MERGE_SHA} is an ancestor of origin/${TRUNK}"
  exit "$EXIT_OK"
fi

if [ "$ANCESTRY" -ne 1 ]; then
  unchecked "git merge-base --is-ancestor exited ${ANCESTRY} for ${MERGE_SHA} and origin/${TRUNK}"
fi

echo "FAIL: PR #${PR_NUMBER} in ${SLUG} reports MERGED but ${MERGE_SHA} is not on origin/${TRUNK}" >&2
echo "      it landed on: $(git branch -r --contains "$MERGE_SHA" | tr -d ' ' | paste -sd, -)" >&2
echo "      the PR merged into its own base ref (${BASE_REF}), not the trunk" >&2
exit "$EXIT_FAIL"
