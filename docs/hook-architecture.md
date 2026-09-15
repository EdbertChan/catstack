# Catstack hook architecture: stop / warn modes and metrics

Status: draft for review. Nothing built yet.

## Binding decisions (user answers)

- Output: design doc first, then build it as a stack of small catstack PRs.
- Mode setting: one central list.
- Promotion: metrics suggest, a person decides.
- Metrics coverage: all machines.
- Stop/warn rule (user): hard stops are the ones that would burn a developer's attention. Added: stop also when the action leaves the machine or is hard to undo. Everything else warns.

## Why this is needed (current state, catstack origin/main)

| Problem | Evidence |
|---|---|
| Each hook decides stop vs warn in its own code; no setting says which | No mode/severity field in any hook config; toggles like `CATSTACK_REFLECT_ENFORCEMENT` (`_flags/flags.py:59`) only turn hooks on or off |
| 10 different output shapes across Claude, Cursor, Codex | 23 hooks use exit 2 + stderr, 17 use `additionalContext`, others use `decision:block`, `permissionDecision:deny`, `continue:false`, `followup_message`, judge queue |
| No central list of hooks | 55 hook JSON fragments, 64 installer scripts (29 carry their own `merge_hook`), a hand-written list in `install.sh:242-286` |
| Metrics guess what a hook meant from its exit code and output | `_runner/outcome.py:36-49`; a Cursor hook that prints `{"continue": true}` to allow is counted as "spoke" (`outcome.py:47`) |
| Metrics carry no rule id and nothing about what happened next | Row fields `_runner/run.py:84-94`; no acted/ignored/override data anywhere in engine/hooks or reflect scripts |
| Background model-judge verdicts never reach metrics and are deleted once read | `llm-judge/judge.py:254-286` |
| No log rotation | append-only `runs.jsonl`, no retention code in `_runner` |
| Copy-pasted helpers | transcript line parsing ×7, session state load/save ×7, transcript resolution ×4, judge loading ×3 |
| Installs drift | this Mac's catstack checkout is 60 commits behind, runs 65 hook entries with no metrics runner, and still runs two hooks deleted on main (#473, #553) |

Real data, 6 remote machines, ~27 h: 19,025 hook runs, 0 crashes, 0 unreadable rows, all Claude. Most hooks were silent; diu-stop stopped 9 and warned 765 times, hook-freshness warned 304, restated-constraint warned 9.

## Prior art (verified quotes)

