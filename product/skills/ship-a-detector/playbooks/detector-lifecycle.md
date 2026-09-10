# Shipping a detector: the verbatim list

## How to use this file

Copy all 20 steps into your todolist **before** any task-specific work,
verbatim, in this order. Then work the list.

A step that does not apply to your change **stays in the list**, marked
`skip: <reason>`. Do not delete it. The whole mechanic of this file is that
a skipped step stays visible: a step dropped silently and a step that
genuinely does not apply look identical afterwards, and only one of them is
safe. `skip: widening an existing hook, no new manifest` is a fine reason.
`skip:` with nothing after it is not.

Steps 1–3 frame the change. Steps 4–10 are the seven defect kinds, one kind
per step. Steps 11–13 are the evidence. Steps 14–19 are the tail — the
install, README, and inventory wiring, which belongs here and not to
`make-pr`. Step 20 publishes.

---

## 1. Paste the real payload before you write a regex

Put the exact text the detector must catch into the PR body or a scratch
file first, copied from where it actually happened: the shell command
string, the assistant paragraph, the transcript span. Not a paraphrase of
it. Then run your existing patterns against that text and record the hit
count.

A paraphrase is written from your own idea of the shape — the same idea the
pattern already encodes — so it agrees with the pattern by construction and
can never disconfirm it. Only the literal payload can. Then widen the
sample: grep the transcript corpus for the shape, count how often it occurs
and how often the shipped patterns hit it. One pasted example proves the
shape exists; the corpus count is what sizes the change and tells you
whether you are looking at a one-off or at a phrasing the current patterns
have been missing all along.

## 2. Write down the neighbours you are NOT catching

List the legitimate inputs that sit closest to your positive case. Each one
becomes a negative fixture in step 12. If you cannot name at least three,
your pattern is not specific enough yet to know what it will hit.

Write the list into the hook's README as a named silent set, the way
`gh-write-verification` does: the bracket idiom, a name match without `-f`,
a pattern held in a variable or command substitution, `kill -0 "$PID"`, a
log-sentinel wait. A later widening then has something to be measured
against — its Non-goals can say the silent set is unchanged, and every
previously-allowed shape still has a passing negative fixture to prove it.

Prefer silence by construction over silence by exclusion. A detector that
matches an allowlist of state-changing commands leaves every read-only
command silent because it was never in the list; a detector that blocks
broadly and subtracts safe shapes stays silent only as long as the
subtraction list keeps up with the world. This is the same choice as basing
access on permission rather than exclusion: state the conditions under which
you fire, not the conditions under which you don't.

## 3. Pick the surface, and know what that surface can see

Choose one and say why:

- `PreToolUse` — the command text, **before** the command runs. It cannot
  see the effect, and the payload `cwd` is the session's launch directory,
  not where the command will actually execute.
- `Stop` / `SubagentStop` — the outgoing message plus the transcript file.
- `UserPromptSubmit` — the user's turn, including anything they pasted.
- `scripts/check_*.py` — the repo at CI time, run from `.github/workflows/ci.yml`.

A rule that a CI script can decide from the tree belongs in a script — not
in a hook, and never in prose. "A file-reading detector must have an
unreadable-input test" is a property of the tree, so it lives in
`scripts/check_hook_test_coverage.py`, where it fails a build. Prose asking
an author to remember is the weakest form of the same rule: make the mistake
impossible to commit rather than asking for discipline.

## 4. Resolve the target before you match on it

If your detector's verdict depends on *which repo or directory* a command
means, enumerate every way the payload can name one, and write a resolver
with a test per source. There are three in this repo:

- a leading `cd <dir> &&` / `cd <dir>;` in the command text — `PreToolUse`
  fires before the shell runs, so the payload `cwd` cannot know a `cd` is
  coming.
- a `workdir` field, including Codex's JavaScript-wrapped form.
- `gh`'s own `--repo` / `-R` flag, resolved against the sibling-checkout
  convention.

Do the enumeration in one pass. Handling the source in front of you and
leaving the others gives a detector that is right about the directory it
happened to be tested in and silently wrong everywhere else — and each
missing source looks like a brand-new bug when it surfaces, not like the
same gap. When the resolver cannot resolve — the flag is present but no
matching checkout exists on disk — do not guess; take the step-11 decision
explicitly.

