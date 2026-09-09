#!/usr/bin/env python3
"""Structural regression tests for corpus/skills/cat-mode/SKILL.md.

cat-mode is prose, not code -- there is no way to mechanically test whether
an agent actually follows it. What IS mechanically testable, and worth
guarding, is the skill *file* staying well-formed: valid frontmatter, the
deliberate disable-model-invocation:true choice not silently flipping,
every skill it references by name still existing, and the file not
re-bloating the way CLAUDE.md's class-search bullet did before it was
split apart (see cat-mode's own "fix doc bloat proactively" bullet).

Run: python3 -m unittest discover -s tests -v
(stdlib unittest + re only, matches tests/test_install.py and
engine/hooks/diu-stop/tests/test_hooks.py -- no PyYAML dependency in this repo.)
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_PATH = os.path.join(REPO_ROOT, "corpus", "skills", "cat-mode", "SKILL.md")
SKILL_ROOTS = (
    os.path.join(REPO_ROOT, "engine", "skills"),
    os.path.join(REPO_ROOT, "corpus", "skills"),
    os.path.join(REPO_ROOT, "product", "skills"),
)

# Calibrated against the file as of this test's authoring (134 lines, 15
# bullets, longest bullet line 76 chars) with headroom for organic growth --
# tight enough to catch the file re-bloating into a CLAUDE.md-style wall of
# text, loose enough not to fail on a normal new bullet. Raised from 220
# after #37 (owner-serve) already sat over the cap; raised again from 260
# after the "Categorical constraints & recurrence" section, which was the
# expected next increment, not a rewrite.
MAX_TOTAL_LINES = 300
MAX_BULLET_WORDS = 140
ROUTING_REF = os.path.join(REPO_ROOT, "corpus", "skills", "cat-mode", "references", "execution-routing.md")


def read_skill_text():
    with open(SKILL_PATH, encoding="utf-8") as f:
        return f.read()


def parse_frontmatter(text):
    """Extracts the --- ... --- frontmatter block as a dict of top-level
    `key: value` pairs. Deliberately not a real YAML parser (no PyYAML
    dependency in this repo) -- good enough for this file's flat frontmatter
    shape, matching every other test file's stdlib-only convention."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        field_match = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", line)
        if field_match:
            fields[field_match.group(1)] = field_match.group(2).strip()
    return fields


