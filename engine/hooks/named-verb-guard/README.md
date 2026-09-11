# named-verb-guard

Stop hook: when the user's last message named a verb (repro, test, run,
rerun, regenerate, prove, show, delete, revert, or a short "stop"), or it
was the second or later "prove it" / "show me" / "are you sure" in the
session, the outgoing reply must carry the matching evidence or the turn
is blocked (exit 2) with guidance.

| The user said | The reply (or the turn) must carry |
| --- | --- |
| repro, test, rerun, prove | a closed fenced command+output block or a `path:line` |
| run, regenerate, show | the above, or a URL, or a markdown table row |
| delete, revert | an `rm` / `git rm` / `git revert` / `git reset` / `git restore` command this turn, or that command in backticks |
| stop (message of 8 words or fewer) | no Bash / Edit / Write tool calls after the message |
| a repeated proof demand | a fenced block, `path:line`, or URL |

a well-formed `{{CAT-UNVERIFIED}}` tag anywhere in the reply, or a reply that ends in a question,
always passes: the guard wants proof or an honest "not proven", never a
prettier assurance.

Mechanical half of the `Named constraints` and `Evidence rules` in
`engine/CLAUDE.core.md`. It cannot judge whether the evidence is real; it
only refuses a bare pass/done claim where the user asked for proof.

## False-positive guards

- Verbs match only as imperatives: at the start of the message, after
  punctuation, or after please / then / now / and / can you. "the test is
  flaky" does not fire.
- "stop" fires only when it opens a message of eight words or fewer.
- Proof polling needs two demands in the session; the first "are you sure"
  stays silent.
- Hook feedback lines, tool results, and system-injected turns are never
  the user's message.
- Fail-open on any read/parse error; `stop_hook_active` allows the rewrite.

## Files

- `detect.py` -- verb, proof-demand, and evidence patterns; `decide()`.
- `claude_stop_check.py` -- Claude Stop entrypoint.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- positive fixtures block, negative fixtures stay silent.

Tests: `python3 -m unittest discover -s engine/hooks/named-verb-guard/tests -v`
