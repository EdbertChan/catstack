# no-new-github-repo

One rule: **no new GitHub repositories from this machine.** A project that
has no remote stays local until the user says where it should live. A
"make a PR" request for such a project is a stop and a question, not a
reason to create somewhere to push.

`PreToolUse` on the shell tool, for Claude (`Bash`), Cursor and Codex. The
command text is parsed into the commands it will run, and each one is
judged by its program name and parsed arguments. A word list over the raw
string is not used: `grep 'gh repo create' log` is one argument of `grep`,
and stays allowed.

## Three outcomes

| Outcome | Exit (Claude) | When |
|---|---|---|
| hit | 2 | a parsed command creates or forks a GitHub repository |
| clean | 0 | every parsed command is something else |
| unchecked | 2 | the hook could not read the command at all |

**Fail direction: closed.** An unreadable payload is refused, not allowed.
A check that cannot run never returns clean. The unchecked branch covers:
hook input that is not JSON, JSON that is not an object, input that is not
UTF-8, a payload with no command field, a command field that is not text,
and a GraphQL call whose body sits in a file or on a stdin the hook cannot
see. Each case has a test.

## Fires on

Any of these, in any argument order, reached directly or through `&&`, `;`,
`|`, newlines, a `bash -c '...'` / `zsh -lc '...'` string, `eval`, a
heredoc fed to a shell, a `$(...)` substitution (inside double quotes too),
or a `sudo` / `env` / `nohup` / `time` / `nice` / `command` / `exec` wrapper:

- `gh repo create ...`, `gh repo fork ...`
- `gh api` with method POST (`-X POST`, `--method POST`, `-XPOST`, or no
  method but `-f` / `-F` / `--field` / `--raw-field` / `--input` fields,
  which `gh` sends as POST) to `user/repos`, `orgs/<org>/repos`,
  `repos/<o>/<r>/forks`, or `repos/<o>/<r>/generate`
- `gh api graphql` whose inline body carries `createRepository` or
  `cloneTemplateRepository`
- `curl`, `wget`, `http`/`https`/`xh` sending POST (explicit, or implied by
  a data flag) to the same paths on `api.github.com`, or to a
  `/api/v3/...` path on a GitHub Enterprise host, or a GraphQL body with
  the same mutations

The block message, one paragraph:

```text
no-new-github-repo: No new GitHub repositories from this machine; this project stays local. Ask the user where the code should live. Matched: `gh repo create EdbertChan/ci-projection-time-savings --private --description "..."` (gh repo create).
```

Every repo-creating command in one script is reported, not just the first.

## Stays silent on

- `gh repo view|list|clone|sync|delete`, `gh pr *`, `gh issue *`
- `gh api` reads (`gh api repos/a/b`, `gh api user/repos` with no method and
  no fields, `gh api -X GET user/repos -f per_page=5`)
- `gh api` writes to other paths (`gh api -X POST repos/a/b/issues`,
  `gh api -X PATCH repos/a/b/pulls/3`)
- `git push` to an existing remote
- the words inside an argument: a `grep` / `git grep` pattern, an `echo`
  string, a Python heredoc, a `cat > notes.md <<'EOF'` body
- `curl`/`http` GETs, `curl -G`, and POSTs to hosts that are not GitHub

Each line above has a fixture in `tests/fixtures/commands_clean.json`.

## Real payloads

`tests/fixtures/incident_command.txt` is the exact shell tool call that
created the unwanted repository: a multi-line script whose second line is
`gh repo create ... 2>&1 | tail -2`. It hits.
`tests/fixtures/memory_note_heredoc.txt` is a later call from the same
session that wrote `gh repo create` and `gh repo fork` into a memory note
through `cat > file <<'EOF'`. It stays clean.

## Parser

Logical lines are joined on `\` continuations. Heredocs are lifted out
first: a body whose introducer runs a shell (`bash <<'EOF'`, `sh`, a `.sh`
file) is parsed as another script; any other body is data and is attached
to the line as stdin text. Each line is then split on unquoted `;`, `|`,
`&`, `(`, `)`, backticks and newlines, with `$(` and backticks splitting
even inside double quotes. Each piece is tokenized with `shlex` (POSIX); a
piece `shlex` refuses (an unbalanced quote) falls back to a plain split with
quotes stripped, which leans toward detection. Leading `VAR=value` words
and known wrappers are dropped, `bash -c <string>` and `eval` recurse, and
the first word decides which rule set reads the rest.

## Escape hatch

The hook SDK's mode override applies: `CATSTACK_HOOK_MODE_NO_NEW_GITHUB_REPO=warn`
turns the block into advisory context, `off` silences it. That is a
decision for the user to make in the harness environment, not for the agent
to make from inside a session. The SDK also reads `.env` files in the
working directory for this flag, as it does for every hook.

## Non-goals

- `git push` whose URL or remote resolves to github.com for a repository
  the checkout has no remote for. Deciding that needs the remote list of the
  real working directory at run time, and the shape overlaps every
  legitimate push; it is out of scope here and stays with the user's
  standing rule.
- A repo created through a script file on disk (`bash create.sh`), through
  `xargs`, through `ssh host 'gh repo create ...'`, through a `gh alias`,
  or through a library client (Python `requests`, Octokit). The hook reads
  the command text, not files or remote shells.
- Repository creation on hosts other than GitHub (GitLab projects, Gitea).
- A GraphQL body stored in a variable (`gh api graphql -f query="$Q"`): the
  variable's value is not in the command text. The call is allowed, because
  nothing in it names a mutation; this is the one place the parser cannot
  see the meaning.

## Files

- `detect.py` — parser, rules, messages, and the fail-closed stdin reader
- `claude_pretooluse.py`, `cursor_pretooluse.py`, `codex_pretooluse.py` —
  the three harness entrypoints
- `claude.hook.json`, `cursor.hook.json`, `codex.hook.json` — settings
  fragments the registry installer merges
- `tests/` — hit, clean, and unchecked fixtures, plus the entrypoints run as
  subprocesses so the exit-2 contract is proven rather than assumed

## Install

`./install.sh` from the repo root (the `hooks.toml` entry makes the registry
installer link the directory and merge the fragments), then restart the
harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/no-new-github-repo/tests -v
python3 scripts/ci/check_hook_test_coverage.py engine/hooks/no-new-github-repo
```
