# serial-option-guard

Blocks an `AskUserQuestion` menu whose `(Recommended)` option works several
independent publishing units (PR stacks, rebases, repairs) one at a time in
the parent chat, unless the routing check already ran this session.

Owning rule: cat-mode's "Many PR stacks: one parallel unit per stack, never
serial", with `corpus/skills/cat-mode/scripts/route_execution.py` as the
routing check.

## How it decides

Claude `PreToolUse` on `AskUserQuestion` (`claude_pretooluse.py` ->
`detect.py`).

1. Parse the menu. Only options whose label carries the fixed
   `(Recommended)` marker are considered. No marker, no check.
2. Parse the transcript's tool calls. If a successful `Bash` call ran
   `route_execution` with a `units` value (`units=9`, `"units": 22`) and its
   output names a route, the menu is allowed. Reading the script with `cat`
   or `grep` does not count; a call that errored does not count.
3. Otherwise ask the shared llm-judge whether the recommended option means
   "the assistant works through many publishing units one after another in
   this chat". The meaning lives in the phrase dictionary
   [`engine/hooks/llm-judge/phrases/serial-option-guard.json`](../llm-judge/phrases/serial-option-guard.json),
   not in a word list here. The hook waits for that one verdict (default 40
   seconds, `SERIAL_OPTION_GUARD_WAIT_SECONDS`) so a hit blocks the menu
   before the user sees it. It takes only its own verdict file, so other
   hooks' verdicts stay in the llm-judge inbox.

## Fires on

The real menu option `Here, one at a time (Recommended)` for "~22 PRs need
rebases or test fixes. Where should that work run?"
(`tests/fixtures/real_serial_recommended.json`), when the judge says it
matches.

## Silent on

- a serial option with no `(Recommended)` marker;
- a recommended parallel option (`Invoker workflows (Recommended)`), a
  single-unit option, or a read-only option, when the judge says clean;
- any menu after `route_execution.py` ran with `units=N` this session;
- subagent payloads and other tools.

## Block message

The dictionary's `on_hit` text: run `route_execution.py` with `units` set to
the number of units, then recommend the route it returns (an Invoker
workflow per unit, else one worktree subagent per unit). A serial option may
stay in the menu, but not as the recommended one until the check has run.

## Fail direction

Fails open, and says so. A missing or unreadable transcript, a judge with no
working runner, or a judge that does not answer in time lets the menu
through and writes `serial-option-guard: unchecked, ...` to stderr. A late
verdict still lands in the llm-judge inbox and reaches the agent after the
next tool call, before the serial work starts. A crash in the detector is
logged by the hook SDK and allows.

## Escape hatch

`CATSTACK_HOOK_MODE_SERIAL_OPTION_GUARD=off` (or `warn`). Grow coverage by
adding the real text of a miss to the dictionary's `match` list, or of a
false alarm to `not_match`.

## Tests

```
python3 -m unittest discover -s engine/hooks/serial-option-guard/tests -v
```
