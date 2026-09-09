# answer-overrides-menu (hook)

PostToolUse on `AskUserQuestion`: when an answer is not verbatim one of the
labels offered for that same question, the user overrode the menu. Inject a
reminder that a free-text answer supersedes every option offered and has to
be restated as a binding parameter before planning. Inject-only, never
blocks, fail-open.

## The failure mode

`AskUserQuestion` presents a menu and the harness appends an "Other" escape
hatch. A user who types instead of picking has said the most binding thing
in the turn: every option offered was wrong. That answer is also the least
durable thing in the transcript. A typed message persists as a `user` turn
the model re-reads on every subsequent request; an `AskUserQuestion` answer
lands inside a `tool_result` blob shaped exactly like a `Bash` result, is
never restated, and is never carried into the plan. Highest information,
lowest durability — so the plan gets built from the menu the agent wrote
rather than the answer the user gave, and the substitution is invisible at
the point where the work happens.

This is Green & Petre's **hidden dependencies** dimension: a value that
governs downstream behaviour but is not visible where that behaviour is
decided. Their prescription is to surface the dependency at the point of
use rather than rely on the reader to remember it. The hook does exactly
that — it re-emits the answer into context at the moment it was given.

> Green, T. R. G. and Petre, M. "Usability Analysis of Visual Programming
> Environments: A Cognitive Dimensions Framework." *Journal of Visual
> Languages & Computing* 7(2), 1996, 131-174.
> <https://doi.org/10.1006/jvlc.1996.0009>

## What makes it fire, exactly

Zero heuristics. No regex over prose, no keyword list, no sentiment. Every
decision is a string comparison against the tool call's own payload.

`AskUserQuestionOutput.answers` is keyed by question text, so each answer is
compared only against the labels of **its own** question.

Fires when, for any question:

- the answer, stripped, is not one of that question's `options[].label`, and
- the question is not `multiSelect`, or it is and some comma-separated part
  of the answer is not one of that question's labels
  (`sdk-tools.d.ts`, `AskUserQuestionOutput.answers`: "multi-select answers
  are comma-separated")

or when `AskUserQuestionOutput.response` — the harness's own field for
"freeform text the user typed instead of selecting a structured option" — is
non-empty.

Stays silent when:

- every answer is verbatim a label of its own question (a menu pick)
- a multi-select answer's parts are all labels of that question
- the answer's question text is not among the offered questions, so there is
  nothing to compare it against
- the tool is not `AskUserQuestion`
- the payload carries an `agent_id` — a subagent's `AskUserQuestion` is not
  the human's, matching `frustration-watchdog` and `auto-pr`
- the payload is malformed, missing, or not JSON

## Fixtures

Both are verbatim payloads from real sessions.

- `tests/fixtures/real_free_text_override.json` — three questions; the user
  typed `"0DTE and futures. futures need to be checked"` for the instrument
  and free text for the entry rule, and picked an offered label for the
  repo. The hook fires on the two overrides and not on the pick. A five-year
  SPY equities pipeline was built from the menu instead.
- `tests/fixtures/real_menu_pick.json` — the user selected
  `"Install fnm + Node 26"`, an offered label. Silent.

## Files

- `detect.py` — `overrides()`, `reminder_text()`, `decide()`.
- `claude_posttooluse.py` — Claude PostToolUse entrypoint, `agent_id` guard.
- `claude.hook.json` / `install_claude_hook.py` — settings.json merge (idempotent).
- `tests/test_hooks.py` — override, per-question label scoping, multi-select,
  freeform field, menu pick, subagent, fail-open.

Claude-only: `AskUserQuestion` has no Cursor or Codex equivalent, so there is
nothing to mirror into those harnesses.

Tests: `python3 -m unittest discover -s engine/hooks/answer-overrides-menu/tests -v`
