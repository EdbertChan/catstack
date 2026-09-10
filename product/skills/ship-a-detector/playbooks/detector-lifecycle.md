# Shipping a detector: the verbatim list

## How to use this file

Copy the block under **The list** into your todolist **before** any
task-specific work, verbatim, all 20 lines, in this order. Then work the
list top to bottom. The sections after the block say how to do each step
and which PRs paid for it.

A step that does not apply to your change **stays in the list**, marked
`skip: <reason>`. Do not delete it. That is the whole mechanic: a skipped
step stays visible and a reviewer can argue with the reason, while a
deleted step is invisible. Each step below exists because a shipped
detector lacked it and a later PR had to add it. `skip: widening an
existing hook, no new manifest` is a fine reason. `skip:` with nothing
after it is not.

Steps 1–3 frame the change. Steps 4–10 are the seven defect kinds, one
kind per step. Steps 11–13 are the evidence. Steps 14–18 are the tail —
the install, README, inventory and pointer wiring, which belongs here and
not to `make-pr`. Step 19 runs CI locally. Step 20 publishes by calling
`make-pr`.

## The list

```text
1. Paste the real payload before you write a regex — done: the pasted text and its hit count against the current patterns are written down. (#220, #298, #322)
2. Write down the neighbours you are NOT catching — done: three or more legitimate near-neighbours are listed, each headed for a negative fixture. (#322, #323, #324)
3. Pick the surface and the home, and check nobody is already building it — done: surface, home hook or reason for a new one, and the open-PR search are written down. (#61, #202, #208, #296, #319, #322)
4. Resolve the target before you match on it — done: every way the payload names a repo or directory has a resolver and a test, or a written non-goal. (#61, #103, #217)
5. Strip quoted, fenced, pasted and rehearsed content, span by span — done: each exemption covers only its own span, per check, with a negative fixture. (#66, #67, #77, #83, #174, #299, #319, #322)
6. Enumerate the near-miss shapes of the same meaning — done: each spelling has a positive fixture and each exemption has a test that tries to break it. (#202, #208, #216, #220, #298, #319, #324)
7. Return early on `stop_hook_active`, and name the deficit in the block — done: a test proves the second block on one turn passes, or skip: not a Stop hook. (#124, #319)
8. Run every check; never exit on the first failure — done: a message that trips two checks reports both, and a fix/re-trigger matrix covers each check. (#77, #207)
9. Give the detector three outcomes, not two — done: unreadable input has its own branch and its own test, wherever the read happens. (#296)
10. If the detector remembers anything across turns, write the state machine down first — done: every transition has a test and the state has a TTL, or skip: stateless. (#186, #194, #196, #299)
11. Decide the fail direction and write it in the README — done: one sentence per read says open or closed, and a test pins it. (#217, #296, #322)
12. Write the fixtures: positive, negative, unreadable — done: the coverage gate passes and a clean-input negative exists apart from any fails_open test. (#207, #220, #296, #298, #323, #324)
13. Prove fail-before / pass-after, and keep every consumer and prose gate green — done: both outputs pasted, importers' suites run, comment and provenance gates pass. (#66, #67, #125, #128, #174, #198, #299, #338)
14. Wire it into `install.sh` — the symlink AND the settings merge — done: both edits are in this diff, or skip: existing hook, already wired. (#114, #260, #290, #301)
15. Assert the wiring in `tests/test_install.py` — done: a test asserts the link target and each event's command, or skip: existing hook, already asserted. (#114, #301, #322)
16. Write `engine/hooks/<name>/README.md` — done: fires on, silent on, block message, fail direction and escape hatch are in this diff. (#83, #220, #322, #323, #324)
17. Add both inventory rows: `docs/ecosystem.md` and the root `README.md` — done: the hook appears in both tables in this diff. (#246, #249, #250, #251, #252, #253, #290, #322)
18. Add the pointer from the owning skill — done: the owning skill names the detector, in this diff or a named stacked slice. (#117, #298)
19. Run every step in `.github/workflows/ci.yml` — done: every command ran and its real output is in the Test Plan. (#298, #299)
20. Call `make-pr` — done: the installed make-pr skill opened the PR after its preflight passed. (#117, #217, #322)
```

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

## 3. Pick the surface and the home, and check nobody is already building it

Choose one surface and say why:

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

Then pick the home: extend an existing hook, or add a new one. Decide it
by running the pasted payload from step 1 through each sibling's
`detect.py`, not by reading names. #319 did this before widening
`hedge-runs-prove-it`: `prove-it-ship-gate`'s `CLAIM_RE` and `diu-stop`'s
`CAUSAL_CLOSER_RE` both returned no match on the real text. #322 rejected
extending `pr-schema-gate` because that hook returns early unless the repo
has `scripts/create-pr.mjs`, so it fails open in catstack — the very repo
where all three incidents happened.

