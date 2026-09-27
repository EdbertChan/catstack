# Sourced by run_all_tests.sh before any suite runs. Tests see none of this
# machine's own settings: no inherited catstack, git, harness or XDG
# variable, a throwaway HOME and git config, and a flag reader told to skip
# the real ~/.catstack.env and the checkout's own .env.
# tests/test_hermetic_test_env.py starts this from a polluted environment.

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

unset _catstack_name _catstack_real_home _catstack_repo
