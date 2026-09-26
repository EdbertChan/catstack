# offscope-session

Notice when the person's new prompt has left the work this session has been
doing, and say so. A session that pivots to a genuinely unrelated task carries
the finished work's context forward forever: every later turn re-sends it, pays
for it again, and lets it compete for attention with the new task. Nothing else
in this repo notices that.

Off by default (`mode = "off"` in `engine/hooks/hooks.toml`). A later slice
promotes it only on measured numbers.

## Fires on

A human `UserPromptSubmit` whose prompt is a genuinely unrelated task: a
different incident, a different deliverable, nothing left in common with what
came before. That is the same wording as the rule in `corpus/CLAUDE.learned.md`
(the session-hygiene rule about pivoting), on purpose, so the hook and the
written rule cannot drift apart.

The hook never blocks and never enforces. A hit suggests a `/clear` or a fresh
session, exactly as the rule says: suggest the reset, do not enforce it.

## Stays silent on

- **Non-human prompts.** A task notification, a slash-command expansion, and a
  system block are never judged and never counted as scope
  (`is_human_prompt` from `engine/hooks/_sdk/events.py`).
- **The same work in new words.** A follow-up, a correction (`no, use the
  existing helper`), a narrowing (`just the parser part`), a test of the same
  work, a write-up of the work just done, and a question about the same code
  from another angle are all on scope. Those are the false positives that would
  make this hook hostile, so each one is a hard negative in the phrase
  dictionary and a test.
- **The first prompt of a session.** There is no running scope to leave yet.
- **Subagent sessions**, and anything running inside the judge itself.

## One turn late, on purpose

The judge is a background model call. The verdict lands after the reply that
caused it, so `report` hands it over on the *next* human prompt, never in the
turn that asked. Waiting for it would hold up the reply, which is the one cost
a detector like this must not impose. The trade is that the suggestion to start
a fresh session arrives one prompt after the pivot.

Verdicts are addressed to `"<transcript>#offscope-session"`, not the bare
transcript path. `judge.drain` deletes what it reads, so draining the plain
transcript would swallow the llm-judge inbox's messages for every other hook in
the session.

## Three outcomes

| Rule id | When |
|---|---|
| `offscope-session.drift-hit` | The judge answered, and `offscope` is JSON `true`. |
| `offscope-session.on-scope` | The judge answered, and `offscope` is JSON `false`. |
| `offscope-session.unchecked` | Anything else. |

Unchecked is its own outcome, never folded into on-scope: malformed JSON, an
answer with no `offscope` key, an answer whose key is the string `"true"`, an
errored job, an unreadable verdict file, and no model command installed all land
here, with the reason attached. A check that could not run is not a pass.

## What the judge is shown

The running scope is rebuilt from the transcript: each human message plus that
turn's final assistant reply, collected newest-first until
`SCOPE_BUDGET_CHARS` (24,000) is full, then rendered oldest first. Newest-first
is the point -- scope moves forward, so truncation has to drop the oldest
context, not the most recent. The judge's whole prompt is one command-line
argument, which stops working near 128 KB and comes back `unchecked`, so both
budgets sit far below it.

The job also carries the off-scope request verbatim under `offscope_request`,
so whatever acts on a hit later seeds a new session from what the person
actually typed instead of deriving it a second time from a transcript that has
moved on.

## Not scope-lock, not split-scope

- **`scope-lock`** fires when the *user corrects the agent* for drifting, and it
  blocks tools until a scope contract is written. Its subject is the agent going
  somewhere it was not sent. This hook's subject is the *user* changing the
  subject, which is entirely their right; it only suggests a fresh session.
- **`split-scope`** fires when one prompt plans multi-slice or multi-PR work,
  and reminds the agent to slice it. Its subject is work that is too big for one
  change. This hook's subject is two pieces of work that have nothing to do with
  each other sharing one conversation.

Neither of those is edited or widened by this hook.

## All three harnesses, one detector

`./install.sh` ships this hook to Claude Code, Cursor, and Codex in one run.
Each harness gets its own thin entrypoint, and all three call the same
`detect.detect`:

| Harness | Event it listens on | Entrypoint |
|---|---|---|
| Claude Code | `UserPromptSubmit` | `claude_prompt_submit.py` |
| Cursor | `beforeSubmitPrompt` | `cursor_before_submit.py` |
| Codex | `UserPromptSubmit` | `codex_prompt_submit.py` |

Cursor's event is spelled `beforeSubmitPrompt`, lower-case `b`, because that is
the exact string both `detect.PROMPT_EVENTS` and `_sdk/render.py` match on. A
capitalised spelling makes the hook do nothing at all on Cursor.

The entrypoints hold no detection logic of their own, and a test asserts each
one's `detect` *is* `detect.detect`, so the three cannot drift apart.

**Drain first, then enqueue.** Each entrypoint gets one event and does both
halves of the hook on it, in that order — `detect.detect` is what fixes the
order. Enqueueing first would risk draining the job just queued and answering
the current turn's own prompt, which is the whole one-turn-late design gone. A
test hands the detector a judge whose verdict is ready the instant a job is
enqueued, so the wrong order shows up as an extra finding rather than as a rare
race.

Each harness keeps its config file: the three `install_*_hook.py` scripts merge
only the entry naming their own entrypoint and leave everything else alone, so
a second `./install.sh` run reports `already up to date` and rewrites nothing.

## Files

- `detect.py` — `build_job` (enqueue the question), `report` (drain and turn
  each verdict into a `Finding`), `detect` (both, in that order, fail-open)
- `claude_prompt_submit.py`, `cursor_before_submit.py`,
  `codex_prompt_submit.py` — one entrypoint per harness, each a single
  `run_hook` call into the shared `detect.detect`
- `claude.hook.json`, `cursor.hook.json`, `codex.hook.json` — the event
  registration each harness reads
- `install_claude_hook.py`, `install_cursor_hook.py`, `install_codex_hook.py` —
  idempotent, marker-based merges into `~/.claude/settings.json`,
  `~/.cursor/hooks.json`, and `~/.codex/hooks.json`
- `../llm-judge/phrases/offscope-session.json` — the meaning, the off-scope
  examples, and the hard negatives

## Tests

```sh
python3 -m unittest discover -s engine/hooks/offscope-session/tests -v
```

`tests/test_hooks.py` covers the detector and the three verdict outcomes;
`tests/test_three_harnesses.py` covers the entrypoints, the event ordering, and
the installers, reusing the same conversation fixture.