class TestCatModeFrontmatter(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(os.path.isfile(SKILL_PATH), f"missing {SKILL_PATH}")

    def test_frontmatter_parses_and_has_required_fields(self):
        fields = parse_frontmatter(read_skill_text())
        self.assertIsNotNone(fields, "SKILL.md must open with a --- ... --- frontmatter block")
        self.assertIn("name", fields)
        self.assertIn("description", fields)
        self.assertIn("disable-model-invocation", fields)

    def test_name_is_cat_mode(self):
        fields = parse_frontmatter(read_skill_text())
        self.assertEqual(fields["name"], "cat-mode")

    def test_disable_model_invocation_stays_true(self):
        # Deliberate design choice (see the automate-me skill's own step 4):
        # mode skills are heavy and opinionated and must apply only when
        # explicitly invoked. A future edit accidentally dropping or
        # flipping this would make cat-mode auto-trigger on every session.
        fields = parse_frontmatter(read_skill_text())
        self.assertEqual(fields["disable-model-invocation"], "true")

    def test_description_is_a_real_trigger_not_a_placeholder(self):
        # Frontmatter description is what an agent actually reads to decide
        # relevance; a folded multi-line YAML block (`description: >`) needs
        # the frontmatter's raw block, not just the first-line regex match.
        raw_frontmatter = re.match(r"^---\n(.*?)\n---\n", read_skill_text(), re.DOTALL).group(1)
        description_block = re.search(r"description:\s*>?\s*\n((?:  .+\n?)+)", raw_frontmatter)
        self.assertIsNotNone(description_block, "description field must be present")
        description_text = description_block.group(1)
        self.assertGreater(len(description_text.split()), 10, "description reads like a placeholder, not a real trigger")


class TestCatModeDefaultHookPointer(unittest.TestCase):
    def test_body_names_the_default_hook_and_flag(self):
        text = normalized_skill_text()
        self.assertIn("Applied by default when `CATSTACK_CAT_MODE_DEFAULT=1` via the `cat-mode-default` hook", text)
        self.assertTrue(os.path.isdir(os.path.join(REPO_ROOT, "engine", "hooks", "cat-mode-default")))
        self.assertEqual(parse_frontmatter(read_skill_text())["disable-model-invocation"], "true")


class TestUiTestingRule(unittest.TestCase):
    """The rule that keeps a UI proof run off the user's own session.

    Prose cannot be executed, but the pieces an agent has to act on -- a
    disposable surface, a granted window, the marker path the guard hook
    reads, and cleanup -- must all still be named, and the marker path must
    match the hook that enforces it.
    """

    def test_names_a_disposable_surface_and_a_granted_window(self):
        text = read_skill_text().lower()
        self.assertIn("disposable", text)
        self.assertIn("hands-off window", text)

    def test_names_the_marker_path_the_guard_hook_reads(self):
        self.assertIn("/tmp/.ui-input-window", read_skill_text())

    def test_marker_path_matches_the_hook_default(self):
        hook = os.path.join(REPO_ROOT, "engine", "hooks", "ui-input-guard", "detect.py")
        with open(hook, encoding="utf-8") as handle:
            self.assertIn('"/tmp/.ui-input-window"', handle.read())

    def test_requires_cleanup_of_what_the_run_left_behind(self):
        text = read_skill_text().lower()
        self.assertTrue("residue" in text or "undo stray" in text, "cleanup rule missing")


class TestCatModeReferences(unittest.TestCase):
    def test_every_referenced_skill_still_exists(self):
        text = read_skill_text()
        referenced = set(re.findall(r"`([a-z][a-z0-9-]*)`", text))
        # Backtick tokens that read as skill-name-shaped (lowercase,
        # hyphenated) but aren't actually skill references (e.g. a
        # hypothetical shell flag) would need excluding here; none exist
        # in the file as of this writing -- if one is added, add it to this
        # allowlist rather than weakening the check.
        not_a_skill_reference = {
            # Invoker-repo skills named in prose; not shipped in catstack.
            "admin-bypass",
            "cat-mode-default",
            "invoker-make-pr",
            "invoker-ops",
            "prove-it",
            "safe-stack-push",
            # Command / process tokens in backticks, not skill names.
            "checkout",
            "invoker-cli",
            "kill",
            "ls",
            "owner-serve",
            "strace",
            # Absolute-negative words in backticks, not skill names.
            "only",
            "never",
            "any",
            "no",
        }
        missing = []
        for name in sorted(referenced - not_a_skill_reference):
            if not any(os.path.isdir(os.path.join(root, name)) for root in SKILL_ROOTS):
                missing.append(name)
        self.assertEqual(missing, [], f"cat-mode references skill(s) that no longer exist: {missing}")


class TestCatModePrSkillSurfaces(unittest.TestCase):
    def test_splits_cursor_slash_from_invoker_merge_gate(self):
        # Regression lock for the 2026-08-27 /reflect: Invoker merge-gate
        # / PR-split sessions are not a Cursor /pr-skill miss. Removing
        # this distinction is the same complaint type as Cursor chat
        # 2026-08-22 (catstack #9), restated against the wrong surface.
        text = read_skill_text()
        self.assertIn("/pr-skill", text)
        self.assertIn("merge-gate", text)
        self.assertIn("invoker-make-pr", text)
        self.assertIn("Cursor-chat only", text)
        self.assertRegex(text, r"didn't\s+fire")


def normalized_skill_text():
    """Skill prose is hard-wrapped at ~76 chars; collapse whitespace so
    assertions can match a phrase without depending on exact line breaks."""
    return re.sub(r"\s+", " ", read_skill_text())


class TestCatModeCategoricalConstraints(unittest.TestCase):
    def test_absolute_negatives_are_categorical(self):
        # Regression lock: an absolute negative (only/never/any/no/do not)
        # must be modeled as a forbidden state, not a defaulted boolean or
        # optional path a later edit can silently flip back on.
        text = normalized_skill_text()
        self.assertIn("Categorical constraints & recurrence", text)
        for token in ("`only`", "`never`", "`any`", "`no`", "`do not`"):
            self.assertIn(token, text, f"missing categorical-negative token {token}")
        self.assertIn("categorical", text)
        self.assertIn("defaulted boolean", text)

    def test_newer_direct_constraint_outranks_stale_delegated_instruction(self):
        text = normalized_skill_text()
        self.assertIn("newer direct-user constraint outranks a stale delegated/task instruction", text)

    def test_recurrence_complaint_requires_history_inspection_before_edit(self):
        # "it's back" / thrash complaints must trigger cross-harness
        # conversation history plus git/task/PR history on the affected
        # files BEFORE any further edit -- not a blind re-apply.
        text = normalized_skill_text()
        self.assertIn("fixed or removed and it's back", text)
        self.assertIn("conversation history across harnesses", text)
        self.assertIn("git, task, and PR history", text)
        self.assertIn("didn't hold, before touching code again", text)

    def test_delegated_baseline_mismatch_replans_not_reconstructs(self):
        text = normalized_skill_text()
        self.assertIn("don't reconstruct that baseline from memory", text)
        self.assertIn("invalidate the plan and replan against the real state", text)

    def test_semantic_decisions_use_structure_not_regex(self):
        text = normalized_skill_text()
        self.assertIn("typed data structures or a domain parser", text)
        self.assertIn("not regex over free-form prose", text)
        self.assertIn("Reserve regex for named", text)
        self.assertIn("boundary parsers that convert external text into models", text)
        self.assertIn("never recover domain identity from proxy strings", text)


class TestCatModeInstrumentProofAndIsolation(unittest.TestCase):
    def test_loop_directive_does_not_end_with_permission_question(self):
        text = normalized_skill_text()
        self.assertIn("want me to continue?", text)
        self.assertIn("already authorized", text)

    def test_file_touching_fork_uses_own_worktree(self):
        text = normalized_skill_text()
        self.assertIn("own worktree, not the live checkout", text)
        self.assertIn("subagent's own report is not verification", text)

    def test_live_behavior_claims_need_instrument_level_proof(self):
        text = normalized_skill_text()
        self.assertIn("instrument-level proof", text)
        self.assertIn("claim type", text)
        self.assertIn("Invoking `/prove-it` once does not arm it", text)

    def test_chained_followups_survive_wait_wake(self):
        text = normalized_skill_text()
        self.assertIn("Keep named follow-ups attached to durable/background execution", text)
        self.assertIn("sleep/wake with a clock-time ETA stated to the user, never a poll loop", text)
        self.assertIn("resume without restatement", text)
        self.assertIn("Completion includes every invoked skill's required landing phase", text)
        self.assertNotIn("poll/resume", text)

    def test_analytical_deliverables_are_immediately_inspectable(self):
        text = normalized_skill_text()
        self.assertIn("Do not stop at ranked totals", text)
        self.assertIn("trace anomalies through logs and turn/event timelines", text)
        self.assertIn("recording the user's questions, hypotheses, and the evidence that answers them", text)
        self.assertIn("Extrapolate patterns only from repeated mechanisms across cases", text)
        self.assertIn("Make analytical deliverables immediately inspectable", text)
        self.assertIn("readable size", text)
        self.assertIn("explicit percentage/unit labels", text)
        self.assertIn("costs or metrics tied to causal turns/events", text)
        self.assertIn("open useful HTML instead of handing back setup instructions", text)


class TestCatModeReflect20260901Seeds(unittest.TestCase):
    # Regression locks for the five FAIL-class reflect findings routed via
    # automate-me from session 4db2ca74 (2026-09-01): each was a named
    # constraint the user had to restate, or a cross-session repeat.

    def test_hand_back_is_an_unverified_claim(self):
        text = normalized_skill_text()
        self.assertIn("A hand-back", text)
        self.assertIn("is an unverified claim", text)
        self.assertIn("name every surface tried", text)
        self.assertIn("grep the artifact already located", text)

    def test_typed_slash_command_is_checked_on_disk(self):
        text = normalized_skill_text()
        self.assertIn("A typed `/name` is a named constraint", text)
        self.assertIn("engine/CLAUDE.core.md", text)
        self.assertIn("not here, because", text)

    def test_retry_switch_resubmit_count_as_fixes_after_repro(self):
        text = normalized_skill_text()
        self.assertIn("A retry, agent switch, or resubmit is a fix, and none comes before the repro", text)

    def test_approval_is_not_a_review(self):
        text = normalized_skill_text()
        self.assertIn('never two options marked "(Recommended)"', text)
        self.assertIn("An approval question is not a review: show the plan in chat first", text)
        self.assertIn("pilot one head", text)

    def test_standing_ops_decisions_are_written_down(self):
        text = normalized_skill_text()
        self.assertIn("Standing Invoker ops decisions", text)
        self.assertIn("Digital Ocean 1 (`remote_digital_ocean_1`) is production", text)
        self.assertIn("never a checkout's `./run.sh`, nor a repo script that shells to it", text)
        self.assertIn("fix that script (PR) rather than hand-writing a sibling wrapper", text)
        self.assertIn("Periodic work is an Invoker worker, not cron", text)

    def test_interruption_gets_instrument_level_proof(self):
        text = normalized_skill_text()
        self.assertIn("An interruption or stuck state gets instrument-level proof", text)
        self.assertIn("the fix goes to a subagent", text)
        self.assertIn("A DO1 restart once looked hung on a stale PID", text)
        self.assertIn("a per-worker watchdog resurrecting mid-shutdown under real task load, not a hang", text)


class TestCatModeDoesNotRebloat(unittest.TestCase):
    def test_total_length_stays_bounded(self):
        line_count = len(read_skill_text().splitlines())
        self.assertLessEqual(
            line_count, MAX_TOTAL_LINES,
            f"cat-mode is {line_count} lines (cap {MAX_TOTAL_LINES}) -- cut per "
            "'Fix the tool, not just the instance': restructure or trim before adding more.",
        )

    def test_no_single_bullet_becomes_a_wall_of_text(self):
        text = read_skill_text()
        offenders = []
        for line in text.splitlines():
            if not line.startswith("- "):
                continue
            word_count = len(line.split())
            if word_count > MAX_BULLET_WORDS:
                offenders.append((word_count, line[:80] + "..."))
        self.assertEqual(
            offenders, [],
            f"bullet(s) exceeding {MAX_BULLET_WORDS} words -- this is exactly the "
            "CLAUDE.md class-search-bullet failure mode cat-mode itself warns against: "
            f"{offenders}",
        )


class TestCatModeExecutionRouting(unittest.TestCase):
    def test_routing_reference_exists_and_is_linked(self):
        self.assertTrue(os.path.isfile(ROUTING_REF), f"missing {ROUTING_REF}")
        skill = read_skill_text()
        self.assertIn("references/execution-routing.md", skill)
        self.assertIn("## Execution routing", skill)

    def test_routing_covers_unavailable_small_and_durable_cases(self):
        with open(ROUTING_REF, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("Invoker unavailable", text)
        self.assertIn("Small local work", text)
        self.assertIn("Approved plan or durable/parallel work", text)
        self.assertIn("invoker_prepare_plan_review", text)
        self.assertIn("reviewToken", text)
        self.assertIn("One explicit user approval", text)
        self.assertNotIn("sqlite", text.lower())
        self.assertIn("database reads", text.lower())


if __name__ == "__main__":
    unittest.main()


class TestCatModeDirectAnswers(unittest.TestCase):

    def test_own_repo_destructive_action_executes_after_verified_list(self):
        text = normalized_skill_text()
        self.assertIn("I am in control, just do it", text)
        self.assertIn("show the verified list", text)
        self.assertIn("no consent sentence, no second refusal", text)
        self.assertNotIn("hold the line", text)

    def test_any_hedge_auto_runs_prove_it(self):
        text = normalized_skill_text()
        self.assertIn("auto-runs prove-it in the same turn", text)
        self.assertIn("a hedge is a trigger to verify, never a place to stop", text)

    def test_new_root_level_files_are_listed_with_reason(self):
        text = normalized_skill_text()
        self.assertIn("New root-level files, scripts, or hooks are allowed", text)
        self.assertIn("listed in the summary with its reason", text)

    def test_land_means_ci_conflicts_and_deploy(self):
        text = normalized_skill_text()
        self.assertIn("fix CI, resolve conflicts, and deploy once merged", text)
        self.assertIn('Absent "land," deploys', text)

    def test_resume_after_accidental_interrupt_continues_in_place(self):
        text = normalized_skill_text()
        self.assertIn("continue exactly where you were", text)
        self.assertIn("no re-plan, no restart", text)

    def test_new_rules_name_prior_art_or_say_none(self):
        text = normalized_skill_text()
        self.assertIn('or says "no known prior art"', text)
        self.assertIn("[[reflect]] step 4 gates this", text)

    def test_recurring_intervention_becomes_a_hook(self):
        text = normalized_skill_text()
        self.assertIn("becomes a hook, not a memory", text)
        for hook in ("restated-constraint", "named-verb-guard", "explicit-failures"):
            self.assertIn(hook, text)

    def test_one_off_scripts_fold_into_single_entry_point(self):
        text = normalized_skill_text()
        self.assertIn("Fold one-off scripts into the single entry point as flags", text)
        self.assertIn("hardcode no names", text)

    def test_design_proposals_scan_own_history_first(self):
        text = normalized_skill_text()
        self.assertIn("The same scan precedes any design proposal", text)

    def test_worker_owned_work_is_queued_not_hand_fixed(self):
        text = normalized_skill_text()
        self.assertIn("queued to that worker, never hand-fixed", text)

    def test_proof_is_the_real_surface_and_failures_are_explicit(self):
        text = normalized_skill_text()
        self.assertIn("Proof means the real surface", text)
        self.assertIn("paste the real output into the PR summary", text)
        self.assertIn("[[principle-explicit-errors]]", text)

    def test_no_dated_provenance_remains(self):
        text = read_skill_text()
        self.assertNotRegex(text, r"\b20\d\d-\d\d-\d\d\b")
        self.assertNotIn("Found via", text)


REFERENCE_DIR = os.path.join(REPO_ROOT, "corpus", "skills", "cat-mode", "references")


def normalized_reference_text(name):
    """Same whitespace collapse as normalized_skill_text, for a references/ file."""
    with open(os.path.join(REFERENCE_DIR, name), encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


class TestCatModeReferencePackage(unittest.TestCase):
    """SKILL.md stays under its line cap by moving detail into references/,
    the same split execution-routing.md already uses. A rule that moved must
    still exist somewhere and still be reachable from SKILL.md -- these lock
    both halves so a future trim cannot quietly delete a rule instead of
    relocating it."""

    EXPECTED = (
        "autonomy.md",
        "execution-routing.md",
        "fix-the-tool.md",
        "named-constraints.md",
        "prose-and-scope.md",
        "verify.md",
    )

    def test_every_reference_file_exists_and_is_linked_from_skill_md(self):
        skill = read_skill_text()
        for name in self.EXPECTED:
            with self.subTest(reference=name):
                self.assertTrue(os.path.isfile(os.path.join(REFERENCE_DIR, name)))
                self.assertIn(f"references/{name}", skill)

    def test_no_orphan_reference_file(self):
        skill = read_skill_text()
        orphans = [
            name for name in sorted(os.listdir(REFERENCE_DIR))
            if name.endswith(".md") and f"references/{name}" not in skill
        ]
        self.assertEqual(orphans, [], f"references/ file(s) nothing links to: {orphans}")

    def test_autonomy_reference_keeps_its_rules(self):
        text = normalized_reference_text("autonomy.md")
        self.assertIn("Prefer the obvious existing mechanism before designing a new one", text)
        self.assertIn("Do not kill/restart a live Invoker `owner-serve` as the default lever", text)
        self.assertIn("stale-lock reclaim lines are successor symptoms, not crash proof", text)
        self.assertIn("Answering the opening question is a stopping point", text)

    def test_fix_the_tool_reference_keeps_its_rules(self):
        text = normalized_reference_text("fix-the-tool.md")
        self.assertIn("check whether an existing one already covers it and consolidate", text)
        self.assertIn("Skills and hooks must work the same across every harness", text)
        self.assertIn("default to restructuring it properly", text)
        self.assertIn("Apply the strongest fix first, not the fastest to write", text)
        self.assertIn("an unapplied finding is not a finding", text)

    def test_named_constraints_reference_keeps_its_rules(self):
        text = normalized_reference_text("named-constraints.md")
        self.assertIn("Admit what was not exercised", text)
        self.assertIn("Treat absolute negatives as categorical", text)
        self.assertIn("A blocked target is a stop, not a licence to substitute", text)
        self.assertIn("carries the proxy's name in the same message as the number", text)
        self.assertIn("An answer given through a tool binds exactly as hard as a typed one", text)

    def test_verify_reference_keeps_its_rules(self):
        text = normalized_reference_text("verify.md")
        self.assertIn("the repo (or its README) is the artifact-of-record", text)
        self.assertIn("Two of my own code paths disagreeing is my bug until proven otherwise", text)
        self.assertIn("Never satisfy a failing comparison with a second implementation", text)
        self.assertIn("A stated caveat does not invalidate a number", text)
        self.assertIn("Retractions cover the conversation, not just the artifacts", text)
        self.assertIn("A claim about the repo's own history is a query, not a recollection", text)

    def test_prose_and_scope_reference_keeps_its_rules(self):
        text = normalized_reference_text("prose-and-scope.md")
        self.assertIn("teach the **existing named system**", text)
        self.assertIn("Answer the literal question asked before adding related context", text)
        self.assertIn("include a regression test without asking", text)
        self.assertIn("No explanatory comments in product code, in every repo", text)
        self.assertIn("cut prose first; evidence overrides the word cap", text)


class TestCatModeClocksAndWaiting(unittest.TestCase):
    """An ETA is only useful if it is in the reader's timezone and if
    something actually re-invokes the agent at that time."""

    def test_times_are_reported_in_the_users_timezone(self):
        text = normalized_skill_text()
        self.assertIn("Report times in the user's timezone, never UTC", text)
        self.assertIn("Read it rather than assuming", text)

    def test_timezone_commands_are_written_as_invocations_not_bare_names(self):
        """A bare backticked lowercase token reads as a skill reference to
        test_every_referenced_skill_still_exists. A command reference carries
        its arguments, so it cannot be mistaken for one."""
        text = read_skill_text()
        self.assertIn("`timedatectl status`", text)
        self.assertNotIn("`timedatectl`", text)

    def test_an_eta_is_paired_with_a_scheduled_wakeup(self):
        text = normalized_skill_text()
        self.assertIn("An ETA and a scheduled wakeup are one thing, not two", text)
        self.assertIn("`ScheduleWakeup`", text)
        self.assertIn("Satisfying half of a gate is worse than tripping it", text)
