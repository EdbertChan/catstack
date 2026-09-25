# gh-write-verification

One principle, five detectors: **a command's report is not the state it
claims.** A command that changes remote state has to leave behind evidence
the agent actually looked at, and that evidence has to be the effect itself
— not the tool's own claim about it. The fourth detector points the same
idea at a *read*: a check whose answer is contaminated by the act of asking.

The directory name is narrower than the current scope; it predates that
detector.

## 1. `gh pr edit` is refused on every flag (PreToolUse)

`gh pr edit` eagerly queries `repository.pullRequest.projectCards`, a sunset
Projects-classic GraphQL field, and exits 1 before writing anything —
`--base`, `--add-label`, `--title`, `--body`, all of them. The equivalent
REST calls work.

**Fires on:** any `gh pr edit ...` in a shell tool call.
**Stays silent on:** `gh pr view`, `gh api` reads, and the `gh api` writes it
redirects to.

The block names the replacements:

```sh
gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -f base=<branch>
gh api -X POST repos/<owner>/<repo>/issues/<n>/labels -f 'labels[]=<label>'
```

Set `GH_WRITE_VERIFICATION_TRUST_PR_EDIT=1` to lift the block once the CLI or
the API stops erroring. Prior art: fail-fast applied to the tool choice —
refuse the reliably-broken path up front instead of letting each session
rediscover the same GraphQL error.

## 2. A mutation with both streams discarded is refused (PreToolUse)

`gh pr edit "$1" --base main >/dev/null 2>&1` exited 1 and printed the reason
every single time; the redirect threw it away, and the next stale read-back
reported success. Four PRs merged into the wrong branch as a result.

**Fires on:** an allowlisted state-changing command — `gh pr
merge|edit|create|close|reopen|ready|comment|review`, `gh issue`/`gh release`
writes, `gh api -X POST|PATCH|PUT|DELETE`, `git push|merge|rebase|cherry-pick|revert`,
`git reset --hard`, `git branch -D`, `git tag -d`, `mergify stack push`/`queue`,
`curl -X POST|PUT|PATCH|DELETE`, `npm publish`, `docker push`, `kubectl
apply|create|delete|patch|replace`, `systemctl start|stop|restart|…`,
`terraform apply|destroy` — whose segment discards **both** stdout and stderr
(`>/dev/null 2>&1`, `&>/dev/null`, `>&/dev/null`, `>/dev/null 2>/dev/null` in
either order) with no exit-code check.

**Stays silent on:**

- every read-only command, by construction — the mutating set is an explicit
  allowlist of danger, not a blocklist of safe things. `grep -q … 2>/dev/null`,
  `command -v x >/dev/null 2>&1`, `git cat-file -e … 2>/dev/null`,
  `git status --porcelain >/dev/null 2>&1` are all untouched, and so is
  `git merge-base`, which is not `git merge`.
- an exit code that is actually checked: `… || exit 1`, `… && echo ok`,
  `if ! cmd …; then`, or `set -e` / `pipefail` anywhere in the text.
- only one stream discarded — `git push … 2>/dev/null` keeps stdout, and
  `2>&1 >/dev/null` keeps stderr on the terminal.
- a redirect that belongs to an earlier command in the pipeline:
  `grep -q main .git/HEAD 2>/dev/null && git push origin HEAD` splits on the
  `&&`, so the redirect never reaches the `git push` segment.
- a `Write`/`Edit` tool call whose *content* mentions any of these shapes —
  only shell-like tool names are matched.

