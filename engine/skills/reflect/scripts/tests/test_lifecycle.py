#!/usr/bin/env python3
"""Tests for lifecycle.py — synthetic records only, with the judge replaced by the fake runner."""
from __future__ import annotations

import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
REPOSITORY_ROOT = SCRIPTS_DIR.parents[3]
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))
for real in (
    REPOSITORY_ROOT / "engine" / "hooks" / "_runner",
    REPOSITORY_ROOT / "engine" / "hooks" / "_sdk",
    REPOSITORY_ROOT / "engine" / "hooks" / "skill-usage-log",
    REPOSITORY_ROOT / "engine" / "hooks" / "llm-judge",
):
    sys.path.insert(0, str(real))

import lifecycle  # noqa: E402
from fake_judge import fake_judge  # noqa: E402

SESSION_ID = "11111111-2222-3333-4444-555555555555"
INSIDE_WINDOW = "2026-10-26T12:00:00+00:00"
HOOKS_TOML = """
[hooks.quiet-hook]
mode = "warn"
why_mode = "habit"
summary = "Notes a quiet thing nobody acts on."

[hooks.loud-hook]
mode = "warn"
why_mode = "attention"
summary = "Stops a loud thing that burns attention."

[thresholds]
min_closed_findings = 2
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = 3
"""
SKILLS_TOML = """
[skills.alpha-skill]
bucket = "engine"

[skills.beta-skill]
bucket = "engine"
"""