## 5. Strip quoted, fenced, pasted and rehearsed content before matching

Text that merely *contains* your trigger is not your trigger. Five distinct
sources, each needing its own strip:

- **Fenced blocks.** A fenced plan, diff or config block is not prose, and
  counting it as prose blocks legitimate replies and loses whatever the
  reply was carrying. Require a real closing fence when you strip, or an
  unterminated ` ``` ` becomes a way to smuggle unlimited text past the
  gate.
- **Pasted transcripts.** A prompt can quote another session's directives at
  any length, so a whole-prompt scan matches text the user is *showing* you
  rather than text they are *telling* you. Bound the scan to where a live
  directive actually sits: `engine/hooks/scope-lock/detect.py` uses the last
  `CORRECTION_SCAN_TAIL_CHARS` (400) characters.
- **Relayed machine turns.** A `<task-notification>` subagent report arrives
  shaped like a user turn and can quote your trigger phrases well enough to
  drive state — including clearing a hard stop by quoting the escape hatch
  in prose. Exempt notification-shaped text entirely, the way
  `AUTOMATED_NOTIFICATION_RE` does.
- **Quotes and meta-description.** A message that quotes or describes its
  own trigger phrase — including one explaining what the hook catches — is
  not an instance of the thing.
- **Rehearsals.** A flag that means "do not actually do it" (`--dry-run`,
  `--check`, `-n`) must not arm state that assumes it was done, or the gate
  blocks the real run that follows.

## 6. Enumerate the near-miss shapes of the same meaning

Your first pattern catches the phrasing you saw. Write out the other
spellings of the same claim and grep the transcript corpus for each one
before shipping:

- the hedged form — "I think X happened" alongside the bare claim
- reversed word order, and the follow-on clause that never uses the trigger
  word at all
- the self-caught form — "my mistake", "I misread X" — with no reference to
  a prior check
- the concession form — conceding the user's instinct beat your own checks
- the **unhedged** form, when the gate only knows hedges: a confident wrong
  diagnosis passes a bar the tentative one would have failed
- the one-shot form of a shape you only caught in a loop

For each shape, add a positive fixture. When you exempt a shape, test the
exemption rather than assuming it — an exemption is a claim about the world,
and it can simply be false. A bare `pgrep -f <token>` looks like a read-only
"is it running?" check, but the harness runs every tool call as
`bash -c '<the whole command>'`, so the token is already sitting in a live
command line before the search starts: the search matches its own shell, and
returns a pid and exit 0 with no such process running.

## 7. Return early on `stop_hook_active`, and name the deficit in the block

A `Stop` hook that blocks, gets a rewrite, and blocks the rewrite is a loop.
Nothing inside the hook ends it; the only backstop is the harness's retry
cap, and until it trips the agent shaves a few words per attempt against a
bar it cannot see. Return when `stop_hook_active` is set, the way the
sibling Stop hooks do — `grep -l stop_hook_active engine/hooks/*/claude_stop_check.py`
— so the contract is one block, one rewrite, then pass.

The block message is half the fix. Say the exact deficit and the structural
change — "cut 40 words: drop a section" — not "shorten it". A message that
names only the violated property leaves the rewrite to guesswork, which is
what produces near-identical retries. When you widen the hook, short-circuit
on `stop_hook_active` in the shared entry point, before any new path runs,
so a new check cannot reintroduce the loop.

## 8. Run every check; never exit on the first failure

A `main()` that calls `sys.exit(2)` on the first failing check hides every
later check behind the earliest-firing one. A message that is both too long
*and* makes an unverified claim then reports only the word count, and the
wrong root cause reaches the user unblocked — the hook looks like it fired
while the check that mattered never ran. Run all checks, collect every
finding, block once with all of them. Watch for a test that pins the
first-failure behaviour as intended; it makes the defect look like a
feature and has to be rewritten with the fix.

Then pin the interaction. A fix/re-trigger matrix gives each trigger a
`broken` message that must block and a `fixed` message — the compliant
rewrite — that must not block by *any* check, plus an explicit
`KNOWN_DOUBLE_BLOCKS` list for the one case where a fix deliberately still
trips a second check; `engine/hooks/diu-stop/tests/test_fix_matrix.py` is
the shape to copy. Unit-testing each check alone cannot catch this, because
the defect lives in the composition rather than in any single check.

## 9. Give the detector three outcomes, not two

Found the thing, did not find the thing, **could not read the input at
all**. Collapsing the third into the second is how a guard reports an
unchecked file as clean: a wrapper script past a size cap, a path holding an
unresolved shell variable, a stat that raised. A check that could not run is
not a pass. It says so, and which way it then resolves is the step-11
decision, made in words.

`scripts/check_hook_test_coverage.py` fails any file-reading detector that
has no test pinning its unreadable-input behaviour, so this step is a build
failure rather than a habit. Name the test with vocabulary that gate
recognises: `unreadable`, `malformed`, `corrupt`, `missing`, `too_large`,
`fails_open`.

## 10. If the detector remembers anything across turns, write the state machine down first

Cross-turn state fails in two directions, and a detector that keeps state
without a written transition table is exposed to both:

- **A state that is set but never consumed.** The detector reaches a waiting
  state and no later turn transitions it out, so the approved continuation
  can never proceed and the session is stuck behind its own guard.
- **A state that is never set.** The detector has no memory that the thing
  happened, so the follow-up it owes is never demanded, and a half-finished
  action stands as if it were complete.

Write every transition down, then a test per transition. Keep the state file
small, one per repo, **outside the worktree** so it never dirties
`git status`, and give it a TTL — `pr-schema-gate` uses
`PENDING_TTL_SECONDS = 2 * 60 * 60`. Every state read that cannot be
understood means "nothing owed": missing, unreadable, malformed,
wrong-typed, future-dated and expired all read the same way, and an
unwritable state directory logs the error to stderr and allows. Arm state on
the real action only, never on a rehearsal (step 5).

## 11. Decide the fail direction and write it in the README

Fail open or fail closed — fail-safe or fail-secure — is a per-detector
decision. Make it once, in words, and put the sentence in the hook's README
so the next author is not guessing.

The direction is not global, and one hook can need both. `scope-lock`'s two
reads resolve in opposite directions on purpose: a corrupt state file means
no lock is in force, while an unreadable transcript means no scope contract
was recorded, so an existing lock is **not** released by a file that could
not be read. `gh-write-verification` traps every uncaught detector exception
and reports "allowing", so a detector bug can only ever under-block.
`pr-schema-gate` fails open when a `--repo` flag names a repo with no
matching checkout on disk. `scripts/check_hook_test_coverage.py`
deliberately never asserts which direction you must pick — only that you
tested the one you picked.

## 12. Write the fixtures: positive, negative, unreadable

In `engine/hooks/<name>/tests/`:

- one positive test per shape from steps 1 and 6, using the pasted real
  payload, not a synthetic approximation;
- one negative test per neighbour from step 2, and a negative for every
  shape you deliberately exempted;
- one unreadable-input test if the detector opens, sizes, or stats a file;
- the fix/re-trigger matrix if the hook has more than one check.

Then run the gate on the hook by name:

```sh
python3 scripts/check_hook_test_coverage.py engine/hooks/<name>
```

It classifies by test-name substring only — it cannot judge whether a test
reproduces the right scenario. That judgment is still yours.

## 13. Prove fail-before / pass-after, and keep the prose gates green

Run the new test against the **unmodified** detector and show it failing,
then against the change and show it passing, with both outputs pasted. A
test that has only ever passed proves nothing about the detector: it may be
green on a path your change never touched. Landing the failing regression
test on its own, ahead of the fix, is the strongest form of this. Where the
suite is large, run it twice — once with only the detector reverted, once
whole — so the fail-before and the pass-after are the same suite.

Two repo gates apply to everything you just wrote:

- **No explanatory comments in code.** `scripts/check_no_new_comments.py` is
  the CI twin of the `no-comments` PreToolUse hook. The detector explains
  itself in the README and in its test names.
- **No dated provenance lines.** No "as of <date>", no incident narrative
  with a date in the rule text; `scripts/check_no_dated_provenance.py` fails
  the build on one.

## 14. Wire it into `install.sh` — the symlink AND the settings merge

Both halves, in the same PR. They are separate edits and the second is the
one that gets forgotten:

- `link_item "<name>" "$REPO_DIR/engine/hooks/<name>" "$HOME/.claude/hooks/<name>"`
  in each harness section the hook applies to (`.claude`, `.cursor`,
  `.codex`).
- `python3 "$REPO_DIR/engine/hooks/<name>/install_claude_hook.py"` in the
  settings-merge block, plus the `claude.hook.json` fragment and the
  idempotent marker-based installer it reads.

A symlink with no settings entry gives you a hook dir that ships but never
runs: present in the repo, listed in the inventory, reviewed as shipped, and
dead. Nothing downstream notices, because every other check reads the tree
rather than the merged settings — which is why the assertion in step 15 is
not optional.

If the hook wires `Stop`, `scripts/mirror_stop_hooks_to_subagent_stop.py`
mirrors it to `SubagentStop` automatically from your manifest. To opt out,
say so in the manifest with a reason — `"subagent_stop": {"inherit": false,
"reason": "..."}` — never by omission; the mirror script refuses an opt-out
that carries no reason.

## 15. Assert the wiring in `tests/test_install.py`

Add the assertion that would have failed yesterday: the symlink resolves to
`engine/hooks/<name>`, and each entrypoint appears under its event in the
merged settings. `gh-write-verification`'s block is the shape to copy — it
asserts the link target, then that `PreToolUse`, `Stop`, and `SubagentStop`
each contain the right command.

`TestEveryClaudeHookScriptIsWired::test_every_claude_hook_entrypoint_is_in_settings`
covers the general case: every `claude_*.py` entrypoint under `engine/hooks`
must be wired after install. That test is what makes step 14 impossible to
forget rather than merely easy to remember. A link is also not proof the
install took effect, so `scripts/check_install_effective.py` runs at the end
of `install.sh` and exits non-zero when it did not; and a real file
shadowing a link target makes `install.sh` exit 3 and name the shadowed
items, rather than letting a skipped link read as success.

## 16. Write `engine/hooks/<name>/README.md`

All 34 hooks in this repo have one; yours is not special. Per detector: what
it fires on, what it stays silent on, the exact block message, the fail
direction from step 11, and the escape hatch if there is one — like
`GH_WRITE_VERIFICATION_TRUST_PR_EDIT=1`, which lifts that detector once the
underlying CLI stops erroring.

The README section lands in the same change as the pattern, not after it.
The README is where the block message, the silent set and the fail direction
are readable without reading the regex, so a pattern that ships ahead of its
README is a detector whose behaviour can only be learned by tripping it.

## 17. Add the `docs/ecosystem.md` inventory row

One row in the engine inventory table: `| `<name>` | hook |`, with a
qualifier when it needs one — `hook (advisory)`, `hook (advisory; off by
default)`, `hook (not always installed)`.

This is the measured weak point: 14 of this repo's 34 hooks have no row at
all. The inventory is what a reader consults to find out what is installed
and what it does, so a missing row makes a live hook invisible to everyone
who did not write it, while it keeps firing. The row costs one line at the
moment you already know the answer, and gets expensive to reconstruct later.
Land it in the same commit as the hook.

## 18. Add the pointer from the owning skill

A detector that routes to a skill must be named in that skill's own trigger
or invoke list. Otherwise the written trigger and the detector disagree
about when the skill applies: a reader following the prose will not know the
hook fires on shapes the prose never mentions, and the skill's own list
stops being a usable description of when it runs. Add the trigger line in
the same change as the pattern, so the two cannot drift.

If the detector is a gate rather than a hook, the pointer is the
`CONTRIBUTING.md` line under `## Test` that tells a contributor to run it.

## 19. Run every step in `.github/workflows/ci.yml`

Not a subset. All 14, locally, in the order CI runs them:

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

Paste the real output into the Test Plan. A skipped step is not a pass — say
which ran and which did not. Run every `engine/hooks/*/tests` directory plus
`tests/`, the way CI runs them, not only the hook you touched: the gates
that catch this repo's recurring defects are repo-wide, and a hook-local run
stays green right up until the wiring, coverage and inventory checks see the
change.

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
