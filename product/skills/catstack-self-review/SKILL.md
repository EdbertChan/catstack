---
name: "catstack-self-review"
description: "Run catstack's stop-hooks (diu-stop, scope-lock, repeat-deny-stop) against your own draft message and planned tool calls before finalizing. Muse has no hook pipeline, so the agent is its own hook runner."
---

# catstack-self-review

Catstack ships deterministic stop-hooks for Claude/Cursor/Codex (`engine/hooks/`,
registry `engine/hooks/hooks.toml`, modes off/warn/stop). This skill ports three
of them to Muse by running the *same detector code* against your own work:

- **diu-stop** — flags unverified-shaped claims with no adjacent evidence in your
  planned final message, plus over-long replies. A well-formed
  `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}` excuses the paragraph
  it sits in; bare `UNVERIFIED:` excuses nothing.
- **scope-lock** — stateful per-session gate. A user correction after mutating
  work first demands a one-line scope contract (then the turn ends); a second
  correction in the same class hard-stops every tool until the user invokes
  reflect + automate-me. Off unless `CATSTACK_REFLECT_ENFORCEMENT=1`.
- **repeat-deny-stop** — two tool calls denied for the identical reason in a row
  means stop calling tools and do what the deny text says. Retrying through a
  different tool does not dodge it.
- **...and the rest of the registry.** The adapter loads every hook in
  `engine/hooks/hooks.toml`, resolves its `detect(event)`, and synthesizes the
  events its installed fragments subscribe to (Stop → your draft,
  UserPromptSubmit → your user message, PreToolUse → each planned tool call,
  PostToolUse → the result batch). A detector that cannot run on the synthetic
  event fails open (reported unchecked, never blocking). Pass `"hooks":
  ["diu-stop", "scope-lock", "repeat-deny-stop"]` for the ~90ms fast path;
  the full sweep takes ~1.3s.

State lives under muse-specific cache dirs (`~/.cache/catstack-muse-*`), so
other harnesses' sessions are never touched. Modes come from the same
`hooks.toml` registry and honor `CATSTACK_HOOK_MODE_<HOOK>` overrides.

## When to run it

Run `bin/muse_self_review.py` before finalizing, when the turn involves:

- factual claims about systems you operate (CI state, infra, money), or
- side-effecting / external tool calls (exec, browser, sends, destroys), or
- a user correction landed this session (scope-lock state may be armed).

Quick factual answers with no claims and no side effects can skip it.

## Isolated Muse judge (diu-stop plain-words)

On the Claude harness, diu-stop's plain-words check asks the shared llm-judge
(cli runners: claude/codex/cursor) whether the draft uses wording the user has
had to ask about. Those CLIs do not exist here, so the adapter sets
`CATSTACK_LLM_JUDGE_CHILD=1` — the judge queue is never polled and no detached
judge process is spawned. Instead, the full sweep can hand the *same prompt*
to an isolated Muse subagent as the judge:

1. Run the review with `"judge": true` in the input JSON (full sweep only —
   never the 90ms fast path; a judge call costs a subagent).
2. If stdout contains `JUDGE_REQUEST <path>`, read the prompt from that file
   and spawn the judge with `subagent.spawn`, using this brief verbatim:

   > You are an isolated classifier judge. Ignore all prior conversation
   > context: it is not relevant to this task. Judge ONLY the USER/ASSISTANT
   > texts in the prompt below. Use no tools. Read no files. Your FINAL
   > output must be exactly one line of JSON and nothing else.
   >
   > <judge_system_prompt + prompt from the request file>

3. Apply the verdict:

   ```bash
   python3 ~/workspace/skills/catstack-self-review/bin/muse_judge_apply.py <path> '<judge JSON>'
   ```

   Exit 2 means HIT: reword the flagged wording in everyday words, then
   re-run the review (max 3 attempts, then surface). Exit 0 means clean or
   unchecked (fail open, like the harness).

Isolation caveat (be honest about it): `subagent.spawn` inherits the agent's
transcript, so this is prompt-level isolation — a fresh agent instructed to
ignore all context and judge only the given texts — not the process-level
isolation of the CLI runners (fresh process, no memory, hooks disabled). For
a one-line JSON classification it is adequate; do not use it for judgments
that need the judge to be blind to the session.

Verified end to end: request emission, isolated-judge HIT (exit 2 with the diu
message rendered by the same `judge.verdict()` + `plain_words.message_for()`
code the Claude harness uses), and the clean path (exit 0).

## How to run it

Compose the review from your own context — no transcript file needed; the
adapter synthesizes one from what you pass:

```bash
cat > /tmp/review.json <<'EOF'
{
  "session_id": "muse-<this-chat-id>",
  "user_message": "<the user's latest message, verbatim>",
  "draft": "<your planned final message, verbatim>",
  "tool_calls": [
    {"tool": "muse.exec", "id": "c1",
     "input": {"command": "doctl compute droplet delete 123"},
     "result": "DENIED: user rejected the destroy approval"}
  ],
  "cwd": "/home/hatch/workspace"
}
EOF
python3 ~/workspace/skills/catstack-self-review/bin/muse_self_review.py /tmp/review.json
```

Conventions: `session_id` must be stable within a chat (it keys scope-lock and
repeat-deny-stop state); use a throwaway id for experiments. `result` may be
omitted for planned-but-not-run calls. Prefix a refused call's result with
`DENIED:` and the deny reason so repeat-deny-stop can match it.

To arm scope-lock enforcement for the run (it is off by default, per repo
policy — stopping all tools is opt-in):

```bash
CATSTACK_REFLECT_ENFORCEMENT=1 python3 .../muse_self_review.py /tmp/review.json
```

## Reading the result

- Exit `0` — clean. Send / act.
- Exit `1` — warn-only findings. Note them, proceed.
- Exit `2` — **STOP. Do not send the draft; do not run the tool calls.**
  Fix every flagged item (add the `{{CAT-UNVERIFIED}}` marker, narrow the
  claim to what the evidence shows, drop the denied tool call, write the
  scope contract the gate asks for) and re-run. Max 3 attempts; if still
  stopped, surface the findings to the user instead of acting.

A `scope-lock` hard-stop finding names the two invocations still needed
(reflect + automate-me). Do not work around it — that is the entire point of
the hook. Tell the user it fired and what it asks of them, then end the turn.

## Drift watch

A 30-minute cron (`catstack-muse-drift-watch`) re-runs this adapter over recent
factory work and stays silent unless a stop-class finding appears. It is the
backstop for drift that slips past the per-turn check.