- ESLint rules are `"off"`, `"warn"` ("doesn't affect exit code"), `"error"` ("exit code is 1 when triggered"). https://eslint.org/docs/latest/use/configure/rules
- Error Prone severity is one of `{"OFF", "WARN", "ERROR"}`; "The last flag for a specific check wins." https://errorprone.info/docs/flags
- Semgrep policies: Monitor ("evaluate their true positive rate"), Comment ("rules that have met your performance criteria"), Block. https://docs.semgrep.dev/semgrep-code/policies
- Sadowski et al., "Lessons from Building Static Analysis Tools at Google", CACM 61(4), 2018: code review results "allowed to include up to 10% effective false positives"; "If the ratio for an analyzer goes above 10%, the Tricorder team disables the analyzer"; a new check became a compiler error only once "the codebase was cleansed of an issue". https://storage.googleapis.com/gweb-research2023-media/pubtools/4365.pdf
- Sadowski et al., "Tricorder", ICSE 2015: build-breaking checks need an effective false positive rate "essentially zero"; an effective false positive is "any report from the tool where a user chooses not to take action to resolve the report".
- Harness contracts: Claude Code exit 2 blocks (https://code.claude.com/docs/en/hooks); Cursor exit 2 = deny, other failures let the action through unless `failClosed: true` (https://cursor.com/docs/agent/hooks); Codex `permissionDecision: "deny"` / `decision: "block"` block, `additionalContext` informs (https://learn.chatgpt.com/docs/hooks).

## Design

### 1. One central hook list: `engine/hooks/hooks.toml`

One entry per hook. It is the only place a mode lives.

```toml
[hooks.diu-stop]
summary = "Reply too long or unproven"
mode = "stop"            # off | warn | stop
fail = "open"            # what happens if the hook crashes: open lets the action through
why_mode = "attention"   # attention | outward | habit
events = { claude = ["Stop", "SubagentStop", "UserPromptSubmit"], cursor = ["stop"], codex = ["Stop"] }
rules = ["diu.word-limit", "diu.unproven-claim", "diu.phrase-list"]
```

- `why_mode` records the reason for the mode, using the stop rule above: `attention` (a wrong result lands on the developer), `outward` (leaves the machine or hard to undo), `habit` (agent-internal, warn).
- A test fails when a hook directory is missing from the list, when a listed hook has no directory, or when `mode = "stop"` has `why_mode = "habit"`.
- Emergency override: `CATSTACK_HOOK_MODE_<HOOK>=warn|off` on one machine. Every row records the effective mode and whether an override applied, so an override is visible in the report instead of silent.

### 2. Hooks return findings; shared code decides what to do

New shared package `engine/hooks/_sdk/`:

- A detector is a function `detect(event) -> list[Finding]`. It never prints, never exits.
- `Finding` is typed: `rule_id`, `subject` (the thing it is about: a file path, a command hash, a reply id), `message`, `evidence`.
- The SDK does everything else, once:
  1. reads the harness payload and transcript, and keeps session state (replaces the ×7 copies);
  2. looks up the mode in `hooks.toml`;
  3. renders the result in the harness's own shape (Claude exit 2 or `additionalContext`, Cursor `permission`/`additional_context`, Codex `permissionDecision`/`additionalContext`);
  4. writes one metrics event per finding (section 3).
- Changing a hook from warn to stop is a one-line edit to `hooks.toml`. No hook code changes.
- Model-judge hooks (named-verb-guard, incidence-needs-repetition): in `stop` mode the SDK waits for the judge with a time limit, the way diu-stop does today. If the judge cannot answer in time, the event is recorded as `unchecked` and the hook's `fail` setting decides.

### 3. Metrics v2: what the hook did and what happened next

Every finding writes an event the SDK knows, not one guessed from output:

| Field | Meaning |
|---|---|
| `schema` | event format version |
| `ts`, `machine`, `harness`, `session_id`, `turn` | where and when |
| `hook`, `rule_id`, `subject_hash` | what fired and about what |
| `mode`, `mode_source` | effective mode and whether it came from the list or an override |
| `action` | `stopped`, `warned`, `unchecked`, `crashed` |
| `finding_id` | id used to link the follow-up |
| `duration_ms` | time spent |

Silent runs keep one small row per run (hook, duration, `action = silent`) so crash and speed reporting keep working.

Follow-up events close each finding:

- `acted`: the same rule did not fire again on the same subject within the next 3 checks of that hook in the session, or the session ended without it firing again.
- `ignored`: the same rule fired again on the same subject.
- `overridden`: the user explicitly overrode it (for example, answered "do it locally" to a routing stop).
- A hook may supply its own typed resolver when the default is wrong for it (for example, prove-it style hooks resolve when a verification command runs).

Effective ignore rate per rule = (ignored + overridden) / closed findings. This is the Tricorder measure.

Storage: `~/.cache/catstack-hook-metrics/events-YYYY-MM-DD.jsonl`, 30-day retention, the runner's `runs.jsonl` kept until every hook is migrated.

### 4. All machines

- Each machine writes locally (section 3), tagged with its machine id.
- `python3 engine/hooks/_sdk/collect.py` pulls the daily event files read-only over SSH from the remote targets listed in `~/.invoker/config.json` (today 6) and merges them under `~/.cache/catstack-hook-metrics/fleet/`.
- A machine that cannot be reached or has unreadable files is listed as `unchecked` in the report, never silently left out.
- Open decision: run the collector by hand, or as a periodic Invoker worker (see Open decisions).

### 5. Report and suggestions (a person decides)

`report.py` gains a per-rule table across all machines: fires, stopped, warned, acted, ignored, overridden, unchecked, crashes, p95 time, effective ignore rate, and a suggestion column:

| Suggestion | When |
|---|---|
| warn → stop | at least 30 closed findings, effective ignore rate ≤ 2%, and `why_mode` is `attention` or `outward` |
| stop → warn | effective ignore rate > 10% over the last 30 closed findings |
| review or turn off | a warn rule ignored > 50%, or crashes/unchecked > 5% of runs |
| not enough data | fewer than 30 closed findings |

Thresholds come from the Google numbers above (≤ 10% for shown warnings, near zero for blocking). They live in `hooks.toml` so they can be tuned in review. The report never edits modes; a person changes `hooks.toml` in a PR.

### 6. Install from the list

- One installer reads `hooks.toml` and writes Claude, Cursor, and Codex configs, always through the runner (replaces 64 installer scripts and the hand-written list).
- `check_install_effective.py` compares installed hooks to the list and reports hooks that are installed but no longer listed (like the two removed ones still running on this Mac).

## Mode changes this design ships with

| Hook | What it does | Today | New | Why |
|---|---|---|---|---|
| named-verb-guard | You asked for proof (repro, test, run) and the reply has none | warns a turn later | stop | You would have to ask again |
| incidence-needs-repetition | Reply claims "always" from one run | warns a turn later | stop | You would act on an unconfirmed pattern |
| repeat-error-stop | Same failing command 3 times | stop | warn | Costs agent time, not your attention |
| text-match-decision-warn (#609) | New code decides by matching text | new | warn | Pattern guess; promote only on data |

## Build plan (catstack PR stack)

Each slice has its own proof and verify command; every safety claim is confirmed by the user per slice before it is published.

| # | Slice | Verify |
|---|---|---|
| 0 | Proof tests: Cursor allow counted as "spoke"; judge verdicts missing from metrics; no rule id in rows (expected failures) | `python3 -m unittest engine/hooks/_runner/tests/test_outcome_gaps.py` |
| 1 | `hooks.toml` with every current hook at its current mode + list/dir consistency test (no behavior change) | `python3 -m unittest engine/hooks/_sdk/tests/test_manifest.py` |
| 2 | `_sdk` finding model, harness renderers, events writer; pilot on repeat-error-stop and diu-stop at unchanged modes | `python3 -m unittest engine/hooks/_sdk/tests` + both hooks' tests |
| 3 | Follow-up resolution (acted / ignored / overridden) + 30-day rotation | `python3 -m unittest engine/hooks/_sdk/tests/test_followup.py` |
| 4 | Report per rule with suggestions | `python3 -m unittest engine/hooks/_runner/tests/test_report.py` |
| 5 | Fleet collector with `unchecked` machines | `python3 -m unittest engine/hooks/_sdk/tests/test_collect.py` + one real run against the 6 targets |
| 6 | Mode changes above (four one-line edits + synchronous judge for the two judge hooks) | the four hooks' tests |
| 7..n | Migrate remaining hooks in batches of ~5, deleting their copied helpers | each batch's hook tests + `bash scripts/test/run_all_tests.sh` |
| last | Single installer from `hooks.toml`; drift check for unlisted installed hooks | `python3 -m unittest tests/test_install.py` + `python3 scripts/ci/check_install_effective.py` |

## Non-goals

- No automatic mode flips.
- No new detectors beyond #609.
- No change to what any existing detector matches.

## Decided (user answers)

1. Fleet collection: "Invoker worker on DO1 (Recommended)". catstack ships `collect.py`; a separate Invoker slice adds a periodic worker on DO1 that runs it, following Invoker's standard worker registry, config, resolver, and UI pattern.
2. Stale install: "Stop when deleted hooks still run (Recommended)". hook-freshness stops only when the install runs hooks that no longer exist upstream (`why_mode = "attention"`); being behind otherwise still warns.
3. Acted on: "No repeat within 3 checks (Recommended)". A finding is `acted` when the same rule does not fire on the same subject in that hook's next 3 checks; `ignored` when it does.
