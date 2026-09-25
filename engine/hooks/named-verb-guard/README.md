# named-verb-guard

Stop hook: when the user asked for something the reply must prove (repro, test,
run, show, delete, revert, stop, or proof for the second time), and the reply
carries no matching evidence, the background judge is asked whether the user
really asked. A hit arrives on a later turn through the shared
[`llm-judge`](../llm-judge/README.md) inbox. The reply is never held up.

| The user asked (judged) | Phrase dictionary | Evidence that skips the question (checked locally) |
| --- | --- | --- |
| repro, test, rerun, prove | [`named-verb-guard-prove-request.json`](../llm-judge/phrases/named-verb-guard-prove-request.json) | a closed fenced block or a `path:line` |
| run, regenerate, show | [`named-verb-guard-show-request.json`](../llm-judge/phrases/named-verb-guard-show-request.json) | the above, or a URL, or a markdown table row |
| delete, revert | [`named-verb-guard-delete-request.json`](../llm-judge/phrases/named-verb-guard-delete-request.json) | an `rm` / `git rm` / `git revert` / `git reset` / `git restore` command this turn, or that command in backticks |
| stop | [`named-verb-guard-stop-request.json`](../llm-judge/phrases/named-verb-guard-stop-request.json) | no Bash / Edit / Write tool calls after the message |
| proof, a second time this session | [`named-verb-guard-proof-demand.json`](../llm-judge/phrases/named-verb-guard-proof-demand.json) | a fenced block, `path:line`, or URL |
| the exact live target, or proof on the real surface | [`named-verb-guard-target-proof-request.json`](../llm-judge/phrases/named-verb-guard-target-proof-request.json) | the turn changed nothing; or a live check (not a file read) ran before the first change, and a pasted output line is found in a check after the last change that is not a read-back of a file the turn wrote |

Target proof reads tool results, so it can tell a stand-in from the real thing:
a saved list read before the change, output from before the change, or a
read-back of the written file. It sorts Bash commands by shape: a write
(redirect, `mv`, `cp`, `tee`, `sed -i`, `git commit`, ...) is a change, and a
command that starts with `cat`, `head`, `grep`, `jq`, `git show`, ... is a file
read. Any other command counts as a live check, so a domain command that
changes things without one of those shapes is missed as a change.

A well-formed `{{CAT-UNVERIFIED}}` tag anywhere in the reply, or a reply that
ends in a question, sends nothing: the guard wants proof or an honest "not
proven", never a prettier assurance.

Whether the user asked is meaning, so the model judges it from the dictionary.
Whether the reply carries evidence is shape, so it stays in `detect.py`. A
request type whose evidence is already in the reply is never sent to the judge.
If the result could not be checked, the inbox says "could not judge" instead of
treating the reply as clean.

To grow coverage, add the real text of a miss to that dictionary's `match`
phrases, or the real text of a false alarm to `not_match`. Do not add a pattern
to this hook.

Mechanical half of the `Named constraints` and `Evidence rules` in
`engine/CLAUDE.core.md`. It cannot judge whether the evidence is real.

## Skips

- Hook feedback lines, tool results, and system-injected turns are never the user's message.
- `stop_hook_active`, an empty reply, or a missing transcript sends nothing.
- A read error or an unloadable dictionary is logged as `catstack-hook-error named-verb-guard` and sends nothing.

## Files

- `detect.py` -- evidence shapes, transcript reading, and which request types to judge; hands the reply off through the shared runtime.
- `claude_stop_check.py` -- thin Claude Stop runtime entrypoint.
- `repro_target_proof.py` -- runs every `tests/fixtures/target_proof/` turn through the real transcript reader; `fire_` fixtures must send target proof, `clean_` ones must not.
- `eval_dictionary.py` -- asks the real judge two cases per dictionary; not run in CI, which has no model access.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- which request types are sent, and inbox delivery with a fake judge.

Tests: `python3 -m unittest discover -s engine/hooks/named-verb-guard/tests -v`

Repro: `python3 engine/hooks/named-verb-guard/repro_target_proof.py`