Last, check that nobody is already building it:

```sh
gh pr list --state open --search "<hook-name>"
git log --oneline -10 -- engine/hooks/<hook-name>
```

#202 and #208 each added a `HEDGE_CLAIM_RE` to the same `diu-stop`
function, opened forty minutes apart from two different branches. #319
found open #309 touching the same `wrong-check-reflect` detector and
disclosed the overlap in its body instead of discovering it at merge.

Cited: #61, #202, #208, #296, #319, #322.

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
than paying for a third. The forms you choose not to resolve go in the
PR's Non-goals by name — #61 listed subshells, multiple `cd`s, and
`pushd`/`popd`. When the resolver cannot resolve — the flag is present but
no matching checkout exists on disk — do not guess; take the step-11
decision explicitly, as #217 did by failing open.

Cited: #61, #103, #217.

## 5. Strip quoted, fenced, pasted and rehearsed content, span by span

Text that merely *contains* your trigger is not your trigger. Five distinct
false-positive sources, each paid for separately:

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

Two rules for every exemption above:

- **Strip the span, not the message.** `diu-stop` once let a single
  backtick anywhere in a message suppress the unverified-claim check for the
  whole message (#77's Non-goals), and #319 found its paragraph loop still
  skipping any paragraph that held one inline backtick. A quote exempts the
  quote.
- **Decide per check.** #67 stripped fences from the word count only; the
  unverified-claim check still receives the full, unstripped message.

For a `PreToolUse` hook, positive-list the shell-like tool names. #322 did,
so a `Write` or `Edit` whose content merely mentions the blocked shape is
never blocked.

Cited: #66, #67, #77, #83, #174, #299, #319, #322.

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
exemption against the real harness rather than reasoning about it (that is
exactly what #324 cost).

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

`scripts/check_hook_test_coverage.py` fails a hook whose `detect.py` opens,
reads, or sizes a file and has no test pinning the unreadable case. Name
the test with vocabulary that gate recognises: `unreadable`, `malformed`,
`corrupt`, `missing`, `too_large`, `fails_open`.

The gate has edges, and you owe the test by hand past them. It only
checks hooks that have a `detect.py`, and it only scans `detect.py`'s own
source for file reads — a transcript read in the entrypoint does not
count. It does not cover `scripts/check_*.py` gates at all; #296's
Non-goals say so.

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
hours. The TTL is not decoration: `PreToolUse` arms state before the
command runs, so a publish that then fails leaves a stale flag, and the
TTL is what clears it (#194's Non-goals). Every state read that cannot be
understood means "nothing owed": missing, unreadable, malformed,
wrong-typed, future-dated and expired all read as nothing owed, and an
unwritable state directory logs to stderr and allows (#194). Arm state on
the real action only, never on a rehearsal (#299, step 5).

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
reproduces the right scenario. One consequence to design around: a test
named `..._fails_open` counts as the negative **and** as the unreadable
test, so a file-reading hook with one positive and one `fails_open` test
passes with no clean-input negative at all. Write the clean-input negative
as its own test.

Cited: #207, #220, #296, #298, #323, #324.

## 13. Prove fail-before / pass-after, and keep every consumer and prose gate green

Run the new test against the **unmodified** detector and show it failing,
then against the change and show it passing, with both outputs pasted. #66
went as far as landing the failing regression test as its own PR before
#67 landed the fix. #299 ran each suite twice — once with only the detector
reverted, once whole.

A matcher can have importers outside its own directory. `token_audit.py`
under `engine/skills/reflect/scripts/` loads `wrong-check-reflect/detect.py`
directly, so #174's fix changed the reflect audit too, and #174 ran that
suite as well. Find yours and run their suites:

```sh
grep -rln "<hook-name>" --include=*.py . | grep -v "^./engine/hooks/<hook-name>/"
```

Three repo gates apply to everything you just wrote:

- **No explanatory comments in code.** `scripts/check_no_new_comments.py`
  is the CI twin of the `no-comments` PreToolUse hook (#128). The detector
  explains itself in the README and the test names.
- **No dated provenance lines.** No "as of <date>", no incident narrative
  with a date in the rule text (#125, #198).
- **No tracker citations in rule prose.** The same checker rejects a
  line that introduces this repo's own number with "PR", "pull request" or
  "issue", including in a hook README (#338). The README states the rule
  and why; the history lives in the commit message.

Cited: #66, #67, #125, #128, #174, #198, #299, #338.

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
the repo and both dead. A commit inside #301 shipped `history-claim-check`
with no `install.sh` wiring at all; #114's test caught it before merge, and
the table in #301's body names the class: "A hook dir that ships but never
runs". #290 kept its wiring in the same slice
for the same reason: "Splitting the wiring into a later slice left this one
red on its own."

If the hook wires `Stop`, `scripts/mirror_stop_hooks_to_subagent_stop.py`
mirrors it to `SubagentStop` automatically from your manifest. To opt out,
say so in the manifest with a reason — `"subagent_stop": {"inherit":
false, "reason": "..."}` — never by omission (#260).

Cited: #114, #260, #290, #301.

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

Every hook in this repo has one; yours is not special. Per detector:
what it fires on, what it stays silent on, the exact block message, the
fail direction from step 11, and the escape hatch if there is one — like
`GH_WRITE_VERIFICATION_TRUST_PR_EDIT=1`, which lifts detector 1 once the
CLI stops erroring (#322).

Test the escape hatch on every harness the hook is installed for. Codex
CLI intercepts a leading `/reflect` as an unknown command before any hook
sees it, so a Codex session that hit `scope-lock`'s hard stop could never
clear it through the documented escape hatch (#83).

The README line lands in the **same** PR as the pattern, not after. #220
shipped "two new admission patterns, two new negative guards, plus their
tests and the README line documenting them" as one slice; #323 and #324
each carried their own README section in the diff.

Cited: #83, #220, #322, #323, #324.

## 17. Add both inventory rows: `docs/ecosystem.md` and the root `README.md`

Two tables, one row each:

- `docs/ecosystem.md`, engine inventory: `| `<name>` | hook |`, with a
  qualifier when it needs one — `hook (advisory)`, `hook (advisory; off by
  default)`, `hook (not always installed)`.
- root `README.md`, `## Hooks`: `| `<name>` | <when it fires, one line> |`.

This is the measured weak point. 15 of the 35 directories under
`engine/hooks/` have no `docs/ecosystem.md` row, and 8 of the hooks that do
have one got it in a later PR: #246, #249, #250, #251 and #252 each shipped
a hook with no row, and #253 came back afterwards to add all five to both
tables at once. #290 did it right — the hook and both rows landed in the
same commit. Measure the gap yourself before and after:

```sh
for d in engine/hooks/*/; do n=$(basename "$d"); grep -q "\`$n\`" docs/ecosystem.md || echo "no row: $n"; done
```

Do not skip this step on the belief that docs cannot ship with a hook.
#322's Non-goals left the root `README.md` row out on exactly that belief,
and it shipped no `docs/ecosystem.md` row either. `make-pr`'s preflight
lists `README.md` and `docs/ecosystem.md` as neutral files beside an
`engine-runtime` diff, and the diff-atomicity lint only warns.

Cited: #246, #249, #250, #251, #252, #253, #290, #322.

## 18. Add the pointer from the owning skill

A detector that routes to a skill must be named in that skill's own trigger
or invoke list, or the written trigger and the detector disagree about when
it fires. #298 added one trigger line to `reflect`'s invoke list alongside
the pattern, and says why: "The reflect skill's invoke list names the same
shapes, so the written trigger and the detector agree."

Where the pointer can land depends on the owning skill's bucket, because
`make-pr`'s preflight classifies by path (#117):

- `engine/skills/` — same `engine-runtime` unit as the hook. Same PR.
- `product/skills/` — preflight warns about two units. Same PR; declare
  `engine-runtime` and justify the pointer in Slice Rationale.
- `corpus/skills/` — preflight exits 1: "engine-runtime and corpus-lesson
  mixed in one PR". Put the pointer in the next stacked slice and mark this
  step `skip: pointer lands in stacked slice <branch>` so the debt stays
  on the list.

If the detector is a gate rather than a hook, the pointer is the
`CONTRIBUTING.md` line under `## Test` that tells a contributor to run it.

Cited: #117, #298.

## 19. Run every step in `.github/workflows/ci.yml`

Not a subset. Locally, in the order CI runs them:

```sh
npm ci
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

The preflight runs gates CI does not, such as `check_codify_has_code.py`
(#117 kept it out of CI on purpose), so a green step 19 does not make this
redundant. Review Unit is `engine-runtime` for a hook or a `scripts/` gate,
`product-skill` for a skill under `product/skills/`. A corpus-skill pointer
from step 18 is the one mix the preflight refuses.

`make-pr` owns the PR body schema, the confirmation rules, and the
diff-atomicity gate. It does not own steps 14–18 — that is why they are
numbered here.

Cited: #117, #217, #322.
