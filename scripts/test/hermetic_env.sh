_catstack_real_home="${HOME:-}"
_catstack_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

for _catstack_name in $(compgen -e); do
  case "$_catstack_name" in
    CATSTACK_* | GIT_* | CLAUDE_* | CODEX_* | CURSOR_* | XDG_*) unset "$_catstack_name" ;;
  esac
done

CATSTACK_TEST_HOME="$(mktemp -d "${TMPDIR:-/tmp}/catstack-test-home.XXXXXX")"
export CATSTACK_TEST_HOME
export HOME="$CATSTACK_TEST_HOME"
export GIT_CONFIG_GLOBAL="$CATSTACK_TEST_HOME/.gitconfig"
: > "$GIT_CONFIG_GLOBAL"
export GIT_CONFIG_NOSYSTEM=1
export CATSTACK_SKIP_ENV_FILES="$_catstack_real_home/.catstack.env:$_catstack_repo/.env"
export CATSTACK_HOOK_TEST_MODEL="gpt-5.6-sol"

unset _catstack_name _catstack_real_home _catstack_repo
