# restated-constraint

UserPromptSubmit hook: when the incoming prompt carries a constraint
(must / never / always / don't / do not / one-X-per-Y) that an earlier
human message in the same transcript already carried, inject a short
`additionalContext` line: "this constraint was already named at turn N".
A restated constraint is a FAIL-class signal, not a preference: apply it
before replying, say what changed, and do not ask the user to restate it.

Advisory only. Never blocks. Fail-open on any read/parse error.

## Detection

The prompt must match the constraint verb list. It is a restatement when
an earlier human message:

- shares a hyphenated term (`stock-agnostic` also matches `stock agnostic`;
  generic ones like `to-do`, `follow-up`, `re-run` never count), or
- is a near-duplicate (content-word Jaccard of 0.5 or more), or
- also carries a constraint verb and the same constraint clause (the
  content words after must / never / don't all appear in the earlier message).

Guards against false fires: prompts under four content words, hook feedback
and tool-result lines, system-injected turns, a transcript line identical to
the current prompt (Claude may append it before the hook runs), and a
prompt the user has already sent three or more times verbatim or as a
near-duplicate (a workflow template, not a correction).

## Files

- `detect.py` -- constraint, clause, and similarity rules; `decide()`.
- `claude_prompt_submit.py` -- Claude UserPromptSubmit entrypoint.
- `claude.prompt.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- positive fixtures fire, negative fixtures stay silent.

Cursor's `beforeSubmitPrompt` cannot inject context, and Codex is not wired
yet; both are follow-ups.

Tests: `python3 -m unittest discover -s engine/hooks/restated-constraint/tests -v`
