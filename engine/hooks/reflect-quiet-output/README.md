# reflect-quiet-output

A reflect pass answers in chat with one sentence. The Accepted / Backlog /
Route-to-automate-me / Rejected list, the cost audit, the feedback-loop line
and any open question go into the PR body (reflect SKILL.md step 7). The chat
window gets: a PR was opened, with its link, plus "one question in the PR"
when a finding needs a human decision. This hook is the mechanical catch for
that rule.

- **Stop (blocks, exit 2):** when the current turn shows a reflect
  invocation, a reply with more than one sentence, or with a findings label
  at the start of a line (`Accepted`, `Backlog`, `Rejected`, `Dropped`,
  `Route to automate-me`, `Cost audit`, `Feedback-loop`, `Edits applied`,
  `Open question`, plain, bold, bulleted or as a heading), is blocked.

## Fires on

- The real reply in `tests/fixtures/findings_reply_fires.md`: a cost-audit
  line, then four bold section labels, printed into chat after `/reflect`.
- A two-sentence reply after a `Skill` tool call for `reflect`.
- A one-line PR link followed by bullets after a `Read` of
  `skills/reflect/SKILL.md`, or after an `Agent` prompt that names that file.

## Silent on

- One sentence with the PR link (`tests/fixtures/one_sentence_silent.md`).
  A label word inside that sentence ("with the Accepted and Backlog list in
  its body") does not count; only a label opening a line does.
- A long reply in a turn with no reflect invocation.
- A reflect envelope that only appears inside a tool result, a harness
  injection (`isMeta`), a subagent row, a task notification, or hook
  feedback: none of those is the person's own message.
- A reply in a later turn ("drop item 2"): the turn window starts at the
  person's last own message, so a reflect run earlier in the session does
  not hold every later reply to one sentence.
- A turn that edits a file under `skills/reflect/` and also reads the
  skill: that is authoring the skill, not running it. The typed `/reflect`
  command and the `Skill` tool still count in such a turn.
- `stop_hook_active`: one block, one rewrite, then pass.

## Reflect invocation shapes

Read from the person's last own message to the end of the transcript:

1. `<command-name>/reflect</command-name>` or
   `<command-message>reflect</command-message>` in that message.
2. A `Skill` tool call whose `skill` is `reflect`.
3. A tool call whose input names `skills/reflect/SKILL.md`: `Read`, a
   shell read (`cat`, `sed`, `head`, `tail`, `less`, `bat`), or an `Agent`
   prompt. `Edit`, `Write`, `Grep` and `Glob` inputs never count.

## Block message

```
reflect-quiet-output: this turn ran reflect and the reply <deficit>. Put the
Accepted / Backlog / Route-to-automate-me / Rejected list, the cost audit, the
feedback-loop line and any open question into the PR body (reflect SKILL.md
step 7), then reply with exactly one sentence: that a PR was opened, with its
link, plus 'one question in the PR' when a finding needs a human decision.
```

`<deficit>` is either `carries findings labels in chat (cost audit, accepted,
...)` or `has N sentences, not one`.

## Three outcomes and fail direction

- **Hit:** a finding; the SDK runtime renders it as exit 2 on Claude Stop.
- **Clean:** nothing.
- **Unchecked:** no transcript path, a transcript that cannot be opened, or
  no reply text. The hook writes
  `catstack-hook-unchecked reflect-quiet-output: <reason>` to stderr and does
  not block: without the transcript it cannot know whether reflect ran, so
  the read fails open. A malformed line inside an otherwise readable
  transcript is skipped and the rest is read.

Sentence counting strips markdown links, bare URLs and backticked spans first,
so the dots in a PR URL do not split the one sentence; it then splits on
sentence punctuation and on line breaks, so a bulleted list counts as several.

## Not mirrored to SubagentStop

`claude.hook.json` opts out of the SubagentStop mirror with a reason: the
reflect investigation subagent must return the full findings list to its
parent. Only the parent's chat reply to the person is held to one sentence.

## Files

- `detect.py` - turn window, invocation shapes, sentence and label checks
- `claude_stop_check.py` - Claude `Stop` wrapper on the hook SDK runtime
- `claude.hook.json` - Claude hook declaration and SubagentStop opt-out
- `tests/test_hooks.py` - fires, silent, unchecked and manifest coverage
- `tests/fixtures/` - the real findings reply and the one-sentence reply

## Install

Run `./install.sh` from the repository root, then restart Claude. The hook is
listed in `engine/hooks/hooks.toml` with mode `stop`; the registry installer
links the directory and merges the manifest.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/reflect-quiet-output/tests -v
python3 scripts/ci/check_hook_test_coverage.py engine/hooks/reflect-quiet-output
```
