# prove-it-ship-gate

Stop hook: when the outgoing message claims done / shipped / deployed / live
about work with a live side effect, the same message must carry evidence a
reviewer can chase (URL, sha, ticket id, fenced output, exit code, PID,
timestamp), or a live command must have run this turn (`ssh`, `curl`,
`gh api`, `gh pr view`, `systemctl`, ...), or the claim must carry the literal
prefix `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}`. Otherwise the
turn is blocked (exit 2).

## What counts as a live surface

Two families, and the second is not optional:

- **External services** -- Linear, a deploy or production host, DO1, a
  droplet, a webhook, Slack, an external API, a live mine, the nightly
  pipeline, the merge queue, a real tick.
- **The user's own machine, session, or screen** -- `your machine`, `your
  Mac`, `your laptop`, `your desktop`, `your screen`, `your session`, and
  the same nouns spelled as the user's or theirs, plus `playwright`,
  `electron`, and `popup`. One qualifier may sit between the two -- `your
  own machine`, `the user's own screen`, `your real laptop` all count, since
  `own` is the wording the block message, this README, and the skill all
  use. A window opened on the user's desktop is as real a side effect as a
  ticket write, and no fixture in the repo can stand in for it.

Bare `end-to-end` and `e2e` are not on that list. They say how a check ran,
not where, and `working end-to-end` / `confirmed end-to-end` are already
claim phrases -- so counting the idiom as a surface would park every such
claim on top of a live noun and collapse the two parts into one, blocking
"the parser now works end-to-end" for showing no live proof it never needed.
Say the surface: `end-to-end on your Mac` still fires.

Silent on a mention without a ship claim ("I'm about to run the Playwright
suite on your machine"), because the gate needs a claim and a live noun
within 240 characters of each other.

## What does not count as evidence

A link to the pull request that carries this change. The block message
already said the PR *number* of this change does not prove the live path
ran; a link to that same PR is the same claim in another spelling, so the
evidence scan blanks any `.../pull/<n>` URL span before it looks. Only that
span is blanked -- a sha, an exit code, or a fenced block sitting beside the
link still counts, and an Actions-run URL is still a live receipt.

Fixture tests and UI registration do not count. That is the whole point:
Invoker PRs #10553-#10558 shipped cross-repo-research after unit + fixture +
UI only, and the user had to force a live Linear e2e.

Mechanical half of `corpus/skills/prove-it-ship-gate`. Judgment (is this work
really live-side-effect work) stays with the model; the hook only matches
shapes.

## Fail direction

Open, on every read. A payload that will not parse, a transcript that cannot
be opened, and a message with no claim all allow the turn: a bug in this hook
can only under-block, never hold a correct message hostage. The escape hatch
is the tag, not a flag -- `{{CAT-UNVERIFIED: <claim> -- cannot verify: <blocker>}}`
ends the turn, and `stop_hook_active` does not, so a retry that still claims
without proof is blocked again.

## Files

- `detect.py` -- claim, live-noun, evidence, and live-command patterns; `detect()` returns SDK findings, with `decide()` kept for direct tests.
- `claude_stop_check.py` -- Claude Stop entrypoint through the shared hook runtime.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- fixtures are verbatim messages mined from real
  sessions on 2026-09-01; positive cases fire, negative cases stay silent.

Tests: `python3 -m unittest discover -s engine/hooks/prove-it-ship-gate/tests -v`