Prior art: Jim Shore, "Fail Fast," IEEE Software 21(5) 2004
(<https://martinfowler.com/ieeeSoftware/failFast.pdf>). A discarded failure
surfaces later, somewhere else, with the diagnostic evidence already gone.

## 2b. A mutation whose exit code a pipe replaces is refused (PreToolUse)

A pipeline reports only its **last** stage's status. So this:

```sh
git push -u origin my-branch 2>&1 | tail -3; echo push=$?
```

printed `error: failed to push some refs` and then `push=0` — `$?` was
`tail`'s status. The output kept the failure; the exit code, which is what
the next step trusted, did not.

**Fires on:** a command from the same mutating allowlist as detector 2 that
is any stage but the last of a pipeline (`|` or `|&`), when neither of these
holds:

- `set -o pipefail` (or `setopt pipefail`) ran earlier in the same shell;
- the very next command reads the dialect's status array:
  `${pipestatus[1]}` in zsh, `${PIPESTATUS[0]}` in bash.

`|| exit 1` or `if …; then` after the pipeline does **not** count: without
pipefail both test the reader's status, not the write's.

**zsh:** `${PIPESTATUS[0]}` is empty in zsh, which is the shell a Claude Code
Bash call runs in when the login shell is zsh. The hook reads `$SHELL` to pick
the top-level dialect (bash when unset), so a `${PIPESTATUS[0]}` read in a zsh
call is flagged and the block says why. A script body run by bash
(`bash <<'EOF'`, `bash -c '…'`, a heredoc written to a `*.sh` file) is scanned
as bash, where `${PIPESTATUS[0]}` works.

**Stays silent on:** read-only pipelines (`git log | head`, `gh api <read> |
jq`); a mutation that is the **last** stage (`echo body | gh api -X PATCH …
--input -`); the mutating words inside a quoted argument (`echo 'git push' |
tail`, `grep 'git push' log | tail`); a `|` inside a `--jq` filter; output
sent to a file and read afterwards (`cmd > out.log 2>&1; echo rc=$?; tail -2
out.log`); and heredoc bodies that no shell runs (a `python3 - <<'EOF'` body,
a heredoc written to `notes.md`).

**Parser:** unlike detectors 1–3, this one splits the command with the
standard library's POSIX shell lexer (`shlex` with `punctuation_chars`), the
same lexer `pr-schema-gate/shell_model.py` uses, so pipes and separators are
real tokens and a quoted `git push` is one word of another command.
`shell_model` itself is not imported: it drops every heredoc body and flattens
pipes into separate commands, and this check needs both.

**Three outcomes, fail open on the third:** hit (exit 2), clean (exit 0), or
unchecked — an unbalanced quote or a heredoc that never closes. Unchecked
allows the command and writes
`gh-write-verification: pipe exit-code check unchecked, allowing: <reason>`
to stderr; it is never reported as clean.

## 3. A process wait that matches itself is refused (PreToolUse)

`pgrep -f` and `pkill -f` compare **full command lines**, and the pattern is
sitting in the argv of the very shell that runs them. So the match is never
empty:

```sh
pgrep -f run_all_tests.sh >/dev/null 2>&1 && echo RUNNING || echo absent
```

prints `RUNNING` even when nothing by that name exists — it matched the shell
asking the question. A wait negated on that (`! pgrep …` as a loop condition)
can never exit, and `pkill -f <name>` kills its own wrapper mid-command.

**This fires on a one-shot check too, deliberately.** An agent harness runs each
tool call as `bash -c '<the whole command>'`, so the pattern is sitting in a live
process cmdline before the search even starts. A plain `pgrep -f postgres` then
returns that wrapper and exits 0 whether or not postgres is running anywhere —
verified against a token present on no process on the box. There is no correct
plain `-f` spelling under such a harness, so a one-shot status check is a true
positive, not a tolerated false one; narrowing the detector to `until`/`while`
loops would also miss a one-shot `pkill -f` and an `if pgrep -f X; then` guard.

The pattern occurring **exactly once** is enough — being the `pgrep` argument
*is* the occurrence. A test for "the pattern appears elsewhere in the command"
therefore misses the canonical loop, which mentions the name only once.

**Fires on:** any `pgrep`/`pkill` with `-f`/`--full` (including `-af`, and with
value-taking flags such as `-u <user>` in front) whose pattern is a plain
literal — in a loop, in an `if` guard, or standalone; and a bracket-class
pattern whose plain spelling still appears somewhere else in the same command.

**Stays silent on:** the bracket idiom on its own (`pgrep -f '[r]un_all_tests'`);
a name match with no `-f` (`pgrep run_all_tests.sh`, `pgrep -x bash`) — the
shell's *name* is `bash`, so it cannot self-match; a pattern held in a variable
or command substitution, which cannot be decided statically; `kill -0 "$PID"`;
and a loop that waits on a log sentinel the runner writes.

The block names the three working shapes: wait on a sentinel the watched
process writes, wait on a pid captured with `$!`, or use the bracket class.

**Why this belongs in this repo specifically:** catstack's own
`wait-needs-wakeup` hook pushes agents toward polling loops — it blocks a plain
foreground wait and tells you to arm a watcher — without saying how to write one
that terminates. This detector closes that gap. Both hooks fire on the same
command shape, so expect to see them together.

Prior art: no formal citation found. The named folk pattern is the classic
`ps aux | grep foo` self-match and its `[f]oo` bracket idiom; the repro above is
the evidence of record.

**Sibling defect, in this repo's own hooks:** a scanner that reads data as code.
`wait-needs-wakeup` blocks on `until`/`sleep` appearing anywhere in a payload,
including inside test *strings* handed to a detector rather than commands being
run; `no-comments` had the same shape until triple-quoted strings were excluded
from its scan. This detector is exposed to it as well — its patterns are matched
in raw payload text, so writing about it in an inline heredoc trips it.

## 4. A merge cannot end the turn unverified (Stop)

`gh pr merge` reporting `MERGED` only means the PR closed against **its own
base ref**. A PR whose base was never retargeted merges into its own stack
branch and reports exactly the same `MERGED` state. Only this decides it:

```sh
git merge-base --is-ancestor <merge_commit> origin/<trunk>
```

**Fires on:** a turn that ran `gh pr merge` and never ran a landing check
afterwards. Blocking happens at `Stop`, so the last merge of a turn is
covered too, not just a chained one.
**Stays silent on:** a turn with no merge; a merge followed by
`verify_pr_landed_on_trunk.sh <that PR number>`, `git merge-base
--is-ancestor …`, or `git branch -r --contains …`; a `stop_hook_active`
rewrite turn; an unreadable or missing transcript.

The shipped script does the whole check. Name the repo explicitly, with
`--repo` or a full PR URL:

```sh
bash "$HOME/.claude/hooks/gh-write-verification/verify_pr_landed_on_trunk.sh" --repo <owner/name> <pr-number> [trunk]
bash "$HOME/.claude/hooks/gh-write-verification/verify_pr_landed_on_trunk.sh" https://github.com/<owner>/<name>/pull/<n> [trunk]
```

It fails closed. There are three outcomes, not two, and only one of them is a
pass:

| Exit | Outcome     | Meaning |
|------|-------------|---------|
| `0`  | `OK`        | the merge commit is an ancestor of `origin/<trunk>` |
| `1`  | `FAIL`      | the PR merged, but its merge commit is not on `origin/<trunk>` |
| `3`  | `UNCHECKED` | the check could not run: PR not merged, no merge commit, `gh` missing, API or fetch error, commit not fetchable, or an ambiguous repo |

A usage error exits `64`. `UNCHECKED` proves nothing and never shares an exit
code with `OK`.

The ancestry check runs in the current clone, so the PR's repo must be this
checkout's `origin`. When it is not, the script exits `UNCHECKED` instead of
answering about a different repository's PR of the same number. With a bare
PR number and no `--repo`, the repo is the one `gh` resolves here (the same
one `gh pr merge` acts on); if that differs from `origin`, as it does in a
fork whose `upstream` remote `gh` prefers, the result is `UNCHECKED`.

Prior art: Saltzer, Reed and Clark, "End-to-End Arguments in System Design,"
ACM TOCS 2(4) 1984. An intermediate acknowledgement cannot stand in for the
end-to-end property; only the endpoints can check it.

## Why not extend `pr-schema-gate`

`pr-schema-gate` already looks at `gh pr edit --body`, so extending it was the
first candidate. It is architecturally repo-scoped: it does nothing unless
`repo_root_with_create_pr_tool()` finds `scripts/create-pr.mjs`, because it
checks PR text with that repo's own `scripts/validate-pr-body.mjs`. catstack
has neither, so `pr-schema-gate` is out of scope here — in the very repo where
all three failures happened. It also answers a different question ("does the
PR text follow the repo's style?") and never blocks, while these detectors ask
"is this write's effect observable at all?", and failures 2 and 3 touch
`git push`, `git merge` and `gh api` rather than PR text. Both hooks are kept:
`pr-schema-gate`'s style check survives a `gh` fix, this one does not.

## Known false positive

For detectors 1, 2 and 3, matching is a raw-text scan over the whole hook
payload, not a shell parser (2b uses a lexer; see its section),
and unlike `pr-schema-gate` this hook deliberately does **not** strip heredoc
bodies — a heredoc that writes a shell script containing a silenced mutation
is the exact shape of the incident, and `bash script.sh` is opaque to a
PreToolUse hook afterwards. The cost: documenting or testing these detectors
with an inline heredoc trips them. Write such text to a file with the `Write`
tool instead.

## Files

- `detect.py` — the five detectors and their messages
- `claude_pretooluse.py` — Claude/Cursor `PreToolUse`, exits 2 on 1, 2, 2b and 3
- `claude_stop_check.py` — Claude `Stop`/`SubagentStop`, exits 2 on 4
- `verify_pr_landed_on_trunk.sh` — the end-to-end landing check
- `claude.hook.json` — `PreToolUse` (matcher `Bash`) + `Stop` fragments
- `install_claude_hook.py` — idempotent, marker-based merge

## Install

`./install.sh` from the repo root, then restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/gh-write-verification/tests -v
```
