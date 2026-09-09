# gh-write-verification

One principle, three detectors: **a write's report is not the write's
effect.** A command that changes remote state has to leave behind evidence
the agent actually looked at, and that evidence has to be the effect itself
— not the tool's own claim about it.

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

## 3. A merge cannot end the turn unverified (Stop)

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

- `detect.py` — the three detectors and their messages
- `claude_pretooluse.py` — Claude/Cursor `PreToolUse`, exits 2 on 1 and 2
- `claude_stop_check.py` — Claude `Stop`/`SubagentStop`, exits 2 on 3
- `verify_pr_landed_on_trunk.sh` — the end-to-end landing check
- `claude.hook.json` — `PreToolUse` (matcher `Bash`) + `Stop` fragments
- `install_claude_hook.py` — idempotent, marker-based merge

## Install

`./install.sh` from the repo root, then restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/gh-write-verification/tests -v
```