def write(path: Path, text: str) -> Path:
    """One file with its parents made, so a fixture reads like the real layout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_rows(path: Path, rows: list[dict]) -> Path:
    """One JSON-lines file, the shape both the hook runner and the event writer append."""
    return write(path, "".join(json.dumps(row) + "\n" for row in rows))


def skill_use_row(skill: str, harness: str = "claude", timestamp: str = INSIDE_WINDOW) -> dict:
    """One skill-use row, as skill-usage-log writes it."""
    return {
        "hook": "skill-usage-log",
        "harness": harness,
        "session_id": SESSION_ID,
        "action": "skill_used",
        "reason": "skill_tool",
        "skill": skill,
        "ts": timestamp,
    }


def rule_row(hook: str, rule_id: str, action: str, timestamp: str = INSIDE_WINDOW) -> dict:
    """One hook finding row, as the shared runtime writes it."""
    return {
        "hook": hook,
        "harness": "claude",
        "session_id": SESSION_ID,
        "rule_id": rule_id,
        "subject_hash": "abc",
        "mode": "warn",
        "mode_source": "registry",
        "effective_level": "soft",
        "action": action,
        "finding_id": f"{hook}-{rule_id}-{action}-{timestamp}",
        "duration_ms": 5,
        "ts": timestamp,
    }


def followup_row(hook: str, rule_id: str, outcome: str, index: int) -> dict:
    """One closed finding, as the follow-up writer closes it."""
    row = rule_row(hook, rule_id, "followup")
    row["outcome"] = outcome
    row["finding_id"] = f"{hook}-{rule_id}-{index}"
    return row


def step_row(
    runbook: str,
    step: str,
    acted: str = "",
    override_reason: str = "",
    evidence_ref: str = "",
    timestamp: str = INSIDE_WINDOW,
    hook: str = "runbook-gate",
) -> dict:
    """One runner row carrying a playbook step log."""
    return {
        "ts": timestamp,
        "harness": "claude",
        "hook": hook,
        "session_id": SESSION_ID,
        "outcome": "spoke",
        "exit_code": 0,
        "duration_ms": 3,
        "rule_ids": [f"{hook}.step"],
        "acted": acted,
        "runbook": runbook,
        "step": step,
        "override_reason": override_reason,
        "evidence_ref": evidence_ref,
    }


def cluster(cluster_key: str, hash_value: str = "aaaabbbbcccc") -> dict:
    """One mined cluster, the shape the mine queue stores."""
    return {
        "cluster_key": cluster_key,
        "hash": hash_value,
        "session_count": 3,
        "utterance_count": 5,
        "high_confidence": True,
        "circumstance_complete": True,
    }


class World:
    """One fixture world: a repository to measure, the records of a window, and where the report goes.

    The hook report module, the registry and the judge are the real ones; only their inputs are fixtures.
    """

    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.repository = self.root / "repo"
        self.metrics = self.root / "metrics"
        self.state = self.root / "state"
        self.transcripts = self.root / "transcripts"
        self.out = self.root / "lifecycle" / "report.tsv"
        self.structural_wins = self.root / "structural-wins.txt"
        write(self.repository / "skills.toml", SKILLS_TOML)
        write(self.repository / "engine" / "hooks" / "hooks.toml", HOOKS_TOML)
        for name, description in (("alpha-skill", "do the alpha thing"), ("beta-skill", "do the beta thing")):
            write(
                self.repository / "engine" / "skills" / name / "SKILL.md",
                f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            )
        write(self.repository / "engine" / "hooks" / "quiet-hook" / "README.md", "# quiet-hook\n")
        write(self.repository / "engine" / "hooks" / "loud-hook" / "README.md", "# loud-hook\n")
        self.events(skill_use_row("alpha-skill"), skill_use_row("beta-skill"))
        self.runs()
        self.queue(cluster("make_pr"))
        self.transcript()

    def events(self, *rows: dict) -> None:
        write_rows(self.metrics / "events-2026-10-26.jsonl", list(rows))

    def runs(self, *rows: dict) -> None:
        write_rows(self.metrics / "runs.jsonl", list(rows))

    def queue(self, *clusters: dict) -> None:
        write(self.state / "queue.json", json.dumps({"clusters": list(clusters)}))

    def transcript(self, *texts: str) -> None:
        rows = [
            {"type": "user", "message": {"role": "user", "content": text}, "timestamp": INSIDE_WINDOW}
            for text in (texts or ("start the alpha thing",))
        ]
        write_rows(self.transcripts / f"{SESSION_ID}.jsonl", rows)

    def cite(self, hook: str, skill: str) -> None:
        write(
            self.repository / "engine" / "hooks" / hook / "README.md",
            f"# {hook}\n\nRead `{skill}` before deciding.\n",
        )

    def arguments(self, *extra: str) -> list[str]:
        return [
            "report",
            "--out",
            str(self.out),
            "--state-dir",
            str(self.state),
            "--metrics-dir",
            str(self.metrics),
            "--transcripts-dir",
            str(self.transcripts),
            "--repository-root",
            str(self.repository),
            "--structural-wins",
            str(self.structural_wins),
            "--window-days",
            "3650",
            "--min-closed-findings",
            "2",
            *extra,
        ]

    def report_rows(self) -> list[dict[str, str]]:
        lines = self.out.read_text(encoding="utf-8").splitlines()
        columns = lines[0].split("\t")
        return [dict(zip(columns, line.split("\t"))) for line in lines[1:]]

    def classes(self) -> list[str]:
        return [row["class"] for row in self.report_rows()]

    def proposals(self) -> list[str]:
        directory = self.out.parent / "proposals"
        return sorted(path.name for path in directory.glob("*.md")) if directory.is_dir() else []


def run(world: World, *extra: str, match: tuple[str, ...] = (), fail: bool = False) -> int:
    """One pass over a fixture world with the judge replaced, returning its exit code."""
    with fake_judge(match=match, fail=fail):
        return lifecycle.main(world.arguments(*extra))


class TestOwnerSkills(unittest.TestCase):
    def test_every_mined_cluster_gets_an_owner_or_an_empty_one(self):
        owned = lifecycle.assign_owner_skills([cluster("make_pr"), cluster("brand_new_poke", "ddddeeeeffff")])
        self.assertEqual([entry["owner_skill"] for entry in owned], ["draft-pr", ""])

    def test_the_owner_table_names_only_registered_skills(self):
        inventory = tomllib.loads((REPOSITORY_ROOT / "skills.toml").read_text(encoding="utf-8"))
        self.assertTrue(set(lifecycle.CLUSTER_OWNER_SKILLS.values()) <= set(inventory["skills"]))

    def test_the_mine_queue_clusters_carry_their_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            clusters = lifecycle.read_mine_clusters(world.state)
        self.assertEqual(clusters[0]["owner_skill"], "draft-pr")

    def test_a_missing_mine_queue_is_unchecked_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(lifecycle.Unchecked) as caught:
                lifecycle.read_mine_clusters(Path(tmp) / "nothing-here")
        self.assertIn("the mine queue unreadable", str(caught.exception))


class TestCleanPass(unittest.TestCase):
    def test_a_window_with_nothing_to_change_ends_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            code = run(world)
            classes = world.classes()
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_CLEAN)
        self.assertEqual(proposals, [])
        self.assertEqual([name for name in classes if name in lifecycle.PROPOSAL_CLASSES], [])

    def test_the_report_carries_its_header_and_unbroken_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            run(world)
            lines = world.out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split("\t"), list(lifecycle.REPORT_COLUMNS))
        for line in lines[1:]:
            self.assertEqual(len(line.split("\t")), len(lifecycle.REPORT_COLUMNS))

    def test_a_used_skill_is_never_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.RETIRE, classes)


class TestRetire(unittest.TestCase):
    def test_an_unused_unowned_uncited_skill_becomes_a_retire_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.RETIRE]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_CHANGED)
        self.assertEqual([row["subject"] for row in rows], ["beta-skill"])
        self.assertEqual(rows[0]["base_count"], "2")
        self.assertEqual(rows[0]["head_count"], "1")
        self.assertIn("retire.md", proposals)

    def test_the_head_count_drops_by_every_subject_the_class_proposes(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("diu"))
            run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.RETIRE]
            body = (world.out.parent / "proposals" / "retire.md").read_text(encoding="utf-8")
        self.assertEqual(sorted(row["subject"] for row in rows), ["alpha-skill", "beta-skill"])
        self.assertEqual({(row["base_count"], row["head_count"]) for row in rows}, {("2", "0")})
        self.assertIn("head registered skills = 0", body)

    def test_the_report_says_what_the_skill_use_signal_rests_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            run(world)
            notes = [row["evidence"] for row in world.report_rows() if row["class"] == lifecycle.NOTE_CLASS]
        self.assertTrue(any("the skill-use signal rests on 2 row(s) naming 2 skill(s)" in note for note in notes))

    def test_a_skill_used_on_another_harness_is_not_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"), skill_use_row("beta-skill", harness="codex"))
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.RETIRE, classes)

    def test_a_citing_hook_that_still_speaks_keeps_the_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"), rule_row("loud-hook", "loud-hook.rule", "warned"))
            world.cite("loud-hook", "beta-skill")
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.RETIRE, classes)

    def test_a_silent_citing_hook_does_not_keep_the_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            world.cite("quiet-hook", "beta-skill")
            run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.RETIRE]
        self.assertEqual([row["subject"] for row in rows], ["beta-skill"])
        self.assertIn("quiet-hook", rows[0]["evidence"])

    def test_a_structural_win_is_recorded_instead_of_a_retire(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            write(world.structural_wins, "# solved for good\nbeta-skill\n")
            code = run(world)
            classes = world.classes()
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.STRUCTURAL_WIN_CLASS]
        self.assertEqual(code, lifecycle.EXIT_CLEAN)
        self.assertNotIn(lifecycle.RETIRE, classes)
        self.assertEqual([row["subject"] for row in rows], ["beta-skill"])

    def test_an_owned_cluster_keeps_its_owner_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            world.queue({**cluster("make_pr"), "cluster_key": "make_pr"})
            lifecycle.CLUSTER_OWNER_SKILLS["make_pr"] = "beta-skill"
            try:
                run(world)
                classes = world.classes()
            finally:
                lifecycle.CLUSTER_OWNER_SKILLS["make_pr"] = "draft-pr"
        self.assertNotIn(lifecycle.RETIRE, classes)


class TestCoverageGap(unittest.TestCase):
    def test_a_cluster_the_table_does_not_name_is_a_coverage_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.queue(cluster("make_pr"), cluster("brand_new_poke", "ddddeeeeffff"))
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.COVERAGE_GAP]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_CHANGED)
        self.assertEqual([row["subject"] for row in rows], ["brand_new_poke"])
        self.assertEqual((rows[0]["base_count"], rows[0]["head_count"]), ("1", "2"))
        self.assertIn("coverage-gap.md", proposals)


class TestRework(unittest.TestCase):
    def test_a_step_skipped_with_a_reason_becomes_a_rework(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.runs(step_row("bugfix", "3", acted="overridden", override_reason="the repro was already green"))
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.REWORK]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_CHANGED)
        self.assertEqual([row["subject"] for row in rows], ["bugfix step 3"])
        self.assertIn("the repro was already green", rows[0]["evidence"])
        self.assertIn("rework.md", proposals)

    def test_a_gate_overridden_in_most_of_ten_runs_becomes_a_rework(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.runs(*([step_row("bugfix", "2", acted="overridden")] * 6 + [step_row("bugfix", "2", acted="acted")] * 4))
            run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.REWORK]
        self.assertEqual([row["subject"] for row in rows], ["bugfix step 2"])
        self.assertIn("overridden in 6 of 10 run(s)", rows[0]["evidence"])

    def test_a_gate_overridden_in_too_few_runs_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.runs(*([step_row("bugfix", "2", acted="overridden")] * 5 + [step_row("bugfix", "2", acted="acted")] * 4))
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.REWORK, classes)

    def test_a_gate_overridden_in_half_the_runs_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.runs(*([step_row("bugfix", "2", acted="overridden")] * 5 + [step_row("bugfix", "2", acted="acted")] * 5))
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.REWORK, classes)


class TestMoveEarlier(unittest.TestCase):
    def _world(self, tmp: str, late_evidence: str, early_evidence: str) -> World:
        world = World(tmp)
        world.transcript("start the alpha thing", "I already told you to run the repro first")
        world.runs(
            step_row("bugfix", "1", evidence_ref=early_evidence, timestamp="2026-10-26T11:59:00+00:00"),
            step_row("bugfix", "4", evidence_ref=late_evidence, timestamp="2026-10-26T11:59:30+00:00"),
        )
        return world

    def test_an_intervention_after_a_step_whose_evidence_came_earlier_moves_the_catch(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = self._world(tmp, "test_result", "test_result")
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.MOVE_EARLIER]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_CHANGED)
        self.assertEqual([row["subject"] for row in rows], ["bugfix step 4"])
        self.assertIn("step 1 already recorded", rows[0]["evidence"])
        self.assertIn("move-earlier.md", proposals)

    def test_a_step_whose_evidence_was_not_available_earlier_stays_where_it_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = self._world(tmp, "test_result", "command_output")
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.MOVE_EARLIER, classes)

    def test_a_session_with_no_intervention_moves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = self._world(tmp, "test_result", "test_result")
            world.transcript("start the alpha thing")
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.MOVE_EARLIER, classes)


class TestLevels(unittest.TestCase):
    def test_a_rule_nobody_ignores_becomes_a_strengthen(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(
                skill_use_row("alpha-skill"),
                skill_use_row("beta-skill"),
                rule_row("loud-hook", "loud-hook.rule", "warned"),
                rule_row("loud-hook", "loud-hook.rule", "warned"),
                followup_row("loud-hook", "loud-hook.rule", "acted", 1),
                followup_row("loud-hook", "loud-hook.rule", "acted", 2),
            )
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.STRENGTHEN]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_CHANGED)
        self.assertEqual([row["subject"] for row in rows], ["loud-hook loud-hook.rule"])
        self.assertIn("suggestion=warn to stop", rows[0]["evidence"])
        self.assertIn("strengthen.md", proposals)

    def test_a_rule_everyone_ignores_becomes_a_simplify(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(
                skill_use_row("alpha-skill"),
                skill_use_row("beta-skill"),
                rule_row("quiet-hook", "quiet-hook.rule", "warned"),
                rule_row("quiet-hook", "quiet-hook.rule", "warned"),
                followup_row("quiet-hook", "quiet-hook.rule", "ignored", 1),
                followup_row("quiet-hook", "quiet-hook.rule", "ignored", 2),
            )
            run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.SIMPLIFY]
        self.assertEqual([row["subject"] for row in rows], ["quiet-hook quiet-hook.rule"])
        self.assertIn("suggestion=review or turn off", rows[0]["evidence"])

    def test_a_rule_with_too_little_data_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(
                skill_use_row("alpha-skill"),
                skill_use_row("beta-skill"),
                rule_row("loud-hook", "loud-hook.rule", "warned"),
                followup_row("loud-hook", "loud-hook.rule", "acted", 1),
            )
            run(world)
            classes = world.classes()
        self.assertNotIn(lifecycle.STRENGTHEN, classes)
        self.assertNotIn(lifecycle.WEAKEN, classes)
        self.assertNotIn(lifecycle.SIMPLIFY, classes)


class TestOverlap(unittest.TestCase):
    def test_a_pair_the_judge_calls_the_same_becomes_a_combine(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            code = run(world, "--max-judge-pairs", "0", match=("do the beta thing",))
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.COMBINE]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_CHANGED)
        self.assertTrue(all("beta-skill" in row["subject"] for row in rows))
        self.assertIn("combine.md", proposals)

    def test_a_pair_the_judge_calls_distinct_proposes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            code = run(world, "--max-judge-pairs", "0", match=("nothing says this",))
            classes = world.classes()
        self.assertEqual(code, lifecycle.EXIT_CLEAN)
        self.assertNotIn(lifecycle.COMBINE, classes)

    def test_the_pair_cap_is_reported_with_its_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            run(world, "--max-judge-pairs", "1")
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.CAPPED_CLASS]
        self.assertEqual(rows[0]["base_count"], "5")
        self.assertIn("--max-judge-pairs 1", rows[0]["evidence"])

    def test_the_skip_walks_the_pair_list_past_the_pairs_a_cap_already_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            with fake_judge(match=("do the beta thing",)) as judged_texts:
                lifecycle.main(world.arguments("--max-judge-pairs", "1"))
                first = list(judged_texts())
            with fake_judge(match=("do the beta thing",)) as judged_texts:
                lifecycle.main(world.arguments("--max-judge-pairs", "1", "--judge-skip-pairs", "1"))
                second = list(judged_texts())
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.CAPPED_CLASS]
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first, second)
        self.assertIn("--judge-skip-pairs 1", rows[0]["evidence"])


class TestBlocked(unittest.TestCase):
    def test_a_judge_that_cannot_answer_blocks_the_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            code = run(world, "--max-judge-pairs", "1", fail=True)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.UNCHECKED_CLASS]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertIn("unchecked from the judge", rows[0]["evidence"])
        self.assertEqual(proposals, [])

    def test_a_missing_mine_queue_blocks_the_pass_and_proposes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            (world.state / "queue.json").unlink()
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.UNCHECKED_CLASS]
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertIn("the mine queue unreadable", rows[0]["evidence"])
        self.assertEqual(proposals, [])

    def test_a_window_with_no_skill_use_row_blocks_instead_of_retiring_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events()
            code = run(world)
            rows = world.report_rows()
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertEqual(proposals, [])
        self.assertNotIn(lifecycle.RETIRE, [row["class"] for row in rows])
        self.assertTrue(
            any("no skill-use row names any skill" in row["evidence"] for row in rows if row["class"] == lifecycle.UNCHECKED_CLASS)
        )

    def test_one_missing_signal_still_reports_the_classes_the_other_signals_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            (world.state / "queue.json").unlink()
            world.runs(step_row("bugfix", "3", acted="overridden", override_reason="the repro was already green"))
            code = run(world)
            rows = world.report_rows()
            proposals = world.proposals()
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertEqual(proposals, [])
        self.assertIn(lifecycle.REWORK, [row["class"] for row in rows])
        self.assertNotIn(lifecycle.RETIRE, [row["class"] for row in rows])
        self.assertEqual({row["proposal"] for row in rows}, {"none"})

    def test_a_missing_metrics_directory_blocks_the_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            for path in sorted(world.metrics.glob("*")):
                path.unlink()
            world.metrics.rmdir()
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.UNCHECKED_CLASS]
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertIn("no hook event rows could be read", rows[0]["evidence"])

    def test_a_missing_transcript_directory_blocks_the_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            (world.transcripts / f"{SESSION_ID}.jsonl").unlink()
            world.transcripts.rmdir()
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.UNCHECKED_CLASS]
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertIn("no transcript directory", rows[0]["evidence"])

    def test_an_unreadable_structural_wins_list_blocks_the_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.structural_wins.mkdir(parents=True)
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.UNCHECKED_CLASS]
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertIn("structural-wins list could not be read", rows[0]["evidence"])

    def test_open_prs_without_a_head_branch_blocks_before_reading_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            code = lifecycle.main(world.arguments("--open-prs"))
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertFalse(world.out.exists())


class TestDroppedWrite(unittest.TestCase):
    def test_a_report_write_that_cannot_land_ends_blocked_and_proposes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            blocker = write(Path(tmp) / "taken", "not a directory\n")
            world.out = blocker / "report.tsv"
            code = run(world)
            proposals = world.proposals()
            untouched = blocker.read_text(encoding="utf-8")
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertEqual(proposals, [])
        self.assertEqual(untouched, "not a directory\n")

    def test_a_proposal_write_that_cannot_land_ends_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            world.out.parent.mkdir(parents=True, exist_ok=True)
            write(world.out.parent / "proposals", "not a directory\n")
            code = run(world)
            rows = [row for row in world.report_rows() if row["class"] == lifecycle.RETIRE]
        self.assertEqual(code, lifecycle.EXIT_BLOCKED)
        self.assertEqual([row["subject"] for row in rows], ["beta-skill"])


class TestProposalBody(unittest.TestCase):
    def test_each_class_gets_one_proposal_carrying_its_base_and_head_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            world.queue(cluster("brand_new_poke", "ddddeeeeffff"))
            run(world)
            proposals = world.proposals()
            body = (world.out.parent / "proposals" / "retire.md").read_text(encoding="utf-8")
        self.assertEqual(proposals, ["coverage-gap.md", "retire.md"])
        self.assertTrue(body.startswith(f"{lifecycle.AUTOMATIC_TITLE_PREFIX} lifecycle: retire (1 subject(s))"))
        self.assertIn("base registered skills = 2", body)
        self.assertIn("head registered skills = 1", body)
        for section in ("## Summary", "## Review Claim", "## Safety Invariant", "## Non-goals", "## Measured", "## Test Plan", "## Revert Plan"):
            self.assertIn(section, body)

    def test_the_pass_opens_no_pull_request_unless_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.events(skill_use_row("alpha-skill"))
            with fake_judge(match=()):
                result = lifecycle.run_pass(lifecycle.build_parser().parse_args(world.arguments()), "test command")
        self.assertEqual(result.outcome, lifecycle.OUTCOME_CHANGED)
        self.assertEqual(result.opened, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
