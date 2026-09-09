# gh-write-verification

One principle, four detectors: **a command's report is not the state it
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
  `git status --porcelain >/dev/null 2>&1` are all untouched.
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

The pattern occurring **exactly once** is enough — being the `pgrep` argument
*is* the occurrence. A test for "the pattern appears elsewhere in the command"
therefore misses the canonical loop, which mentions the name only once.

**Fires on:** any `pgrep`/`pkill` with `-f`/`--full` (including `-af`, and with
value-taking flags such as `-u <user>` in front) whose pattern is a plain
literal; and a bracket-class pattern whose plain spelling still appears
somewhere else in the same command.

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

The shipped script does the whole check and exits non-zero when the commit is
not on the trunk:

```sh
bash "$HOME/.claude/hooks/gh-write-verification/verify_pr_landed_on_trunk.sh" <pr-number> [trunk]
```

Prior art: Saltzer, Reed and Clark, "End-to-End Arguments in System Design,"
ACM TOCS 2(4) 1984. An intermediate acknowledgement cannot stand in for the
end-to-end property; only the endpoints can check it.

## Why not extend `pr-schema-gate`

`pr-schema-gate` already blocks `gh pr edit --body`, so extending it was the
first candidate. It is architecturally repo-scoped: `claude_pretooluse.py`
returns early unless `repo_root_with_create_pr_tool()` finds
`scripts/create-pr.mjs`, because its redirect target *is* that script. catstack
has no `scripts/create-pr.mjs`, so `pr-schema-gate` fails open here — in the
very repo where all three failures happened. Its scope is also a different
question ("did the PR body follow the schema?") with a different redirect
than these ("is this write's effect observable at all?"), and failures 2 and 3
touch `git push`, `git merge` and `gh api` rather than PRs. Both hooks are
kept: `pr-schema-gate`'s `--body` block survives a `gh` fix, this one does not.

## Known false positive

Matching is a raw-text scan over the whole hook payload, not a shell parser,
and unlike `pr-schema-gate` this hook deliberately does **not** strip heredoc
bodies — a heredoc that writes a shell script containing a silenced mutation
is the exact shape of the incident, and `bash script.sh` is opaque to a
PreToolUse hook afterwards. The cost: documenting or testing these detectors
with an inline heredoc trips them. Write such text to a file with the `Write`
tool instead.

## Files

- `detect.py` — the four detectors and their messages
- `claude_pretooluse.py` — Claude/Cursor `PreToolUse`, exits 2 on 1, 2 and 3
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
