# gate-blame-needs-evidence

Before a reply blames a gate, the session must have read the gate. A
Stop hook (blocks with exit 2) gives feedback when a reply does one of
these about a hook it has not successfully read:

1. **Claims or reverses a claim.** It says the gate is broken, is still
   firing, or clears a certain way ("its stated clear condition is met and
   it's still firing", "it only allows the call if ...", "resets the hook's
   state", "It's not the file.").
2. **Asks for fewer steps than the refusal names.** The refusal says
   "must explicitly invoke both `/reflect` and `automate-me`" and the
   reply says "type `/reflect`". Steps listed in one sentence count
   together. An instruction inside quotes counts as a quotation, not an ask.
3. **Asks to disable it or delete its files.** For example "type `/hooks`
   ... remove it", or `rm ~/.claude/hooks/<name>/...`.

A gate is named when the reply mentions a `hooks/<name>/` path, or the
bare name of a hook that refused a call in this session. Each refusal in
the transcript (`PreToolUse:<Tool> hook error: [<command>]: <text>`,
`Stop hook feedback: [<command>]: <text>`, or UserPromptSubmit context)
gives the gate's name and its refusal text.

## Read state: three outcomes

- **read**: a tool call naming a file under `hooks/<name>/` succeeded,
  and either its output shows the refusal text, or the file it named is
  the one on disk that holds it. Partial reads of that file count.
- **refused**: such a call was made, but a gate refused it. A refused
  read is not a read.
- **none**: no such call.

Only **read** silences a check. Quoting the refusal text in the reply is
not a read, because a real reply quoted it and then called the gate
broken. Reading the entry script (which only imports the refusal text) is
not a read of the refusal-text file. When no refusal from a named hook was
seen this session, its refusal text is unknown, so any successful read of
a file under `hooks/<name>/` counts.

## Input it cannot read

- **Transcript unreadable or missing:** the result is `unchecked`, not
  clean. The hook writes that on stderr and lets the reply through (fails
  open), because the rewrite it asks for cannot fix a missing transcript.
  Pinned by `test_unreadable_transcript_is_reported_unchecked_not_clean`.
- **Gate folder not on this machine:** the on-disk proof is skipped and
  only the output proof is used. This can only add feedback, never hide it.

`stop_hook_active` skips the check so the rewrite turn can finish.

## Why

In one session a hook refused every tool call, including every attempt
to read its own source. With nothing read, the replies said its "detection
is broken", that it was "still firing" after its clear condition was met,
asked the user to type one of the two required commands, then asked the
user to delete its state files and to remove it through `/hooks`. The
hook was working. Nothing checked the claims before they reached the user.

## Files

- `detect.py`: refusal parsing, the read-state lookup, the three checks,
  and `decide_stop()`.
- `claude_stop_check.py`: the Claude Stop entry script.
- `claude.hook.json` / `install_claude_hook.py`: merges the Stop entry
  into `settings.json` (safe to run twice).
- `tests/fixtures/gate_claims_fires.json`,
  `tests/fixtures/fewer_than_required_fires.json`: real replies, copied
  word for word, that must fire. Each comes with the tool calls and hook
  refusals that came before it.
- `tests/fixtures/after_read_silent.json`: a real reply written after the
  gate's source was read. It must stay silent.
- `tests/test_hooks.py`: every fire fixture fires; every fire fixture
  goes silent once a successful read of `detect.py` is added; a refused
  read counts as no read.

Tests: `python3 -m unittest discover -s engine/hooks/gate-blame-needs-evidence/tests -v`
