# ask-to-scope

Claude Code `PreToolUse` hook. When the user's message leaves out which target
they mean, it holds the first committing or user-visible tool call and tells the
agent to put one scoping question to the user, instead of guessing.

This is the executable half of two text rules: `engine/CLAUDE.core.md` (resolve
an ambiguous referent by what the conversation is about, and ask when two
readings conflict) and cat-mode's "ask clarifying questions up front on a
genuinely ambiguous ask". A text rule did not stop an agent from guessing one of
several cited files for "open the file in gitlab for me"; this hook can say no.

## Fires on

All of these, for the tool call being made:

1. The tool is one the hook gates: browser navigate/open tools
   (`mcp__*__navigate`, `browser_navigate`, `open_url`, `tabs_create`,
   `tabs_create_mcp`), `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Agent`/`Task`,
   or a `Bash` command that is not read-only.
2. The latest user message is a real user message, not a relayed
   `<task-notification>`, `<local-command...>` or `<system...>` turn.
3. Not every URL or path the call touches appears in that message. A URL
   must appear verbatim; a path may appear in full, as a tail
   (`ci/a.yml` for `/repo/ci/a.yml`), or as its exact file name.
4. The assistant has not asked this turn: no `AskUserQuestion` call and no
   question mark outside code, inline code, and URLs in its last message.
5. The hook has not already blocked once for this user message.
6. The judge says the message is ambiguous.

Steps 1 to 5 read typed fields. Step 6 is meaning, so it goes to the shared
[`llm-judge`](../llm-judge/README.md) through the
[`ambiguous-ask`](../llm-judge/phrases/ambiguous-ask.json) phrase dictionary. The
judge reads the user's message plus the URLs, paths, and job numbers the
assistant cited in its previous two turns. Regexes only extract those
candidates; none decides anything. Grow the dictionary from real misses and
false alarms; do not add a pattern here.

The judge returns only `match`. The question is not written by the judge: the
block message lists the typed candidates and tells the agent to ask which one
the user means.

## Stays silent on

- `Read`, `Grep`, `Glob`, `AskUserQuestion`, `WebFetch`, and every other tool
  the matcher does not name, so the agent can narrow the options by looking;
- read-only `Bash`: a pipeline of `cat`, `ls`, `grep`, `rg`, `find` (without
  `-exec`/`-delete`), `sed` (without `-i`), `head`, `tail`, `wc`, `jq`, `diff`
  and similar, or `git status|log|diff|show|rev-parse|grep|ls-files|blame`,
  with no redirect except to `/dev/null`, no `$(...)`, and no backticks. A
  command the parser cannot read counts as not read-only;
- a message that names its targets exactly, and a message the judge calls clear
  ("show line 980 of dependency-maps.gitlab-ci.yml", "run the tests");
- any call after the assistant asked, and any second call after one block in the
  same user message;
- subagent calls (`agent_id` set).

## Block message

`ask-to-scope: the user's message does not say which target they mean, and you
were about to <open a page|edit a file|run a command|launch a subagent>.
Candidates from the last 2 turns: ...` then one instruction: put one scoping
question to the user, such as an `AskUserQuestion` whose options are the
candidates. It says to ask what they mean, not whether the agent may, because a
permission ask is not the fix. The block clears on the next user message.

## Waiting on the judge

A block has to land before the tool runs, so the hook waits for the verdict in
the same call, on a private channel (`<transcript>#ask-to-scope`) that never
drains another hook's verdicts. The wait is `ASK_TO_SCOPE_WAIT_SECONDS`
(default 40; the hook timeout is 60). Verdicts and the once-per-message marker
are cached per transcript for two hours (ten minutes for unchecked) under
`ASK_TO_SCOPE_STATE_DIR` (default `~/.cache/catstack-ask-to-scope`), so one
user message is judged once. Parallel tool calls wait on the same job; the
process that drains the verdict writes it to the cache and the others adopt it.

The first gated call of a user message pays the judge's latency. One real run
through the real entrypoint took 37.9 s to a block and 7.2 s to a clean answer.

## Fail direction

Fails **open**, never silent.

- **Judge unavailable, no answer inside the wait, or the judge refused the
  job**: the call is allowed. The hook prints `ask-to-scope: UNCHECKED, allowing
  this <action>: <why>` to stderr and writes an `unchecked` row to the hook
  metrics. Claude Code shows exit-0 stderr only in verbose mode, so the metrics
  row is the durable record.
- **Transcript missing, unreadable, or no transcript path in the payload**: the
  same UNCHECKED allow.
- **Unparseable transcript lines**: skipped, with a count on stderr.
- **State file unreadable**: treated as empty, logged on stderr.
- A crash in `detect` allows, through the shared hook runtime.

Failing open is deliberate: a missed block costs a guess, and a wrongly held call
costs the user a question they did not need. A guard that blocks when it cannot
check would stall every edit whenever the judge CLI is down.

## Escape hatch

`CATSTACK_HOOK_MODE_ASK_TO_SCOPE=warn|off` overrides the registry's `stop` for
one machine. `warn` shows the message without blocking.

## Harnesses

Claude Code only, like `fanout-routing-guard` and `serial-option-guard`. It reads
the Claude transcript format. Cursor and Codex payloads name transcripts in other
formats and are a non-goal here.

## Files

- `detect.py`: gating, typed pre-checks, candidate extraction, the judge wait.
- `claude_pretooluse.py`: the entrypoint, via `_sdk/runtime.py`.
- `claude.hook.json` / `install_claude_hook.py`: the settings fragment and its
  idempotent merger.
- Shared code: `_sdk/judge_channel.py` (private judge channel, verdict cache),
  `_sdk/transcript_rows.py` (transcript row readers), `_sdk/events.py`
  (`is_human_text`).
