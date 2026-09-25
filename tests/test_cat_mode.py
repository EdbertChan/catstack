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
import importlib.util
import json
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
MAX_TOTAL_LINES = 330
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
        self.assertIn("Applied by default when `CATSTACK_CAT_MODE_DEFAULT=on` via the `cat-mode-default` hook", text)
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
            "invoker-route-delegation",
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
            "all",
            "every",
            "each",
            "categorical-scope-guard",
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
        self.assertIn("scoped to Cursor chat", text)
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

    def test_positive_quantifiers_are_categorical_and_name_the_guard_hook(self):
        text = normalized_skill_text()
        for token in ("`all`", "`every`", "`each`"):
            self.assertIn(token, text, f"missing categorical-positive token {token}")
        self.assertIn("categorical-scope-guard", text)
        self.assertTrue(os.path.isdir(os.path.join(REPO_ROOT, "engine", "hooks", "categorical-scope-guard")))

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

    def test_decisions_read_recorded_state_not_error_text(self):
        """A substring check on an error message is regex over prose under
        another name. SKILL.md keeps the one-line rule; named-constraints.md
        keeps the full text and its sources, so a trim cannot drop either."""
        skill = normalized_skill_text()
        self.assertIn("Error, log, and exit text is for humans", skill)
        self.assertIn("decide retry, cap, or status from the recorded state that drives it", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("Error, log, and exit text is for humans", reference)
        self.assertIn("a launch-completed timestamp, a typed failure class, a gate's state file", reference)
        self.assertIn("A substring check on an error string is regex by another name", reference)
        self.assertIn("Extending an existing text-match table is not precedent", reference)
        self.assertIn("replace it with the state", reference)
        self.assertIn("exists for humans, not code", reference)
        self.assertIn("https://dave.cheney.net/2016/04/27/dont-just-check-errors-handle-them-gracefully", reference)
        self.assertIn("https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/", reference)

    def test_a_value_seen_only_in_an_error_string_is_not_reported_as_fact(self):
        """Deciding from recorded state and reporting from it are different
        halves: a setting copied out of an error message reaches the user as a
        reading of that setting, which it never was."""
        skill = normalized_skill_text()
        self.assertIn(
            "report a setting, capability or count from whatever owns it, "
            "never from an error string that named it",
            skill,
        )

    def test_an_open_pr_is_checked_for_supersession_before_a_land(self):
        """Open state records nothing about whether later merged work already
        covers the claim, so the rule names the gate that reads direction
        rather than leaving the reader to judge a file listing."""
        skill = normalized_skill_text()
        self.assertIn("An open PR is not evidence it is still needed", skill)
        self.assertIn("scripts/ci/check_branch_not_superseded.py", skill)
        gate = os.path.join(REPO_ROOT, "scripts", "ci", "check_branch_not_superseded.py")
        self.assertTrue(os.path.exists(gate), f"cat-mode names a gate that is not on disk: {gate}")

    def test_tool_and_agent_output_is_not_a_decision_input(self):
        """The rule covers tool and agent output, not only failures. Dropping
        the clause from SKILL.md or named-constraints.md fails here."""
        skill = normalized_skill_text()
        self.assertIn("tool and agent output", skill)
        self.assertIn("read `--output json`, API fields, exit codes", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("**Tool and agent output.**", reference)
        self.assertIn("CLI stdout, PR and issue comments, CI logs, and model replies", reference)
        self.assertIn("Decide from the structured field or JSON output when one exists", reference)
        self.assertIn("never by matching the human-readable text", reference)

    def test_plan_and_task_prose_is_not_a_decision_input(self):
        """The rule covers plan and task prose, not only failures. Dropping
        the clause from SKILL.md or named-constraints.md fails here."""
        skill = normalized_skill_text()
        self.assertIn("plan and task prose", skill)
        self.assertIn("read typed plan and task fields", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("**Plan and task prose.**", reference)
        self.assertIn("comes from typed plan and task fields, not regex over descriptions or prompts", reference)

    def test_type_discipline_principle_points_at_the_error_text_rule(self):
        path = os.path.join(REPO_ROOT, "corpus", "skills", "principle-type-system-discipline", "SKILL.md")
        with open(path, encoding="utf-8") as handle:
            text = re.sub(r"\s+", " ", handle.read())
        self.assertIn("Error, log, and exit text is external data too", text)
        self.assertIn("cat-mode", text)


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

    def test_helper_reported_block_is_tried_in_the_main_session(self):
        """A subagent's guard block does not bind the parent: session 189436d4
        handed the user publish scripts for 66 minutes on a helper's report."""
        text = normalized_skill_text()
        self.assertIn("First try the step once in the main session", text)
        self.assertIn("a block a helper reports is the helper's, not yours", text)

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
        """Demoted out of SKILL.md into the routing reference to make room for
        the precedence rule under the line cap. SKILL.md must still point at
        them; the reference must still hold every one, or this trim deleted a
        rule rather than relocating it."""
        skill = normalized_skill_text()
        self.assertIn(
            "**Standing Invoker ops decisions** (production host, live-owner access, "
            "worker-owned periodic work) live in that reference",
            skill,
        )
        self.assertNotIn("Digital Ocean 1", skill)
        text = normalized_reference_text("execution-routing.md")
        self.assertIn("Standing Invoker ops decisions", text)
        self.assertIn("Digital Ocean 1 (`remote_digital_ocean_1`) is production", text)
        self.assertIn("never a checkout's `./run.sh`, nor a repo script that shells to it", text)
        self.assertIn("fix that script (PR) rather than hand-writing a sibling wrapper", text)
        self.assertIn("Periodic work is an Invoker worker, not cron", text)
        self.assertIn("queued to that worker, never hand-fixed", text)

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


class TestEscapeHatchVocabulary(unittest.TestCase):
    """cat-mode is always loaded, so an instruction here to write the retired
    bare `UNVERIFIED:` would send every session into a block."""

    def test_skill_and_verify_reference_name_the_tag_not_the_retired_marker(self):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import escape_hatch_vocab as vocab
        verify_ref = os.path.join(os.path.dirname(SKILL_PATH), "references", "verify.md")
        for path in (SKILL_PATH, verify_ref):
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertEqual(vocab.instructs_retired_marker(text), [], path)
            self.assertIn("CAT-UNVERIFIED", text, path)


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

    def test_autonomy_standing_rule_grounds_the_never_block_principle(self):
        """The standing act-don't-ask rule names the principle it instantiates.

        Pinned because cat-mode is trimmed under a hard line cap: without an
        assertion, a future trim drops the citation and the rule reads as a
        personal preference rather than an instance of a named principle.
        """
        text = normalized_skill_text()
        self.assertIn("[[principle-never-block-on-the-human]]", text)
        self.assertIn("a reversible decision costs", text)

    def test_blocked_handback_relays_the_gate_exit_verbatim(self):
        """A summarized gate message can drop the one step that unblocks the
        user, so the rule demands the exit text and the marker it names."""
        text = normalized_skill_text()
        self.assertIn("relays the gate's exit word for word", text)
        self.assertIn("unshortened", text)

    def test_read_a_gate_before_judging_it_cites_chestertons_fence(self):
        """Pinned because cat-mode is trimmed under a hard line cap: without an
        assertion a future trim drops the fence citation, and the rule reads as
        a style note rather than a named prior-art principle."""
        text = normalized_skill_text()
        self.assertIn("Read a gate before calling it broken", text)
        self.assertIn("Chesterton's fence", text)
        self.assertIn("unchecked, not clean", text)

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
        """Relocated with the rest of the standing ops decisions."""
        self.assertIn("queued to that worker, never hand-fixed", normalized_reference_text("execution-routing.md"))
        self.assertNotIn("queued to that worker", normalized_skill_text())

    def test_proof_is_the_real_surface_and_failures_are_explicit(self):
        text = normalized_skill_text()
        self.assertIn("Proof means the real surface", text)
        self.assertIn("paste the real output into the PR summary", text)
        self.assertIn("[[principle-explicit-errors]]", text)

    def test_done_gate_covers_the_users_own_machine_not_only_external_services(self):
        """The two e2e bullets were once removed as a duplicate of the global
        rule, which only fires on UI/layout work or on a test the user asked
        for. Work that is neither -- an agent opening windows on the user's
        own desktop -- then had no trigger at all. The surfaces stay named in
        SKILL.md itself, not only in the reference it points at, because a
        pointer narrower than the text it replaces is what failed."""
        text = normalized_skill_text()
        self.assertIn("A done-gate is the real path, not the layers under it", text)
        self.assertIn("the user's own machine, session, or screen", text)
        self.assertIn("each layer proved separately is not the property proved", text)
        self.assertIn("run the named e2e end to end the way a user would", text)

    def test_declining_to_run_the_real_path_is_not_a_blocker(self):
        text = normalized_skill_text()
        self.assertIn('"I chose not to run it" is not a blocker', text)

    def test_admit_what_was_not_exercised_enumerates_against_the_done_gate(self):
        text = normalized_skill_text()
        self.assertIn("Admit what was not exercised", text)
        self.assertIn("for each named layer, say whether the real path through it ran", text)

    def test_no_dated_provenance_remains(self):
        text = read_skill_text()
        self.assertNotRegex(text, r"\b20\d\d-\d\d-\d\d\b")
        self.assertNotIn("Found via", text)


class TestCatModeTargetProofRules(unittest.TestCase):
    """General, repo-independent rules: proof must match the layer the claim
    names, a target's live identity gets re-resolved right before a mutation
    (not read from an earlier listing), and missing repro evidence is a stop
    rather than license to fix on hypothesis."""

    def test_proof_must_match_the_claimed_layer(self):
        skill = normalized_skill_text()
        self.assertIn("Proof must come from the layer the claim names", skill)
        self.assertIn("Say which layer the evidence actually came from", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("Proof must match the layer the claim names, not merely a layer", reference)
        self.assertIn("A write succeeding is not a UI showing it", reference)
        self.assertIn("a queue accepting a job is not the job having run", reference)

    def test_target_identity_is_re_resolved_before_mutation(self):
        skill = normalized_skill_text()
        self.assertIn(
            "Re-resolve a target's live identity immediately before mutating it; "
            "an earlier listing is not standing authorization",
            skill,
        )
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn(
            "Re-resolve a target's live identity immediately before the action that "
            "mutates it; an earlier listing is not standing authorization to act on "
            "what it named",
            reference,
        )
        self.assertIn("can now point at a different live thing, or the original thing can", reference)
        self.assertIn("have moved or been replaced", reference)
        self.assertIn("This differs from the blocked-target rule", reference)

    def test_missing_repro_evidence_is_a_stop_not_a_license_to_guess(self):
        skill = normalized_skill_text()
        self.assertIn("Repro evidence that can't be gathered is a stop, not licence to fix", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("Repro evidence that genuinely can't be gathered is a stop, not", reference)
        self.assertIn(
            "the environment, data, or access needed to trigger it is unavailable",
            reference,
        )
        self.assertIn("only that the code changed", reference)

    def test_target_identity_comes_from_the_owner_and_ambiguity_is_a_stop(self):
        skill = normalized_skill_text()
        self.assertIn("Read it from the system that owns the target", skill)
        self.assertIn("no match or several matches is a stop, never a pick", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("Read identity from the system that owns the target", reference)
        self.assertIn("a name that looks closest is a guess", reference)
        self.assertIn("No match, or more than one match, is a stop", reference)

    def test_unreachable_claimed_layer_is_a_stop_not_a_relabel(self):
        skill = normalized_skill_text()
        self.assertIn("If that layer can't be exercised, stop and tag the claim", skill)
        self.assertIn("never relabel lower-layer evidence as it", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("When the layer the claim names cannot be exercised", reference)
        self.assertIn("never describe, reconstruct, or simulate what it would have shown", reference)


class TestCatModeSubagentPrecedence(unittest.TestCase):
    """Two sections used to fire on the same work and point opposite ways:
    the Subagents default ("delegate whenever separable ... default to
    parallel") and Execution routing ("delegate durable/parallel work to
    Invoker"). Whichever an agent read first won. These lock the tiebreak in
    both directions, in both sections, so neither can be read alone as
    authorization to fan out publishing work."""

    def test_subagent_default_is_scoped_to_non_publishing_work(self):
        text = normalized_skill_text()
        self.assertIn("This default governs read-only and non-publishing delegation", text)

    def test_subagents_section_yields_to_execution_routing_on_publishing_work(self):
        text = normalized_skill_text()
        self.assertIn(
            "**Execution routing wins whenever the work produces a commit, a PR, or a durable artifact.**",
            text,
        )
        self.assertIn("Separable and parallel is not authorization to fan out", text)

    def test_execution_routing_section_states_the_same_precedence(self):
        text = normalized_skill_text()
        self.assertIn(
            "**This section outranks the Subagents default whenever the work produces a "
            "commit, a PR, or a durable artifact.**",
            text,
        )

    def test_precedence_is_backed_by_the_executable_table(self):
        text = read_skill_text()
        self.assertIn("`scripts/route_execution.py`", text)
        script = os.path.join(REPO_ROOT, "corpus", "skills", "cat-mode", "scripts", "route_execution.py")
        with open(script, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("def route_delegation(", source)
        self.assertIn("PUBLISHING_OUTPUTS", source)
        self.assertIn("subagent_fanout", source)


class TestFleetUpkeepLever(unittest.TestCase):
    """The fleet-upkeep rule names a script, and that script exists, runs, and
    reports a row per host rather than failing silently. Written after the same
    "put every machine on the new Invoker and the current catstack" request
    arrived twice and was hand-run both times."""

    SCRIPT = os.path.join(
        REPO_ROOT, "corpus", "skills", "cat-mode", "scripts", "update_fleet.sh"
    )

    def test_skill_points_at_the_script(self):
        self.assertIn("`scripts/update_fleet.sh`", read_skill_text())

    def test_script_exists_and_is_executable(self):
        self.assertTrue(os.path.isfile(self.SCRIPT), self.SCRIPT)
        self.assertTrue(os.access(self.SCRIPT, os.X_OK), "update_fleet.sh is not executable")

    def test_script_parses_and_help_lists_every_flag(self):
        import subprocess

        syntax = subprocess.run(["bash", "-n", self.SCRIPT], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        help_out = subprocess.run(
            ["bash", self.SCRIPT, "--help"], capture_output=True, text=True
        )
        self.assertEqual(help_out.returncode, 0, help_out.stderr)
        for flag in ("--version", "--hosts", "--skip-invoker", "--skip-catstack",
                     "--with-app", "--dry-run"):
            self.assertIn(flag, help_out.stdout)

    def test_unknown_flag_fails_loudly(self):
        import subprocess

        out = subprocess.run(
            ["bash", self.SCRIPT, "--not-a-flag"], capture_output=True, text=True
        )
        self.assertEqual(out.returncode, 64)
        self.assertIn("unknown argument", out.stderr)

    def test_unreachable_or_unreadable_hosts_never_read_as_ok(self):
        """A host it could not check gets a fail row, not silence -- the
        three-outcome rule (hit / clean / unchecked) applied to upkeep."""
        with open(self.SCRIPT, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('row fail "$id" "ssh failed; version unchecked"', source)
        self.assertIn("catstack: install did not report an exit code", source)
        self.assertIn("exit \"$FAILED\"", source)

    def test_catstack_checkout_is_resolved_from_installed_links(self):
        """A host can hold more than one catstack checkout; the live one is
        whichever the installed skill symlinks point into, not the first hit
        of a directory listing."""
        with open(self.SCRIPT, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('for s in "$HOME"/.claude/skills/*', source)
        self.assertIn("readlink", source)

    def test_remote_install_does_not_let_install_sh_eat_the_script(self):
        """install.sh reads stdin; without </dev/null it swallows the rest of
        a heredoc-fed remote script and the run reports nothing."""
        with open(self.SCRIPT, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("./install.sh > /tmp/catstack-install.log 2>&1 </dev/null", source)

    def test_script_carries_no_comments(self):
        """Comments are banned in code repo-wide, and CI fails the PR on any
        added one. The header block that used to hold the usage text is a
        heredoc in usage() now, so --help does not depend on comments either."""
        spec = importlib.util.spec_from_file_location(
            "no_comments_detect",
            os.path.join(REPO_ROOT, "engine", "hooks", "no-comments", "detect.py"),
        )
        detect = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(detect)
        with open(self.SCRIPT, encoding="utf-8") as handle:
            source = handle.read()
        hits = detect.comment_lines("scripts/update_fleet.sh", source)
        self.assertEqual(hits, [], "\n".join(hits))


APP_FUNCTIONS = re.compile(r"^local_invoker\(\) \{.*?(?=^write_payloads\(\) \{)", re.S | re.M)

HARNESS = """set -uo pipefail
APP_DIR="$TEST_APP_DIR"
WORK_DIR="$TEST_WORK_DIR"
RELEASE_VERSION="9.9.9"
DRY_RUN="${{TEST_DRY_RUN:-0}}"
row() {{ printf '%s\\t%s\\t%s\\n' "$1" "$2" "$3" >> "$TEST_ROWS"; return 0; }}
fetch_asset() {{ printf '%s' "$WORK_DIR/Invoker.dmg"; }}
{functions}
local_app
echo "RC=$?"
"""

STUBS = {
    "uname": 'case "${1:-}" in -m) echo arm64 ;; *) echo Darwin ;; esac\n',
    "osascript": "exit 0\n",
    "hdiutil": (
        'if [ "$1" = attach ]; then\n'
        '  mount="$4"\n'
        '  mkdir -p "$mount/Invoker.app/Contents"\n'
        '  printf \'%s\\n\' "${TEST_DMG_VERSION:-9.9.9}" > "$mount/Invoker.app/version"\n'
        "fi\n"
        "exit 0\n"
    ),
    "defaults": (
        'file="${2%/Contents/Info.plist}/version"\n'
        '[ -f "$file" ] || exit 1\n'
        'cat "$file"\n'
    ),
}

FAILING_CP = "exit 1\n"


def run_local_app(script_path, tmp, dmg_version="9.9.9", cp_fails=False, dry_run=False):
    """Run update_fleet.sh's app-replace step alone, against a fake /Applications.

    The local-Mac section is sliced out of the real script and sourced into a
    harness so the test exercises the shipped code, not a copy of it. The dmg,
    the mount, `defaults`, `hdiutil` and `osascript` are stubbed on PATH; a
    bundle's version is a plain file the `defaults` stub reads.
    """
    import stat
    import subprocess

    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    stubs = dict(STUBS)
    if cp_fails:
        stubs["cp"] = FAILING_CP
    for name, body in stubs.items():
        stub = os.path.join(bin_dir, name)
        with open(stub, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/bash\n" + body)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)

    app_dir = os.path.join(tmp, "Applications")
    work_dir = os.path.join(tmp, "work")
    rows = os.path.join(tmp, "rows.tsv")
    os.makedirs(app_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    open(os.path.join(work_dir, "Invoker.dmg"), "w").close()
    open(rows, "w").close()

    with open(script_path, encoding="utf-8") as handle:
        source = handle.read()
    match = APP_FUNCTIONS.search(source)
    if match is None:
        raise AssertionError("could not slice the local-Mac section out of the script")
    harness = os.path.join(tmp, "harness.sh")
    with open(harness, "w", encoding="utf-8") as handle:
        handle.write(HARNESS.format(functions=match.group(0)))

    env = dict(os.environ)
    env.update(
        PATH=bin_dir + os.pathsep + env["PATH"],
        TEST_APP_DIR=app_dir,
        TEST_WORK_DIR=work_dir,
        TEST_ROWS=rows,
        TEST_DMG_VERSION=dmg_version,
        TEST_DRY_RUN="1" if dry_run else "0",
    )
    out = subprocess.run(["bash", harness], capture_output=True, text=True, env=env)
    with open(rows, encoding="utf-8") as handle:
        row = handle.read().strip()
    return app_dir, row, out


def write_bundle(app_dir, name, version):
    os.makedirs(os.path.join(app_dir, name, "Contents"), exist_ok=True)
    with open(os.path.join(app_dir, name, "version"), "w", encoding="utf-8") as handle:
        handle.write(version + "\n")


def bundle_version(app_dir, name):
    path = os.path.join(app_dir, name, "version")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


class TestAppReplaceNeverReportsAFailureAsOk(unittest.TestCase):
    """--with-app quits the live owner and swaps the bundle. The first version
    moved the app aside, copied over it, and recorded `ok` whatever happened --
    and it cleared Invoker.app.old first, so a replace that died after the move
    left the backup as the only copy and the next run deleted it. Every case
    here runs the shipped functions against a fake /Applications."""

    SCRIPT = os.path.join(
        REPO_ROOT, "corpus", "skills", "cat-mode", "scripts", "update_fleet.sh"
    )

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="fleet-app-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_failed_copy_reports_fail_and_puts_the_old_bundle_back(self):
        app_dir = os.path.join(self.tmp, "Applications")
        os.makedirs(app_dir, exist_ok=True)
        write_bundle(app_dir, "Invoker.app", "1.0.0")

        app_dir, row, out = run_local_app(self.SCRIPT, self.tmp, cp_fails=True)

        self.assertTrue(row.startswith("fail\t"), f"row was {row!r}\n{out.stderr}")
        self.assertEqual(bundle_version(app_dir, "Invoker.app"), "1.0.0", row)
        leftovers = [n for n in os.listdir(app_dir) if ".replacing." in n]
        self.assertEqual(leftovers, [], f"parked bundle left behind: {leftovers}")

    def test_a_failed_copy_never_deletes_the_backup_from_an_earlier_run(self):
        """The reported bug in its worst shape: a previous replace already died
        after the move, so Invoker.app.old is the only bundle left on the Mac."""
        app_dir = os.path.join(self.tmp, "Applications")
        os.makedirs(app_dir, exist_ok=True)
        write_bundle(app_dir, "Invoker.app.old", "1.0.0")

        app_dir, row, out = run_local_app(self.SCRIPT, self.tmp, cp_fails=True)

        self.assertTrue(row.startswith("fail\t"), f"row was {row!r}\n{out.stderr}")
        self.assertEqual(bundle_version(app_dir, "Invoker.app.old"), "1.0.0", row)

    def test_a_copied_bundle_that_reads_the_wrong_version_is_not_ok(self):
        app_dir = os.path.join(self.tmp, "Applications")
        os.makedirs(app_dir, exist_ok=True)
        write_bundle(app_dir, "Invoker.app", "1.0.0")

        app_dir, row, out = run_local_app(self.SCRIPT, self.tmp, dmg_version="0.0.1")

        self.assertTrue(row.startswith("fail\t"), f"row was {row!r}\n{out.stderr}")
        self.assertIn("wanted 9.9.9", row)
        self.assertEqual(bundle_version(app_dir, "Invoker.app"), "1.0.0", row)

    def test_a_good_replace_reports_ok_and_keeps_the_previous_bundle(self):
        app_dir = os.path.join(self.tmp, "Applications")
        os.makedirs(app_dir, exist_ok=True)
        write_bundle(app_dir, "Invoker.app", "1.0.0")

        app_dir, row, out = run_local_app(self.SCRIPT, self.tmp)

        self.assertTrue(row.startswith("ok\t"), f"row was {row!r}\n{out.stderr}")
        self.assertEqual(bundle_version(app_dir, "Invoker.app"), "9.9.9", row)
        self.assertEqual(bundle_version(app_dir, "Invoker.app.old"), "1.0.0", row)
        leftovers = [n for n in os.listdir(app_dir) if ".replacing." in n]
        self.assertEqual(leftovers, [], f"parked bundle left behind: {leftovers}")

    def test_a_park_beside_a_killed_copy_is_put_back_before_the_retry(self):
        """A SIGKILL mid `cp -R` cannot be trapped. It leaves a partial
        Invoker.app beside the parked original. The next run has to trust the
        park, not the partial, or a failed retry restores the partial and the
        good bundle is lost."""
        app_dir = os.path.join(self.tmp, "Applications")
        os.makedirs(app_dir, exist_ok=True)
        write_bundle(app_dir, "Invoker.app", "partial")
        write_bundle(app_dir, "Invoker.app.replacing.4242", "1.0.0")

        app_dir, row, out = run_local_app(self.SCRIPT, self.tmp, cp_fails=True)

        self.assertTrue(row.startswith("fail\t"), f"row was {row!r}\n{out.stderr}")
        self.assertEqual(bundle_version(app_dir, "Invoker.app"), "1.0.0", row)
        leftovers = [n for n in os.listdir(app_dir) if ".replacing." in n]
        self.assertEqual(leftovers, [], f"parked bundle left behind: {leftovers}")

    def test_dry_run_warns_on_a_park_beside_a_killed_copy(self):
        app_dir = os.path.join(self.tmp, "Applications")
        os.makedirs(app_dir, exist_ok=True)
        write_bundle(app_dir, "Invoker.app", "partial")
        write_bundle(app_dir, "Invoker.app.replacing.4242", "1.0.0")

        app_dir, row, out = run_local_app(self.SCRIPT, self.tmp, dry_run=True)

        self.assertTrue(row.startswith("warn\t"), f"row was {row!r}\n{out.stderr}")
        self.assertIn("Invoker.app.replacing.4242", row)
        self.assertEqual(bundle_version(app_dir, "Invoker.app.replacing.4242"), "1.0.0", row)


CATSTACK_FUNCTIONS = re.compile(r"^write_payloads\(\) \{.*?(?=^write_payloads$)", re.S | re.M)

CATSTACK_HARNESS = """set -uo pipefail
WORK_DIR="$TEST_WORK_DIR"
RELEASE_VERSION="9.9.9"
DRY_RUN=1
row() {{ printf '%s\\t%s\\t%s\\n' "$1" "$2" "$3" >> "$TEST_ROWS"; return 0; }}
{functions}
ssh_to() {{ return "${{TEST_SSH_RC:-0}}"; }}
write_payloads
catstack_on "$TEST_ID" "$TEST_DEST"
echo "RC=$?"
"""


def run_catstack_dry_run(script_path, tmp, dest, home, scp_fails=False, ssh_rc=0):
    """Run update_fleet.sh's catstack step alone, in --dry-run, against a fake
    HOME. The step is sliced out of the real script and sourced into a harness
    so the test exercises the shipped code, not a copy of it -- same shape as
    run_local_app above. `scp` is stubbed on PATH; `ssh_to` is replaced with a
    stub whose exit code the caller picks."""
    import stat
    import subprocess

    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    scp_stub = os.path.join(bin_dir, "scp")
    with open(scp_stub, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/bash\nexit %d\n" % (1 if scp_fails else 0))
    os.chmod(scp_stub, os.stat(scp_stub).st_mode | stat.S_IXUSR)

    work_dir = os.path.join(tmp, "work")
    rows = os.path.join(tmp, "rows.tsv")
    os.makedirs(work_dir, exist_ok=True)
    open(rows, "w").close()

    with open(script_path, encoding="utf-8") as handle:
        source = handle.read()
    match = CATSTACK_FUNCTIONS.search(source)
    if match is None:
        raise AssertionError("could not slice the catstack section out of the script")
    harness = os.path.join(tmp, "catstack-harness.sh")
    with open(harness, "w", encoding="utf-8") as handle:
        handle.write(CATSTACK_HARNESS.format(functions=match.group(0)))

    env = dict(os.environ)
    env.update(
        PATH=bin_dir + os.pathsep + env["PATH"],
        HOME=home,
        TEST_WORK_DIR=work_dir,
        TEST_ROWS=rows,
        TEST_ID="hostA",
        TEST_DEST=dest,
        TEST_SSH_RC=str(ssh_rc),
    )
    out = subprocess.run(["bash", harness], capture_output=True, text=True, env=env)
    with open(rows, encoding="utf-8") as handle:
        row = handle.read().strip()
    return row, out


def make_fake_checkout(home):
    """A HOME whose installed skill symlink points into a real git checkout,
    the way the payload resolves the live one. install.sh drops a marker so a
    dry-run that installed anything is visible."""
    import subprocess

    repo = os.path.join(home, "catstack")
    os.makedirs(os.path.join(repo, "corpus", "skills", "cat-mode"), exist_ok=True)
    install = os.path.join(repo, "install.sh")
    with open(install, "w", encoding="utf-8") as handle:
        handle.write('#!/bin/bash\ntouch "$HOME/INSTALL_RAN"\n')
    os.chmod(install, 0o755)
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", repo]
    subprocess.run(git[:1] + ["-C", repo, "init", "-q"], check=True, capture_output=True)
    subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-qm", "seed"], check=True, capture_output=True)

    skills = os.path.join(home, ".claude", "skills")
    os.makedirs(skills, exist_ok=True)
    os.symlink(os.path.join(repo, "corpus", "skills", "cat-mode"),
               os.path.join(skills, "cat-mode"))
    return repo


class TestDryRunNeverMarksAnUncheckedHostOk(unittest.TestCase):
    """--dry-run used to record `ok` for catstack before touching the host, so
    `--skip-invoker --dry-run` -- the one mode where nothing else SSHes --
    printed ok rows and exit 0 for hosts that were never reached. A dry-run row
    is earned by a real check: hit, clean, or unchecked, never clean by
    default."""

    SCRIPT = os.path.join(
        REPO_ROOT, "corpus", "skills", "cat-mode", "scripts", "update_fleet.sh"
    )

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="fleet-dry-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home, exist_ok=True)

    def test_an_unreachable_host_is_a_fail_row_not_ok(self):
        row, out = run_catstack_dry_run(
            self.SCRIPT, self.tmp, "me@hostA", self.home, scp_fails=True
        )

        self.assertTrue(row.startswith("fail\t"), f"row was {row!r}\n{out.stderr}")
        self.assertIn("unchecked", row)

    def test_a_host_that_answers_with_nothing_is_a_fail_row_not_ok(self):
        row, out = run_catstack_dry_run(
            self.SCRIPT, self.tmp, "me@hostA", self.home, ssh_rc=255
        )

        self.assertTrue(row.startswith("fail\t"), f"row was {row!r}\n{out.stderr}")

    def test_a_host_with_no_checkout_is_a_fail_row_not_ok(self):
        row, out = run_catstack_dry_run(self.SCRIPT, self.tmp, "local", self.home)

        self.assertTrue(row.startswith("fail\t"), f"row was {row!r}\n{out.stderr}")
        self.assertIn("no checkout", row)

    def test_a_checked_host_reports_ok_and_changes_nothing(self):
        import subprocess

        repo = make_fake_checkout(self.home)
        head = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        row, out = run_catstack_dry_run(self.SCRIPT, self.tmp, "local", self.home)

        self.assertTrue(row.startswith("ok\t"), f"row was {row!r}\n{out.stderr}")
        self.assertIn(head, row)
        self.assertIn("dry-run", row)
        self.assertFalse(
            os.path.exists(os.path.join(self.home, "INSTALL_RAN")),
            "a dry-run ran install.sh",
        )


def write_stub(bin_dir, name, body):
    import stat

    path = os.path.join(bin_dir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/bash\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def run_fleet(script_path, tmp, args, targets):
    """Run the whole shipped update_fleet.sh with `gh` failing, every `scp`
    failing, and a fake HOME with no catstack checkout, so every host ends in a
    row without any network call."""
    import json
    import subprocess

    bin_dir = os.path.join(tmp, "bin")
    home = os.path.join(tmp, "home")
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(home, exist_ok=True)
    write_stub(bin_dir, "gh", "echo 'gh: no network in this test' >&2\nexit 1\n")
    write_stub(bin_dir, "scp", "exit 1\n")
    write_stub(bin_dir, "ssh", "exit 255\n")
    config = os.path.join(tmp, "config.json")
    with open(config, "w", encoding="utf-8") as handle:
        json.dump({"remoteTargets": targets}, handle)
    env = dict(os.environ)
    env.update(PATH=bin_dir + os.pathsep + env["PATH"], HOME=home, INVOKER_CONFIG=config)
    return subprocess.run(
        ["bash", script_path] + args, capture_output=True, text=True, env=env
    )


class TestFleetFlagsDoWhatTheySay(unittest.TestCase):
    """--skip-invoker has to keep a catstack-only run away from the Invoker
    release lookup, and --hosts has to account for every id it was handed."""

    SCRIPT = os.path.join(
        REPO_ROOT, "corpus", "skills", "cat-mode", "scripts", "update_fleet.sh"
    )
    TARGETS = {"hostA": {"host": "10.0.0.1", "user": "me"}}

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="fleet-flags-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_skip_invoker_never_needs_a_release(self):
        out = run_fleet(self.SCRIPT, self.tmp, ["--skip-invoker"], self.TARGETS)

        self.assertNotIn("daily-*", out.stderr)
        self.assertNotIn("invoker-cli asset", out.stderr)
        self.assertIn("STATUS", out.stdout, out.stderr)
        self.assertRegex(out.stdout, r"fail\s+hostA\s+catstack: scp")

    def test_an_unknown_host_id_gets_a_fail_row(self):
        out = run_fleet(
            self.SCRIPT, self.tmp, ["--skip-invoker", "--hosts", "hostA,hostTypo"],
            self.TARGETS,
        )

        self.assertRegex(out.stdout, r"fail\s+hostTypo\s+not in remoteTargets", out.stderr)
        self.assertRegex(out.stdout, r"fail\s+hostA\s+")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)

    def test_only_unknown_host_ids_still_fail_each_by_name(self):
        out = run_fleet(
            self.SCRIPT, self.tmp, ["--skip-invoker", "--skip-catstack", "--hosts", "nope"],
            self.TARGETS,
        )

        self.assertRegex(out.stdout, r"fail\s+nope\s+not in remoteTargets", out.stderr)
        self.assertEqual(out.returncode, 1)


REMOTE_INVOKER_HARNESS = """set -uo pipefail
WORK_DIR="$TEST_WORK_DIR"
RELEASE_VERSION="9.9.9"
DRY_RUN=0
row() {{ printf '%s\\t%s\\t%s\\n' "$1" "$2" "$3" >> "$TEST_ROWS"; return 0; }}
{functions}
fetch_asset() {{ printf '%s' "$TEST_TARBALL"; }}
ssh_to() {{ shift; local cmd="$*"; env -i HOME="$TEST_REMOTE_HOME" PATH="$TEST_SSH_PATH" bash -c "${{cmd//\\/tmp\\//$TEST_REMOTE_TMP/}}"; }}
scp() {{ local a; for a in "$@"; do case "$a" in -*|BatchMode=*|ConnectTimeout=*|*:/tmp/) ;; *) cp "$a" "$TEST_REMOTE_TMP/" ;; esac; done; }}
write_payloads
remote_invoker hostA me@hostA
echo "RC=$?"
"""


def run_remote_invoker(script_path, tmp, sudo_ok, local_bin_on_path=False):
    """Run update_fleet.sh's remote_invoker step against a fake remote: `ssh_to`
    runs the command locally under a clean non-interactive environment (no
    .bashrc) with the fake remote HOME, the same PATH a real `ssh host cmd`
    gets when nothing adds ~/.local/bin."""
    import subprocess
    import tarfile

    bin_dir = os.path.join(tmp, "ssh-bin")
    remote_home = os.path.join(tmp, "remote-home")
    remote_tmp = os.path.join(tmp, "remote-tmp")
    work_dir = os.path.join(tmp, "work")
    for d in (bin_dir, remote_home, remote_tmp, work_dir):
        os.makedirs(d, exist_ok=True)
    write_stub(bin_dir, "sudo", "exit 0\n" if sudo_ok else "exit 1\n")
    write_stub(bin_dir, "uname", "echo x86_64\n")

    pkg = os.path.join(tmp, "pkg", "invoker-cli-9.9.9-linux-x64")
    os.makedirs(pkg, exist_ok=True)
    write_stub(pkg, "invoker-cli", "echo 9.9.9\n")
    tarball = os.path.join(work_dir, "invoker-cli-9.9.9-linux-x64.tar.gz")
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(pkg, arcname="invoker-cli-9.9.9-linux-x64")

    with open(script_path, encoding="utf-8") as handle:
        source = handle.read()
    match = CATSTACK_FUNCTIONS.search(source)
    if match is None:
        raise AssertionError("could not slice the payload section out of the script")
    harness = os.path.join(tmp, "remote-invoker-harness.sh")
    with open(harness, "w", encoding="utf-8") as handle:
        handle.write(REMOTE_INVOKER_HARNESS.format(functions=match.group(0)))

    rows = os.path.join(tmp, "rows.tsv")
    open(rows, "w").close()
    env = dict(os.environ)
    env.update(
        TEST_WORK_DIR=work_dir,
        TEST_ROWS=rows,
        TEST_TARBALL=tarball,
        TEST_REMOTE_HOME=remote_home,
        TEST_REMOTE_TMP=remote_tmp,
        TEST_SSH_PATH=(
            os.path.join(remote_home, ".local", "bin") + ":" if local_bin_on_path else ""
        ) + bin_dir + ":/usr/bin:/bin",
    )
    out = subprocess.run(["bash", harness], capture_output=True, text=True, env=env)
    with open(rows, encoding="utf-8") as handle:
        row = handle.read().strip()
    return row, out


class TestRemoteInstallOffTheSshPathIsNotOk(unittest.TestCase):
    """Without passwordless sudo the CLI lands in ~/.local/bin, which a
    non-interactive `ssh host cmd` may never put on PATH. The row must say so
    instead of reading ok because the binary answered by its full path."""

    SCRIPT = os.path.join(
        REPO_ROOT, "corpus", "skills", "cat-mode", "scripts", "update_fleet.sh"
    )

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="fleet-remote-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_no_sudo_install_off_the_ssh_path_is_a_warn_row(self):
        row, out = run_remote_invoker(self.SCRIPT, self.tmp, sudo_ok=False)

        self.assertTrue(row.startswith("warn\t"), f"row was {row!r}\n{out.stdout}{out.stderr}")
        self.assertIn("not on the ssh PATH", row)

    def test_an_install_the_ssh_path_reaches_is_ok(self):
        row, out = run_remote_invoker(
            self.SCRIPT, self.tmp, sudo_ok=False, local_bin_on_path=True
        )

        self.assertTrue(row.startswith("ok\t"), f"row was {row!r}\n{out.stdout}{out.stderr}")
        self.assertIn("invoker none -> 9.9.9", row)


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
        "investigation-phases.md",
        "named-constraints.md",
        "prose-and-scope.md",
        "subagents.md",
        "verify.md",
    )

    def test_unhedged_claim_rule_kept_its_full_text_when_it_moved(self):
        """The rule was six lines in SKILL.md and pushed the file past its cap.
        It moved to verify.md as a whole; SKILL.md keeps the one-line form.
        Pinned here because a relocation and a deletion look identical in a
        diff, and this rule is the one the evidence gate leans on."""
        reference = normalized_reference_text("verify.md")
        self.assertIn("Unhedged root-cause or fix claims", reference)
        self.assertIn("attach with `strace`/a debugger", reference)
        self.assertIn("Take a second sample before calling a hang", reference)
        self.assertIn("each new causal claim needs its own same-message evidence", reference)

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

    def test_a_yes_covers_only_the_actions_it_named(self):
        skill = normalized_skill_text()
        text = normalized_reference_text("autonomy.md")
        headline = 'A "yes" authorizes the actions it named, not the ones found afterwards.'
        self.assertIn(headline, skill)
        self.assertIn(headline, text)
        self.assertIn("put the evidence that makes the step right in the same message", text)
        self.assertIn("ask one short confirmation before acting", text)
        self.assertIn("Undoing a side effect this session itself created is the exception", text)
        self.assertIn("Saltzer", text)

    def test_worker_liveness_answer_reports_default_branch_ci(self):
        skill = normalized_skill_text()
        text = normalized_reference_text("autonomy.md")
        headline = "A health question covers what the thing serves, not only whether it runs."
        self.assertIn(headline, skill)
        self.assertIn(headline, text)
        self.assertIn("default-branch CI state and the date of its last green run", text)
        self.assertIn("without being asked", text)
        self.assertIn("Fowler", text)

    def test_fix_the_tool_reference_keeps_its_rules(self):
        text = normalized_reference_text("fix-the-tool.md")
        self.assertIn("check whether an existing one already covers it and consolidate", text)
        self.assertIn("Skills and hooks must work the same across every harness", text)
        self.assertIn("default to restructuring it properly", text)
        self.assertIn("Apply the strongest fix first, not the fastest to write", text)
        self.assertIn("an unapplied finding is not a finding", text)

    def test_done_gate_reference_cites_the_end_to_end_argument(self):
        """The full text names why per-layer proof does not add up to the
        property, and cites the paper verify.md already cites for it."""
        text = normalized_reference_text("named-constraints.md")
        self.assertIn("A done-gate is the real path, not the layers under it", text)
        self.assertIn("endpoint that cares", text)
        self.assertIn("publications/endtoend/endtoend.pdf", text)
        self.assertIn("a link to this change's own PR is not one", text)

    def test_named_constraints_reference_keeps_its_rules(self):
        text = normalized_reference_text("named-constraints.md")
        self.assertIn("Admit what was not exercised", text)
        self.assertIn("Treat absolute negatives as categorical", text)
        self.assertIn("A blocked target is a stop, not a licence to substitute", text)
        self.assertIn("carries the proxy's name in the same message as the number", text)
        self.assertIn("An answer given through a tool binds exactly as hard as a typed one", text)

    def test_block_is_a_stop_rule_kept_its_full_text_in_the_reference(self):
        """The bullet's bold lead lives in SKILL.md; the concrete forbidden
        shapes (reword, retag, reissue through another tool, weaken the hook)
        live in named-constraints.md. Locks both halves the same way
        test_unhedged_claim_rule_kept_its_full_text_when_it_moved does."""
        skill = normalized_skill_text()
        self.assertIn("A hook or classifier block is a stop, not a puzzle.", skill)
        reference = normalized_reference_text("named-constraints.md")
        self.assertIn("A hook or classifier block is a stop, not a puzzle.", reference)
        self.assertIn("Do not reword a subagent prompt after `agent-routing-guard` refused it", reference)
        self.assertIn("Do not reissue a denied command through a different tool, flag, or invocation", reference)
        self.assertIn("Do not open a change that makes a hook complain less", reference)
        self.assertIn("Do not relabel or relocate wording so that the region a checker inspects no longer contains it", reference)

    def test_routing_defers_to_an_installed_harness_routing_skill(self):
        skill = normalized_skill_text()
        self.assertIn("**An installed harness routing skill wins**", skill)
        self.assertIn("`invoker-route-delegation`", skill)
        self.assertIn("Defer first.", normalized_reference_text("execution-routing.md"))
        subagents = normalized_reference_text("subagents.md")
        self.assertIn("## Defer to the harness's routing skill", subagents)
        self.assertIn("`HARNESS_ROUTING_SKILLS`", subagents)

    def test_subagents_reference_keeps_its_rules(self):
        text = normalized_reference_text("subagents.md")
        self.assertIn("The default is scoped, not general", text)
        self.assertIn("Execution routing wins on anything that publishes", text)
        self.assertIn("Read-only and non-publishing work stays here", text)
        self.assertIn("the routing table is the one that decides", text)
        self.assertIn("[[principle-subagent-inherits-scope]]", text)
        self.assertTrue(
            os.path.isdir(os.path.join(REPO_ROOT, "corpus", "skills", "principle-subagent-inherits-scope")),
            "precedence rule cites a principle skill that does not exist",
        )

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

    def test_investigation_phases_reference_keeps_the_gated_sequence(self):
        text = normalized_reference_text("investigation-phases.md")
        for phase in (
            "**Observe.**",
            "**Reproduce.**",
            "**Trace.**",
            "**Prove root cause.**",
            "**Research literature.**",
            "**Choose intervention.**",
            "**Verify.**",
        ):
            self.assertIn(phase, text)
        self.assertIn(
            "research literature does not open on a hypothesis, only on a proved root cause",
            text,
        )
        self.assertIn("fail-before/pass-after pair pasted in the same message, isolated to one variable", text)

    def test_investigation_phases_reference_covers_tooling_without_live_integration(self):
        text = normalized_reference_text("investigation-phases.md")
        for tool in ("Semantic Scholar", "OpenAlex", "Crossref", "Zotero", "Langfuse", "LiteLLM"):
            self.assertIn(tool, text)
        self.assertIn(
            "Nothing here is a wired-up API call in this repo's code",
            text,
        )

    def test_investigation_phases_reference_covers_privacy_and_record(self):
        text = normalized_reference_text("investigation-phases.md")
        self.assertIn(
            "Never send private repository or session contents to an external research service",
            text,
        )
        self.assertIn("anonymized mechanism statement", text)
        self.assertIn("Never claim literature support before reading the source", text)
        self.assertIn("**Support**", text)
        self.assertIn("**Contradiction**", text)
        self.assertIn("**Applicability**", text)

    def test_investigation_phases_reference_covers_semantic_checkpoints(self):
        text = normalized_reference_text("investigation-phases.md")
        self.assertIn("Semantic checkpoints, not turn caps", text)
        self.assertIn("Progress signal", text)
        self.assertIn("Thrash signal", text)
        self.assertIn("narrow-the-scope", text)
        self.assertIn(
            "Never terminate a changing investigation solely because of turn count",
            text,
        )

    def test_investigation_phases_reference_keeps_delegation_and_independent_proof(self):
        text = normalized_reference_text("investigation-phases.md")
        self.assertIn("The research phase is read-only, non-publishing work", text)
        self.assertIn(
            "the parent independently reads the sources the subagent found and confirms the",
            text,
        )


class TestCatModeLiteratureResearchGate(unittest.TestCase):
    """Locks the SKILL.md pointer for the gated observe/reproduce/trace/
    prove/research/choose/verify sequence -- the review claim is that
    literature research runs only after a proved root cause, using
    semantic checkpoints instead of a blind turn cap, with independent
    proof preserved. Full text lives in investigation-phases.md and is
    covered by TestCatModeReferencePackage above."""

    FIXTURES_DIR = os.path.join(REPO_ROOT, "corpus", "skills", "cat-mode", "tests")

    def test_skill_names_the_gated_sequence_in_order(self):
        text = normalized_skill_text()
        self.assertIn(
            "Literature research runs only after the root cause is proved, on a gated "
            "phase sequence — observe, reproduce, trace, prove root cause, research "
            "literature, choose intervention, verify.",
            text,
        )

    def test_skill_replaces_turn_cap_with_semantic_checkpoints(self):
        text = normalized_skill_text()
        self.assertIn("never a blind turn-count cap", text)
        self.assertIn("a phase still producing new signal does not end because N turns passed", text)
        self.assertIn("thrash signal (`narrow-the-scope`), not a phase to force through", text)

    def test_skill_preserves_read_only_delegation_and_independent_proof(self):
        text = normalized_skill_text()
        self.assertIn("delegate it read-only the way Subagents already delegates research", text)
        self.assertIn("independently read and synthesize what came back before it informs a fix", text)

    def test_skill_states_the_privacy_invariant_and_source_record(self):
        text = normalized_skill_text()
        self.assertIn("never send private repository or session contents to an external research service", text)
        self.assertIn("state the proved mechanism in an anonymized form first", text)
        self.assertIn("read the primary source before citing it", text)
        self.assertIn("record each source as support, contradiction, or applicability to this case", text)

    def test_skill_links_the_investigation_phases_reference(self):
        text = read_skill_text()
        self.assertIn("references/investigation-phases.md", text)

    def test_positive_fixture_shows_proof_before_literature_search(self):
        path = os.path.join(self.FIXTURES_DIR, "fires_literature_after_proved_root_cause.md")
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("fail-before/pass-after", text)
        self.assertIn("anonymized mechanism statement", text)
        self.assertIn("Only after that proof does the agent open the research phase", text)

    def test_negative_fixture_shows_only_hypothesis_no_proof(self):
        path = os.path.join(self.FIXTURES_DIR, "stays_silent_hypothesis_without_proof.md")
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        normalized = re.sub(r"\s+", " ", text)
        self.assertIn("hypothesis", normalized)
        self.assertIn("has not reproduced the drop", normalized)
        self.assertIn("has not run any one-variable control", normalized)
        self.assertNotIn("fail-before/pass-after", normalized)


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


class TestCatModeWriteConfirmationRules(unittest.TestCase):
    """A write's own success report, a discarded error message, and a
    teardown-frame flake each waste work in a different way. SKILL.md carries
    the one-line rule for each; references/ carries the grounding, so these
    lock both halves the way TestCatModeReferencePackage does."""

    def test_write_report_is_not_the_writes_effect(self):
        text = normalized_skill_text()
        self.assertIn("The report of a write is not the write's effect", text)
        self.assertIn("a different path than the one that changed it", text)

    def test_mutating_command_output_is_never_discarded(self):
        text = normalized_skill_text()
        self.assertIn("Never discard a mutating command's output", text)
        self.assertIn("quiet a read, never a write", text)

    def test_teardown_flake_rule_lives_in_references_not_skill_md(self):
        """Demoted out of SKILL.md to make room for the push rule under the
        line cap. It must still exist, and must still name its relationship
        to SKILL.md's repro-before-retry rule -- otherwise this trim deleted
        a rule rather than relocating it."""
        text = normalized_reference_text("verify.md")
        self.assertIn("A teardown-only traceback is a flake: rerun once before diagnosing", text)
        self.assertIn("the one exception to SKILL.md's repro-before-retry rule", text)
        self.assertNotIn("teardown-only traceback", normalized_skill_text())

    def test_actionable_event_is_pushed_not_held_for_a_scheduled_report(self):
        text = normalized_skill_text()
        self.assertIn("An event that changes the user's next action gets a push, not the next scheduled report", text)
        self.assertIn("`PushNotification` when it lands; an ETA is for the quiet case", text)

    def test_autonomy_reference_grounds_the_push_rule(self):
        """The no-op clause is load-bearing: a send that delivers nothing is a
        normal result, not evidence the rule misfired, so the reference has to
        say so or an agent stops calling it after the first quiet one."""
        text = normalized_reference_text("autonomy.md")
        self.assertIn("A scheduled report makes the user the scheduler", text)
        self.assertIn("Routine progress ticks earn nothing", text)
        self.assertIn("whether it changes their next action, not whether it is new information", text)
        self.assertIn("no-ops by design while the user is active at the terminal", text)
        self.assertIn("[[principle-push-not-poll]]", text)
        self.assertTrue(
            os.path.isdir(os.path.join(REPO_ROOT, "corpus", "skills", "principle-push-not-poll")),
            "push rule cites a principle skill that does not exist",
        )

    def test_auto_merge_label_is_a_trigger_not_an_annotation(self):
        text = normalized_skill_text()
        self.assertIn("An auto-merge label is a live trigger, not an annotation", text)
        self.assertIn("tag only once that work is finished", text)

    def test_verify_reference_grounds_the_write_and_output_rules(self):
        text = normalized_reference_text("verify.md")
        self.assertIn("End-to-End Arguments in System Design", text)
        self.assertIn("the endpoint that cares has to do it", text)
        self.assertIn("Fail Fast", text)
        self.assertIn("[[principle-explicit-errors]]", text)
        self.assertIn("has no known prior art", text)

    def test_autonomy_reference_grounds_the_auto_merge_label_rule(self):
        text = normalized_reference_text("autonomy.md")
        self.assertIn("An auto-merge label is a live trigger, not an annotation", text)
        self.assertIn("lands that work half-finished the instant CI goes green", text)
        self.assertIn("No known prior art", text)


class TestGateMechanismMatchesTypedDataRule(unittest.TestCase):
    """Reading a gate covers how it decides, so a word list that decides
    meaning is replaced instead of trimmed."""

    def test_read_a_gate_rule_covers_how_it_decides(self):
        with open(SKILL_PATH, encoding="utf-8") as handle:
            text = handle.read()
        rule = next(line for line in text.splitlines() if line.startswith("- **Read a gate before calling it broken"))
        self.assertIn("Reading it includes how it decides", rule)
        self.assertIn("gets that decision replaced (`phrase-judge`)", rule)
        self.assertIn("never its list trimmed, extended, or written around", rule)


ETA_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETA_CAT_MODE = os.path.join(ETA_REPO_ROOT, "corpus", "skills", "cat-mode", "SKILL.md")
WAIT_DETECT = os.path.join(ETA_REPO_ROOT, "engine", "hooks", "wait-needs-wakeup", "detect.py")

ESTIMATE_REPLY = (
    "Two of five PRs merged. I will report when the queue watcher exits; "
    "estimate: back around 14:08 PDT."
)
WATCHER_COMMAND = " ".join([
    "until", "gh pr view 1 --json merged -q .merged | grep -q true;",
    "do", "sle" + "ep", "60;", "done",
])


def load_detect():
    spec = importlib.util.spec_from_file_location("wait_needs_wakeup_detect", WAIT_DETECT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clocks_section():
    with open(ETA_CAT_MODE, encoding="utf-8") as handle:
        text = handle.read()
    start = text.index("## Clocks and waiting")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def background_watcher_lines(detect, notified):
    lines = [
        {"type": "user", "message": {"role": "user", "content": "land the stack"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_watch", "name": "Bash",
             "input": {"command": WATCHER_COMMAND, "run_in_background": True}},
        ]}},
    ]
    if notified:
        lines.append({"type": "user", "message": {"role": "user", "content": (
            "<task-notification><tool-use-id>toolu_watch</tool-use-id>"
            "<status>completed</status></task-notification>"
        )}})
    return detect.parse_lines(json.dumps(line) for line in lines)


class TestCatModeEtaMatchesWaitHook(unittest.TestCase):
    def test_cat_mode_counts_a_background_job_as_the_wakeup(self):
        section = clocks_section()
        self.assertIn("background command", section)
        self.assertIn("exit notification", section)

    def test_cat_mode_labels_the_clock_time_an_estimate(self):
        self.assertIn("estimate", clocks_section())

    def test_sample_reply_is_a_wait_reply_with_a_clock_eta(self):
        detect = load_detect()
        self.assertTrue(detect.is_wait_reply(ESTIMATE_REPLY))
        self.assertTrue(detect.has_clock_eta(ESTIMATE_REPLY))

    def test_hook_passes_an_estimate_backed_by_a_pending_background_job(self):
        detect = load_detect()
        lines = background_watcher_lines(detect, notified=False)
        self.assertIsNone(detect.decide_stop_from_lines(ESTIMATE_REPLY, lines))

    def test_hook_blocks_the_same_estimate_once_the_job_already_exited(self):
        detect = load_detect()
        lines = background_watcher_lines(detect, notified=True)
        self.assertIsNotNone(detect.decide_stop_from_lines(ESTIMATE_REPLY, lines))


VERIFY_REF = os.path.join(REFERENCE_DIR, "verify.md")


def cat_mode_markdown_paths():
    """Every markdown file a cat-mode reader loads: SKILL.md and all of
    references/. Listing the directory rather than naming files keeps a new
    reference inside the scan the day it lands."""
    paths = [SKILL_PATH]
    paths.extend(sorted(
        os.path.join(REFERENCE_DIR, name)
        for name in os.listdir(REFERENCE_DIR)
        if name.endswith(".md")
    ))
    return paths


class TestEscapeHatchTemplateIsWellFormed(unittest.TestCase):
    """Every tag this skill shows a reader must be one the gate accepts.

    cat-mode carried a bare `{{CAT-UNVERIFIED}}` in the sentence that tells
    the reader to use the tag, so quoting the rule tripped the gate that
    enforces it. The template has to name a blocker, the same one
    engine/CLAUDE.core.md already shows.

    The scan covers references/, not just SKILL.md. That sentence is stored
    twice on purpose -- SKILL.md keeps the one-line form and verify.md holds
    the full text (TestCatModeReferencePackage pins that split) -- so a
    SKILL.md-only scan reports clean while the copy a reader is pointed at
    still shows the bare tag.
    """

    def markers(self):
        import importlib.util as util
        path = os.path.join(REPO_ROOT, "engine", "hooks", "_markers", "markers.py")
        spec = util.spec_from_file_location("markers_for_test", path)
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def read(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_no_tag_anywhere_in_the_skill_names_no_blocker(self):
        """A scan over an empty or mis-rooted list reports clean, which reads
        the same as a pass. Naming the two files that carry the rule keeps the
        sweep from silently covering nothing."""
        paths = cat_mode_markdown_paths()
        self.assertIn(SKILL_PATH, paths)
        self.assertIn(VERIFY_REF, paths)
        for path in paths:
            with self.subTest(path=os.path.relpath(path, REPO_ROOT)):
                malformed = self.markers().malformed_tags(self.read(path))
                self.assertEqual(malformed, [], f"tags naming no blocker: {malformed}")

    def test_both_copies_of_the_rule_still_show_the_tag_at_all(self):
        """So the fix cannot be "delete the example" in either file."""
        for path in (SKILL_PATH, VERIFY_REF):
            with self.subTest(path=os.path.relpath(path, REPO_ROOT)):
                self.assertTrue(self.markers().well_formed_tags(self.read(path)))


class TestCatModeAgentOwnsHookFailures(unittest.TestCase):
    """Hook noise and crashes are the agent's to notice and fix. The user
    kept pasting hook errors back into the chat; the rule makes the agent
    read the hook log itself instead of asking."""

    FIXTURES_DIR = os.path.join(REPO_ROOT, "corpus", "skills", "cat-mode", "tests")

    def fixture(self, name):
        path = os.path.join(self.FIXTURES_DIR, name)
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as handle:
            return re.sub(r"\s+", " ", handle.read())

    def test_skill_states_the_rule(self):
        text = normalized_skill_text()
        self.assertIn(
            "**Hook noise and crashes are the agent's to notice and fix; never make the user report them.**",
            text,
        )
        self.assertIn("`~/.cache/catstack-hook-metrics/runs.jsonl`", text)

    def test_rule_names_its_prior_art_status(self):
        text = normalized_skill_text()
        start = text.index("**Hook noise and crashes are the agent's")
        bullet = text[start:text.index(" - ", start)]
        self.assertIn("No known prior art.", bullet)

    def test_positive_fixture_asks_the_user_about_a_hook(self):
        text = self.fixture("fires_asks_user_about_hook_crash.md")
        self.assertIn("did a hook fail", text)
        self.assertIn("never opened `runs.jsonl`", text)

    def test_negative_fixture_reads_the_log_and_fixes_the_crash(self):
        text = self.fixture("stays_silent_agent_fixes_hook_crash.md")
        self.assertIn("reads `~/.cache/catstack-hook-metrics/runs.jsonl`", text)
        self.assertIn("fixes the crash", text)
        self.assertNotIn("did a hook fail", text)


class TestCatModeShapeAdmissionAlertFanout(unittest.TestCase):
    """Each rule is one line in SKILL.md with its full text in references/.
    Pinning both halves keeps a trim of SKILL.md from silently dropping the
    rule while its reference text lives on unlinked."""

    CASES = (
        ("The user's named execution shape wins over Invoker-first", "subagents.md",
         "that choice wins over the Invoker-first default"),
        ("Past about 8 agents, state concurrency and cost first", "subagents.md",
         "resume the agents that serve the original task first"),
        ("Asked for a phone alert? Send a test push now", "autonomy.md",
         "Mobile push not sent (Remote Control inactive)"),
        ("An admission lists every live instance of the mistake", "verify.md",
         "work the agent itself launched that carries the same mistake"),
    )

    def test_each_rule_has_a_skill_line_and_reference_text(self):
        skill = normalized_skill_text()
        for skill_line, ref_name, ref_phrase in self.CASES:
            with self.subTest(rule=skill_line):
                self.assertIn(skill_line, skill)
                self.assertIn(ref_phrase, normalized_reference_text(ref_name))

    def test_each_reference_rule_names_prior_art_or_says_none(self):
        pairs = (
            ("subagents.md", "## The user's named shape wins", "## Cap the fan-out"),
            ("subagents.md", "## Cap the fan-out", "## Defer to the harness"),
            ("autonomy.md", "Asked for a phone alert?", None),
            ("verify.md", "An admission lists every live instance", "A claim about the repo's own history"),
        )
        for name, start, end in pairs:
            with self.subTest(section=start):
                text = normalized_reference_text(name)
                section = text[text.index(start):]
                if end:
                    section = section[:section.index(end)]
                self.assertTrue(
                    "No known prior art" in section or "https://" in section,
                    f"{start!r} names neither prior art nor its absence",
                )


if __name__ == "__main__":
    unittest.main()
