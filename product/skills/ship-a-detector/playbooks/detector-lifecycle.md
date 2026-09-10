# Shipping a detector: the verbatim list

## How to use this file

Copy all 20 steps into your todolist **before** any task-specific work,
verbatim, in this order. Then work the list.

A step that does not apply to your change **stays in the list**, marked
`skip: <reason>`. Do not delete it. The whole mechanic of this file is that
the skipped steps stay visible: 37 of this repo's PRs repaired a shipped
detector, and every one of them repaired a step that had been silently
dropped rather than skipped out loud. `skip: widening an existing hook, no
new manifest` is a fine reason. `skip:` with nothing after it is not.

Steps 1–3 frame the change. Steps 4–10 are the seven defect kinds, one
kind per step, each with the PRs that paid for it. Steps 11–13 are the
evidence. Steps 14–19 are the tail — the install, README, and inventory
wiring, which belongs here and not to `make-pr`. Step 20 publishes.

---

## 1. Paste the real payload before you write a regex

Put the exact text the detector must catch into the PR body or a scratch
file first, copied from where it actually happened: the shell command
string, the assistant paragraph, the transcript span. Not a paraphrase of
it. Then run your existing patterns against that text and record the hit
count.

`wrong-check-reflect` got its patterns widened three separate times because
each new shape was described rather than pasted. #220 pasted one real reply
— "My mistake — the skill does have disable-model-invocation: true (I
misread it)" — and it scored zero hits against every pattern the hook had.
#298 went further and counted the shape across the whole transcript corpus:
53 replies opened with that concession, 13 of them straight after a human
correction, and none matched. #322 built four detectors off three sessions
that all hit the same broken `gh pr edit` in one day.

Cited: #220, #298, #322.

## 2. Write down the neighbours you are NOT catching

List the legitimate inputs that sit closest to your positive case. Each one
becomes a negative fixture in step 12. If you cannot name at least three,
your pattern is not specific enough yet to know what it will hit.

