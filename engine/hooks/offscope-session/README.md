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

## The handoff record

A drift hit is only half the job: the off-scope request still has to be worked
on, just not *here*. `spawn.py` writes one JSON file per hit under
`~/.cache/catstack-offscope-session/handoffs/<id>.json`
(`CATSTACK_OFFSCOPE_STATE_DIR` moves that root), written the way
`../llm-judge/judge.py` writes its files -- temp file in the destination folder,
then `os.replace` -- so a reader never sees half a record. A handoff id holding
a slash, or starting with a dot, is refused with `ValueError`, the same refusal
`judge.enqueue` makes about job ids.

The record carries the off-scope request verbatim, the repository root the
parent session was working in, the parent session id, the harness name, and the
judge's stated reason. Verbatim matters: by the time a verdict lands the
transcript has moved on, so re-deriving the request from it would seed the new
session with the wrong thing.

Next to it, `scripts/<id>.sh` is written and made executable. It is the one file
both routes run -- the terminal runs it, and so does the person, from the single
`! bash <path>` line in the finding. One file, not pasted shell: the request is
arbitrary text somebody typed, and pasted multi-line shell loses its quoting in
transit.

## The spawn

Auto-spawn is off unless `CATSTACK_OFFSCOPE_AUTOSPAWN` is `on` or `1`
(the `enabled_by` line in `engine/hooks/hooks.toml` records that; nothing reads
that field, so it is documentation, and `spawn.py` resolves the variable
itself). With it off, the handoff is still written and reported -- a window
opening unasked is worse than a sentence.

The process is detached exactly as `judge.enqueue` detaches its judge at
`../llm-judge/judge.py`: `start_new_session=True`, `stdin` closed, standard
output and standard error into `spawn.log` inside the state directory. Never
into this hook's own standard error, which the harness parses as the hook's
answer.

The terminal is resolved through an ordered chain, each candidate checked with
`shutil.which` before it is chosen:

| Platform | Order |
|---|---|
| macOS | `open -a Terminal <script>` |
| Linux | `$CATSTACK_OFFSCOPE_TERMINAL`, then `tmux new-session -d` *when headless*, then `x-terminal-emulator`, `gnome-terminal`, `konsole`, `xterm` |

**Why `open` and not `osascript`.** `open -a Terminal <script>` is handed a file
path and re-parses nothing. An AppleScript `do script "..."` takes the command
as a *string*, which a second shell then splits again -- so a request holding a
quote, a dollar sign, or a newline would be re-interpreted on the way in. The
request is arbitrary text a person typed, so the route that never re-quotes it
is the only safe one.

**Why tmux comes before the window terminals when headless.** With no `DISPLAY`
and no `WAYLAND_DISPLAY` no window can open at all, so a detached tmux session
is the whole point rather than a fallback. That is the ordinary case for this
repository's own automation. With a display present, the window terminals come
first and tmux is not used.

The harness command for the new session comes from the harness recorded in the
handoff -- `claude`, `cursor-agent`, `codex` -- also through `shutil.which`.

## Three more outcomes, none of them silence

| Rule id | When |
|---|---|
| `offscope-session.spawn-started` | A terminal was opened for the off-scope request. |
| `offscope-session.spawn-disabled` | `CATSTACK_OFFSCOPE_AUTOSPAWN` is not on. The handoff is written; the `! bash` line starts it by hand. |
| `offscope-session.spawn-unavailable` | No terminal resolved, the harness command is missing, the terminal exited non-zero, the handoff could not be written, or the verdict carried no request. |

`spawn-unavailable` is never reported as a *detection* failure and is never a
silent pass: the judge decided correctly, the machine simply could not open a
window. It names the reason, the handoff path, and one `! bash <path>` line.
Nothing in `spawn.py` swallows an error -- every caught error is printed on
standard error and appended to `spawn.log` with the handoff id and the resolved
command, and then fails open.

A terminal emulator hands the window to its own server and returns at once, so
exit 0 counts as started; `xterm` stays in the foreground, so still running
after `SPAWN_WAIT_SECONDS` also counts as started. Only a non-zero exit inside
that window is a failure -- without the wait, a terminal that refused to open
would be reported as a session that opened.

## Not wired to the detector yet

`detect.py` does not call `spawn.spawn` in this slice, on purpose: the detection
logic from the previous slice is left untouched. `spawn.spawn(verdict, event)`
takes a drained drift-hit verdict and returns exactly one spawn finding, and it
reads the request from the verdict's `offscope_request` field -- the field
`build_job` already puts on the judge job. Carrying that field through the
judge's verdict, and calling `spawn` from `report`, is the next slice.

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

## Files

- `detect.py` — `build_job` (enqueue the question), `report` (drain and turn
  each verdict into a `Finding`), `detect` (both, fail-open)
- `spawn.py` — `handoff_record` / `write_handoff` (the record), `write_script`
  (the one file both routes run), `resolve_terminal` (the ordered chain),
  `spawn` (all three spawn outcomes, fail-open)
- `../llm-judge/phrases/offscope-session.json` — the meaning, the off-scope
  examples, and the hard negatives

## Tests

```sh
python3 -m unittest discover -s engine/hooks/offscope-session/tests -v
```

`tests/test_hooks.py` covers the detector, `tests/test_hooks_spawn.py` the
handoff and the spawn. Every terminal in the spawn tests is a stub script on a
`PATH` holding nothing else, so no test can open a real window.