`gh-write-verification` names its silent set explicitly and keeps a fixture
per entry: the bracket idiom, a name match without `-f`, a pattern held in
a variable or command substitution, `kill -0 "$PID"`, and a log-sentinel
wait (#323). #324 widened the same detector and its Non-goals open with
"Does not change the silent set. Every previously-allowed shape still has a
passing negative fixture." #322's detector 2 is an allowlist of
state-changing commands rather than a blocklist of safe ones, so every
read-only command with discarded output is silent by construction, not by
exclusion rule.

Cited: #322, #323, #324.

## 3. Pick the surface, and know what that surface can see

Choose one and say why:

- `PreToolUse` — the command text, **before** the command runs. It cannot
  see the effect, and the payload `cwd` is the session's launch directory,
  not where the command will actually execute (#61).
- `Stop` / `SubagentStop` — the outgoing message plus the transcript file.
- `UserPromptSubmit` — the user's turn, including anything they pasted.
- `scripts/check_*.py` — the repo at CI time, run from `.github/workflows/ci.yml`.

A rule that a CI script can decide from the tree belongs in a script, not a
hook: #296 put "a file-reading detector must have an unreadable-input test"
into `check_hook_test_coverage.py`, where it fails a build, rather than
into prose asking authors to remember.

Cited: #61, #296, #322.

## 4. Resolve the target before you match on it

If your detector's verdict depends on *which repo or directory* a command
means, enumerate every way the payload can name one, and write a resolver
with a test per source. This repo has found three, one at a time, in the
same hook:

- a leading `cd <dir> &&` / `cd <dir>;` in the command text — `PreToolUse`
  fires before the shell runs, so the payload `cwd` cannot know a `cd` is
  coming (#61).
- a `workdir` field, including Codex's JavaScript-wrapped form (#103).
- `gh`'s own `--repo` / `-R` flag, resolved against the sibling-checkout
  convention (#217).

#217's own Slice Rationale calls itself the "second, independent instance
of the class #61 already fixed once". Do the enumeration in one pass rather
than paying for a third. When the resolver cannot resolve — the flag is
present but no matching checkout exists on disk — do not guess; take the
step-11 decision explicitly.

Cited: #61, #103, #217.

## 5. Strip quoted, fenced, pasted and rehearsed content before matching

Text that merely *contains* your trigger is not your trigger. Five separate
false-positive PRs, five distinct sources:

- **Fenced blocks.** `diu-stop` counted a fenced YAML plan as prose and
  blocked a legitimate reply, which lost a staged plan draft (#66 proves
  it, #67 fixes it). Require a real closing fence when you strip, or an
  unterminated ` ``` ` becomes a way to smuggle unlimited text past the
  gate.
- **Pasted transcripts.** `scope-lock` scanned a whole prompt, so a
  101,873-character paste quoting *another* session's directives matched at
  689 characters from the end. Bound the scan to the last 400 characters,
  where a live directive actually sits (#83).
- **Relayed machine turns.** A `<task-notification>` subagent report
  arrives shaped like a user turn and can quote your trigger phrases well
  enough to drive state — including clearing a hard stop by quoting the
  escape hatch in prose. Exempt notification-shaped text entirely (#83).
- **Quotes and meta-description.** `wrong-check-reflect` and
  `restart-risk-check` both fired on text that only quoted or described
  their own trigger phrases (#174).
- **Rehearsals.** `pr-schema-gate` armed its pending state on a
  `--dry-run`, then blocked the real push that followed (#299). A flag that
  means "do not actually do it" must not arm state that assumes it was
  done.

Cited: #66, #67, #83, #174, #299.

## 6. Enumerate the near-miss shapes of the same meaning

Your first pattern catches the phrasing you saw. Write out the other
spellings of the same claim and grep the transcript corpus for each one
before shipping. Seven PRs, all the same job, all after the fact:

- the hedged form — "I think X happened" alongside the bare claim (#202,
  #208)
- reversed word order, and the follow-on clause that never uses the
  trigger word at all (#216)
- the self-caught form — "my mistake", "I misread X" — with no reference
  to a prior check (#220)
- the concession form — conceding the user's instinct beat your own checks
  (#298)
- the **unhedged** form, when the gate only knew hedges: a confident wrong
  diagnosis passed a bar the tentative one would have failed (#319)
- the one-shot form of a shape you only caught in a loop. #323 exempted a
  bare `pgrep -f` as a legitimate "is it running?" check; #324 tested that
  assumption three days later and it was false — the harness runs every
  tool call as `bash -c '<the whole command>'`, so the pattern is already
  in a live command line before the search starts, and a bare `pgrep -f`
  for a token on no process returned a pid and exit 0.

For each shape, add a positive fixture. When you exempt a shape, test the
exemption rather than assuming it (that is exactly what #324 cost).

Cited: #202, #208, #216, #220, #298, #319, #324.

## 7. Return early on `stop_hook_active`, and name the deficit in the block

A `Stop` hook that blocks, gets a rewrite, and blocks the rewrite is a
loop. `diu-stop` blocked the same message nine times while the agent shaved
a few words per attempt, until the harness cap overrode it (#124). Return
when `stop_hook_active` is set, like the sibling Stop hooks do: one block,
one rewrite, then pass.

The block message is half the fix. Say the exact deficit and the structural
change — "cut 40 words: drop a section" — not "shorten it". #124's own
Review Claim pairs the two: the `stop_hook_active` return **and** the
reason naming how many words to cut. #319's `decide()` short-circuits on
`stop_hook_active` before either new path runs, so a widening cannot
reintroduce the loop.

Cited: #124, #319.

## 8. Run every check; never exit on the first failure

`claude_stop_check.py`'s `main()` checked word-count first and called
`sys.exit(2)` on the first failing check, so a message that was both too
long *and* made an unverified claim never reached the unverified-claim
check — the one that would have caught the wrong root cause. An existing
test asserted this was intentional. Three wrong root-cause claims reached
the user that way (#77).

Then pin the interaction. #207 added a fix/re-trigger matrix: for each
trigger, a `broken` message that must block and a `fixed` message — the
compliant rewrite — that must not block by *any* check, plus an explicit
`KNOWN_DOUBLE_BLOCKS` list for the one case where a fix deliberately still
trips a second check. Unit-testing each check alone does not catch this.

Cited: #77, #207.

## 9. Give the detector three outcomes, not two

Found the thing, did not find the thing, **could not read the input at
all**. Collapsing the third into the second is how a guard reports an
unchecked file as clean. The first `ui-input-guard` skipped any wrapper
script over 64 KB and any path holding an unresolved shell variable, and
returned "clean" for both (#296).

`scripts/check_hook_test_coverage.py` now fails any file-reading detector
that has no test pinning its unreadable-input behaviour, so this step is a
build failure, not a habit. Name the test with vocabulary that gate
recognises: `unreadable`, `malformed`, `corrupt`, `missing`, `too_large`,
`fails_open`.

Cited: #296.

## 10. If the detector remembers anything across turns, write the state machine down first

Cross-turn state has its own failure set, and this repo has hit each half:

- A state that is set but never consumed. `scope-lock` reached
  `contract_required` and never transitioned to `locked` on the next
  prompt, so the approved continuation could not reach tools (#186).
- A state that is never set. `pr-schema-gate` had no memory that a
  publication happened, so `mergify stack push` published a bare body and
  nothing made the `create-pr.mjs` follow-up happen. A published PR then
  sits with a bare `Depends-On:` body until someone reads it, because no
  step downstream of the publish knows the enrichment is still owed
  (#194, #196).

Write every transition, then a test per transition. Keep the state file
small, one per repo, **outside the worktree**, with a TTL — #196 used two
hours. Every state read that cannot be understood means "nothing owed":
missing, unreadable, malformed, wrong-typed, future-dated and expired all
read as nothing owed, and an unwritable state directory logs to stderr and
allows (#194). Arm state on the real action only, never on a rehearsal
(#299, step 5).

Cited: #186, #194, #196, #299.

## 11. Decide the fail direction and write it in the README

Fail open or fail closed is a per-detector decision. Make it once, in
words, and put the sentence in the hook's README so the next author is not
guessing.

`scope-lock`'s two reads resolve in opposite directions on purpose: a
corrupt state file means no lock is in force, while an unreadable
transcript means no scope contract was recorded, so an existing lock is
**not** released by a file that could not be read (#296).
`gh-write-verification` traps every uncaught detector exception and reports
"allowing", so a detector bug can only under-block (#322). `pr-schema-gate`
fails open when a `--repo` flag names a repo with no matching checkout
(#217). #296's gate deliberately never asserts which direction you must
pick — only that you tested the one you picked.

Cited: #217, #296, #322.

## 12. Write the fixtures: positive, negative, unreadable

In `engine/hooks/<name>/tests/`:

- one positive test per shape from steps 1 and 6, using the pasted real
  payload, not a synthetic approximation (#220, #298);
- one negative test per neighbour from step 2, and a negative for every
  shape you deliberately exempted (#323, #324);
- one unreadable-input test if the detector opens, sizes, or stats a file
  (#296);
- the fix/re-trigger matrix if the hook has more than one check (#207).

Then run the gate on the hook by name:

```sh
python3 scripts/check_hook_test_coverage.py engine/hooks/<name>
```

It classifies by test-name substring only — it cannot judge whether a test
reproduces the right scenario. That judgment is still yours.

Cited: #207, #220, #296, #298, #323, #324.

## 13. Prove fail-before / pass-after, and keep the prose gates green

Run the new test against the **unmodified** detector and show it failing,
then against the change and show it passing, with both outputs pasted. #66
went as far as landing the failing regression test as its own PR before
#67 landed the fix. #299 ran each suite twice — once with only the detector
reverted, once whole.

Two repo gates apply to everything you just wrote:

- **No explanatory comments in code.** `scripts/check_no_new_comments.py`
  is the CI twin of the `no-comments` PreToolUse hook (#128). The detector
  explains itself in the README and the test names.
- **No dated provenance lines.** No "as of <date>", no incident narrative
  with a date in the rule text (#125, #198).

Cited: #66, #67, #125, #128, #198, #299.

## 14. Wire it into `install.sh` — the symlink AND the settings merge

Both halves, in the same PR. They are separate edits and the second is the
one that gets forgotten:

- `link_item "<name>" "$REPO_DIR/engine/hooks/<name>" "$HOME/.claude/hooks/<name>"`
  in each harness section the hook applies to (`.claude`, `.cursor`,
  `.codex`).
- `python3 "$REPO_DIR/engine/hooks/<name>/install_claude_hook.py"` in the
  settings-merge block, plus the `claude.hook.json` fragment and the
  idempotent marker-based installer it reads.

#114's first line: "Two shipped hooks never ran. install.sh symlinked them
into the hooks dir but no installer merged their commands into
settings.json." `frustration-watchdog` and `demo-freeze` were both live in
the repo and both dead. #301 hit the identical failure again with
`history-claim-check` and logged it as "A hook dir that ships but never
runs".

If the hook wires `Stop`, `scripts/mirror_stop_hooks_to_subagent_stop.py`
mirrors it to `SubagentStop` automatically from your manifest. To opt out,
say so in the manifest with a reason — `"subagent_stop": {"inherit":
false, "reason": "..."}` — never by omission (#260).

Cited: #114, #260, #301.

## 15. Assert the wiring in `tests/test_install.py`

Add the assertion that would have failed yesterday: the symlink resolves to
`engine/hooks/<name>`, and each entrypoint appears under its event in the
merged settings. #322's block is the shape to copy — it asserts the link
target, then `PreToolUse`, `Stop`, and `SubagentStop` each contain the
right command.

#114 added a class-level test that every `claude_*.py` entrypoint under
`engine/hooks` is wired after install, which is the check that makes step
14 impossible to forget again. A link is not proof the install took effect:
`scripts/check_install_effective.py` runs at the end of `install.sh` for
exactly that reason, and `install.sh` exits 3 and names shadowed items
rather than letting a skip read as success (#301).

Cited: #114, #301, #322.

## 16. Write `engine/hooks/<name>/README.md`

All 31 hooks in this repo have one; yours is not special. Per detector:
what it fires on, what it stays silent on, the exact block message, the
fail direction from step 11, and the escape hatch if there is one — like
`GH_WRITE_VERIFICATION_TRUST_PR_EDIT=1`, which lifts detector 1 once the
CLI stops erroring (#322).

The README line lands in the **same** PR as the pattern, not after. #220
shipped "two new admission patterns, two new negative guards, plus their
tests and the README line documenting them" as one slice; #323 and #324
each carried their own README section in the diff.

Cited: #220, #322, #323, #324.

## 17. Add the `docs/ecosystem.md` inventory row

One row in the engine inventory table: `| `<name>` | hook |`, with a
qualifier when it needs one — `hook (advisory)`, `hook (advisory; off by
default)`, `hook (not always installed)`.

This is the measured weak point. 10 of 31 hooks have no row at all, and 8
got theirs in a later PR: #246, #249, #250, #251 and #252 each shipped a
hook with no row, and #253 came back afterwards to add all of them at once.
#290 did it right — the hook and its row landed in the same commit.

Cited: #246, #249, #250, #251, #252, #253, #290.

## 18. Add the pointer from the owning skill

A detector that routes to a skill must be named in that skill's own trigger
or invoke list, or the written trigger and the detector disagree about when
it fires. #298 added one trigger line to `reflect`'s invoke list alongside
the pattern, and says why: "The reflect skill's invoke list names the same
shapes, so the written trigger and the detector agree."

If the detector is a gate rather than a hook, the pointer is the
`CONTRIBUTING.md` line under `## Test` that tells a contributor to run it.

Cited: #298.

## 19. Run every step in `.github/workflows/ci.yml`

Not a subset. Locally, in the order CI runs them:

```sh
bash scripts/run_all_tests.sh
python3 scripts/check_no_tracked_local_artifacts.py
python3 scripts/check_hook_test_coverage.py
python3 scripts/check_skills_three_harnesses.py
python3 scripts/check_ecosystem_boundaries.py
python3 scripts/check_skill_file_refs.py
python3 scripts/check_skill_test_coverage.py --base origin/main --head HEAD
python3 scripts/check_skill_test_debt_no_growth.py
python3 scripts/check_skill_trigger_mechanism.py
python3 scripts/check_dora_baseline.py
python3 scripts/check_no_dated_provenance.py --base origin/main
python3 scripts/check_no_new_comments.py --base origin/main
ruff check . --select E9,F
shellcheck install.sh
```

Paste the real output into the Test Plan. A skipped step is not a pass —
say which ran and which did not. #299's Test Plan ran each suite twice and
pasted both; #298 ran "every `engine/hooks/*/tests` directory plus
`tests/`, the way CI runs them" rather than only the hook it touched.

Cited: #298, #299.

## 20. Call `make-pr`

Now, and not before. Steps 14–18 are already done, so the PR is complete
when it opens.

Invoke the installed `make-pr` skill (catstack's overlay on `draft-pr`).
Run its preflight first:

```sh
python3 engine/skills/make-pr/scripts/preflight.py --base origin/main
```

Review Unit is `engine-runtime` for a hook or a `scripts/` gate,
`product-skill` for a skill under `product/skills/`. Do not mix units in
one PR.

`make-pr` owns the PR body schema, the confirmation rules, and the
diff-atomicity gate. It does not own steps 14–18 — that is why they are
numbered here.

Cited: #217, #322.
