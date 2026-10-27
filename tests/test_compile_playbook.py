"""An ordered rule pair becomes a playbook proposal only when three or more sessions ran it in that order."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPILE = REPO / "scripts" / "runbook" / "compile.py"
CHECK_PLAYBOOK = REPO / "scripts" / "runbook" / "check_playbook.py"
RULES_HEADER = "rule_id\tkind\tbucket\tsource\tmode\twhy_mode\tauto_fire\tsummary\n"
BASE_RULES = (
    ("alpha-gate", "hook", "engine", "engine/hooks/alpha-gate/", "stop", "Stops a done claim with no pasted command output."),
    ("beta-note", "hook", "engine", "engine/hooks/beta-note/", "warn", "Notes an edit made with no check run after it."),
    ("gamma-skill", "skill", "corpus", "corpus/skills/gamma-skill/SKILL.md", "prose", "Writes the repro before the fix."),
    ("delta-rare", "hook", "engine", "engine/hooks/delta-rare/", "warn", "Notes a rare thing nobody repeats."),
)
HOOKS_TOML = """[hooks.alpha-gate]
mode = "stop"
why_mode = "attention"
summary = "Stops a done claim with no pasted command output."

[hooks.alpha-gate.enforcement]
default = "hard"
capability = ["claude:Stop"]
evidence = ["pasted_output"]
override = "reason_required"

[hooks.beta-note]
mode = "warn"
why_mode = "habit"
summary = "Notes an edit made with no check run after it."

[hooks.beta-note.enforcement]
default = "conditional"
capability = ["claude:PreToolUse"]
evidence = ["edit_count"]
override = "reason_required"

[hooks.delta-rare]
mode = "warn"
why_mode = "habit"
summary = "Notes a rare thing nobody repeats."
"""
INSTALLED_PLAYBOOK = """---
runbook: bugfix
version: 1
applies_to:
  - engine/hooks/alpha-gate/
compiled_from:
  - alpha-gate
playbook-trigger: repair the broken widget
enforcement_profile: guided
---

# Repairing a widget

## 1. Paste the command output [alpha-gate · hard · evidence: pasted_output · @Stop]

Run it and paste what it printed.
"""
ORDERED_RUN = (("hook", "alpha-gate"), ("hook", "beta-note"), ("skill", "gamma-skill"))
TASK = "bugfix"


def write_rules(root: Path, rows: tuple[tuple[str, str, str, str, str, str], ...]) -> None:
    path = root / "engine" / "runbook" / "rules.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [RULES_HEADER]
    for rule_id, kind, bucket, source, mode, summary in rows:
        why_mode = "attention" if kind == "hook" else ""
        auto_fire = "event" if kind == "hook" else "yes"
        lines.append(f"{rule_id}\t{kind}\t{bucket}\t{source}\t{mode}\t{why_mode}\t{auto_fire}\t{summary}\n")
    path.write_text("".join(lines), encoding="utf-8")


def write_hooks(root: Path, text: str = HOOKS_TOML) -> None:
    path = root / "engine" / "hooks" / "hooks.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def session(identifier: str, day: int, steps: tuple[tuple[str, str], ...], task: str = TASK, month: int = 9) -> dict:
    return {
        "path": f"/tmp/{identifier}.jsonl",
        "session_id": identifier,
        "task_type": task,
        "steps": [
            {"kind": kind, "id": step_id, "ts": f"2026-{month:02d}-{day:02d}T09:{minute:02d}:00Z"}
            for minute, (kind, step_id) in enumerate(steps)
        ],
        "unchecked": [],
    }


def write_sessions(root: Path, sessions: list[dict], name: str = "sessions.json") -> Path:
    path = root / name
    path.write_text(json.dumps({"sessions": sessions}, indent=1), encoding="utf-8")
    return path


def three_ordered_sessions() -> list[dict]:
    return [session(f"ordered-{number}", number + 1, ORDERED_RUN) for number in range(3)]


class CompileFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        write_rules(self.root, BASE_RULES)
        write_hooks(self.root)

    def compile_run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(COMPILE), *arguments, "--root", str(self.root)],
            capture_output=True,
            text=True,
        )

    def propose(self, sessions: list[dict], *extra: str) -> subprocess.CompletedProcess[str]:
        path = write_sessions(self.root, sessions)
        return self.compile_run("propose", "--task", TASK, "--sessions-json", str(path), *extra)

    def backtest(self, sessions: list[dict], *extra: str) -> subprocess.CompletedProcess[str]:
        path = write_sessions(self.root, sessions, name="backtest-sessions.json")
        return self.compile_run("backtest", "--task", TASK, "--sessions-json", str(path), *extra)

    def proposal_text(self) -> str:
        return (self.root / "proposals" / f"{TASK}.md").read_text(encoding="utf-8")

    def check_playbook(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECK_PLAYBOOK), str(self.root / "proposals" / f"{TASK}.md"), "--root", str(self.root)],
            capture_output=True,
            text=True,
        )


class ProposeTests(CompileFixture):
    def test_three_sessions_in_one_order_become_three_steps(self) -> None:
        result = self.propose(three_ordered_sessions())
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.proposal_text()
        self.assertLess(text.index("alpha-gate ·"), text.index("beta-note ·"))
        self.assertLess(text.index("beta-note ·"), text.index("gamma-skill ·"))
        self.assertIn("## 1. Stops a done claim with no pasted command output [alpha-gate · hard", text)

    def test_the_fixture_proposal_passes_the_playbook_validator(self) -> None:
        self.assertEqual(self.propose(three_ordered_sessions()).returncode, 0)
        checked = self.check_playbook()
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("clean: 1 playbook(s)", checked.stdout)

    def test_a_hard_step_carries_its_evidence_key_and_event(self) -> None:
        self.propose(three_ordered_sessions())
        text = self.proposal_text()
        self.assertIn("[alpha-gate · hard · evidence: pasted_output · @Stop]", text)
        self.assertIn("[beta-note · conditional · evidence: edit_count · @PreToolUse]", text)

    def test_a_rule_with_no_declared_enforcement_stays_soft(self) -> None:
        self.propose(three_ordered_sessions())
        self.assertIn("[gamma-skill · soft]", self.proposal_text())

    def test_a_pair_seen_twice_is_dropped_and_named(self) -> None:
        sessions = three_ordered_sessions()
        sessions.append(session("rare-1", 10, (("hook", "delta-rare"),) + ORDERED_RUN))
        sessions.append(session("rare-2", 11, (("hook", "delta-rare"),) + ORDERED_RUN))
        result = self.propose(sessions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("delta-rare before alpha-gate: 2 session(s), fewer than 3", result.stdout)
        self.assertNotIn("delta-rare", self.proposal_text())

    def test_a_reversed_pair_is_dropped_and_named(self) -> None:
        sessions = three_ordered_sessions()
        sessions.append(session("reversed-1", 12, (("skill", "gamma-skill"), ("hook", "alpha-gate"), ("hook", "beta-note"))))
        result = self.propose(sessions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("beta-note before gamma-skill: reversed in 1 session(s)", result.stdout)
        self.assertIn("[alpha-gate · hard", self.proposal_text())
        self.assertNotIn("gamma-skill", self.proposal_text())

    def test_a_rule_that_ran_without_its_predecessor_is_dropped_and_named(self) -> None:
        sessions = three_ordered_sessions()
        sessions.append(session("alone-1", 13, (("hook", "beta-note"),)))
        result = self.propose(sessions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("beta-note ran without alpha-gate in 1 session(s)", result.stdout)

    def test_another_task_type_is_not_mined_into_this_proposal(self) -> None:
        sessions = three_ordered_sessions()
        sessions.append(session("other-1", 14, (("hook", "delta-rare"), ("hook", "alpha-gate")), task="ship-pr"))
        sessions.append(session("other-2", 15, (("hook", "delta-rare"), ("hook", "alpha-gate")), task="ship-pr"))
        sessions.append(session("other-3", 16, (("hook", "delta-rare"), ("hook", "alpha-gate")), task="ship-pr"))
        self.assertEqual(self.propose(sessions).returncode, 0)
        self.assertNotIn("delta-rare", self.proposal_text())

    def test_the_profile_stays_advisory_with_no_measured_false_fire_rate(self) -> None:
        result = self.propose(three_ordered_sessions())
        self.assertIn("enforcement_profile: advisory", self.proposal_text())
        self.assertIn("no measured false-fire rate was given", result.stdout)

    def test_a_measured_rate_under_ten_percent_allows_guided(self) -> None:
        result = self.propose(three_ordered_sessions(), "--false-fire-percent", "4.5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("enforcement_profile: guided", self.proposal_text())
        self.assertIn("4.5 percent is under 10 percent", result.stdout)

    def test_a_measured_rate_at_or_over_ten_percent_keeps_advisory(self) -> None:
        result = self.propose(three_ordered_sessions(), "--false-fire-percent", "12.0")
        self.assertIn("enforcement_profile: advisory", self.proposal_text())
        self.assertIn("12.0 percent is not under 10 percent", result.stdout)

    def test_an_installed_playbook_for_the_task_gets_a_unified_diff(self) -> None:
        installed = self.root / "product" / "skills" / "bugfix-repair" / "playbooks" / "repair.md"
        installed.parent.mkdir(parents=True)
        installed.write_text(INSTALLED_PLAYBOOK, encoding="utf-8")
        result = self.propose(three_ordered_sessions())
        self.assertEqual(result.returncode, 0, result.stderr)
        diff = (self.root / "proposals" / f"{TASK}.diff").read_text(encoding="utf-8")
        self.assertIn("--- ", diff)
        self.assertIn("+## 2. Notes an edit made with no check run after it [beta-note · conditional", diff)

    def test_a_trigger_an_installed_playbook_already_claims_fails_the_validator(self) -> None:
        installed = self.root / "product" / "skills" / "bugfix-repair" / "playbooks" / "repair.md"
        installed.parent.mkdir(parents=True)
        installed.write_text(
            INSTALLED_PLAYBOOK.replace("playbook-trigger: repair the broken widget", "playbook-trigger: bugfix playbook"),
            encoding="utf-8",
        )
        result = self.propose(three_ordered_sessions())
        self.assertEqual(result.returncode, 1)
        self.assertIn("'bugfix playbook' is already claimed by", result.stderr)
        self.assertIn("check_playbook.py exited 1", result.stderr)

    def test_no_installed_playbook_says_the_proposal_is_new(self) -> None:
        result = self.propose(three_ordered_sessions())
        self.assertIn("no installed playbook declares runbook: bugfix", result.stdout)

    def test_more_than_nine_ordered_rules_are_capped_and_the_drop_is_named(self) -> None:
        rules = tuple(
            (f"rule-{number:02d}", "hook", "engine", f"engine/hooks/rule-{number:02d}/", "warn", f"Notes thing number {number}.")
            for number in range(1, 11)
        )
        write_rules(self.root, rules)
        chain = tuple(("hook", f"rule-{number:02d}") for number in range(1, 11))
        result = self.propose([session(f"chain-{number}", number + 1, chain) for number in range(3)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 rule(s) past the 9-step cap dropped: rule-10", result.stdout)
        self.assertNotIn("rule-10", self.proposal_text())
        self.assertEqual(self.check_playbook().returncode, 0)

    def test_no_qualifying_pair_proposes_nothing_and_names_the_disqualifier(self) -> None:
        result = self.propose([session("only-1", 1, ORDERED_RUN), session("only-2", 2, ORDERED_RUN)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("no ordered rule pair reached 3 session(s)", result.stderr)
        self.assertIn("2 session(s), fewer than 3", result.stdout)

    def test_an_id_the_inventory_ships_twice_keeps_both_sources(self) -> None:
        rules = BASE_RULES + (
            ("gamma-skill", "hook", "engine", "engine/hooks/gamma-skill/", "warn", "Writes the repro before the fix."),
        )
        write_rules(self.root, rules)
        result = self.propose(three_ordered_sessions())
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.proposal_text()
        self.assertIn("  - corpus/skills/gamma-skill/SKILL.md", text)
        self.assertIn("  - engine/hooks/gamma-skill/", text)

    def test_a_step_id_the_inventory_does_not_ship_is_named_not_mined(self) -> None:
        sessions = three_ordered_sessions()
        sessions.append(session("stray-1", 17, (("hook", "never-shipped-gate"),) + ORDERED_RUN))
        result = self.propose(sessions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 step id(s) are not in engine/runbook/rules.tsv and were not mined", result.stdout)
        self.assertIn("never-shipped-gate: 1 firing(s)", result.stdout)
        self.assertNotIn("never-shipped-gate", self.proposal_text())

    def test_the_candidate_pair_count_is_printed_with_the_session_count(self) -> None:
        result = self.propose(three_ordered_sessions())
        self.assertIn("mined 3 candidate pair(s) from 3 session(s) of bugfix", result.stdout)

    def test_a_malformed_step_timestamp_is_reported_unchecked(self) -> None:
        sessions = three_ordered_sessions()
        sessions[0]["steps"][0]["ts"] = "not-a-timestamp"
        result = self.propose(sessions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("timestamp unchecked", result.stderr)

    def test_an_unreadable_session_report_is_unchecked_not_clean(self) -> None:
        result = self.compile_run("propose", "--task", TASK, "--sessions-json", str(self.root / "absent.json"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("session report unreadable", result.stderr)

    def test_an_unreadable_rule_inventory_is_unchecked_not_clean(self) -> None:
        (self.root / "engine" / "runbook" / "rules.tsv").unlink()
        result = self.propose(three_ordered_sessions())
        self.assertEqual(result.returncode, 2)
        self.assertIn("rule inventory unreadable", result.stderr)

    def test_an_unreadable_hook_inventory_is_unchecked_not_clean(self) -> None:
        (self.root / "engine" / "hooks" / "hooks.toml").unlink()
        result = self.propose(three_ordered_sessions())
        self.assertEqual(result.returncode, 2)
        self.assertIn("hook inventory unreadable", result.stderr)

    def test_no_sessions_at_all_is_unchecked_not_clean(self) -> None:
        result = self.compile_run("propose", "--task", TASK)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no sessions were given", result.stderr)


class TranscriptMiningTests(CompileFixture):
    def test_a_named_transcript_is_mined_by_the_step_order_miner(self) -> None:
        metrics = self.root / "metrics"
        metrics.mkdir()
        transcript = self.root / "session.jsonl"
        transcript.write_text("".join(json.dumps(row) + "\n" for row in [
            {"type": "user", "message": {"role": "user", "content": "fix the broken widget, it crashes"},
             "timestamp": "2026-10-20T10:00:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Looking."}]},
             "timestamp": "2026-10-20T10:01:00Z"},
        ]), encoding="utf-8")
        result = self.compile_run(
            "propose", "--task", TASK, "--metrics-dir", str(metrics), str(transcript),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("across the 1 session(s) of that task type", result.stderr)
        self.assertIn("hook firings unchecked", result.stderr)


class BacktestTests(CompileFixture):
    def chronological_sessions(self) -> list[dict]:
        built = [session(f"early-{number}", number + 1, ORDERED_RUN, month=8) for number in range(4)]
        scored = [
            session("late-1", 20, (("intervention", "told-you"),) + ORDERED_RUN),
            session("late-2", 21, (("intervention", "agent-blame"),) + ORDERED_RUN),
            session("late-3", 22, (("skill", "gamma-skill"), ("hook", "alpha-gate"))),
        ]
        return built + scored

    def test_the_backtest_prints_its_table_with_the_split_counts(self) -> None:
        result = self.backtest(
            self.chronological_sessions(),
            "--now", "2026-10-01T00:00:00Z",
            "--cutoff", "2026-09-01T00:00:00Z",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| measure | value |", result.stdout)
        self.assertIn("| sessions built from (before cutoff) | 4 |", result.stdout)
        self.assertIn("| sessions scored on (after cutoff) | 3 |", result.stdout)
        self.assertIn("| compiled steps | 3 |", result.stdout)

    def test_the_default_cutoff_is_the_median_session_start(self) -> None:
        result = self.backtest(self.chronological_sessions(), "--now", "2026-10-01T00:00:00Z")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(median session start)", result.stdout)
        self.assertIn("| sessions built from (before cutoff) | 3 |", result.stdout)
        self.assertIn("| sessions scored on (after cutoff) | 4 |", result.stdout)

    def test_the_backtest_counts_interventions_a_later_step_would_have_caught(self) -> None:
        result = self.backtest(self.chronological_sessions(), "--now", "2026-10-01T00:00:00Z")
        self.assertIn("| interventions in scored sessions | 2 |", result.stdout)
        self.assertIn("| interventions caught earlier | 2 |", result.stdout)

    def test_the_backtest_counts_a_pair_whose_order_did_not_hold(self) -> None:
        result = self.backtest(self.chronological_sessions(), "--now", "2026-10-01T00:00:00Z")
        self.assertIn("| order false fires | 2 |", result.stdout)

    def test_the_backtest_prints_the_injected_token_estimate(self) -> None:
        result = self.backtest(self.chronological_sessions(), "--now", "2026-10-01T00:00:00Z")
        self.assertIn("| injected tokens per session (estimated) |", result.stdout)
        self.assertIn("| injected tokens over scored sessions |", result.stdout)

    def test_a_declared_cutoff_overrides_the_median_split(self) -> None:
        result = self.backtest(
            self.chronological_sessions(),
            "--now", "2026-10-01T00:00:00Z",
            "--cutoff", "2026-09-01T00:00:00Z",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(declared)", result.stdout)
        self.assertIn("| sessions built from (before cutoff) | 4 |", result.stdout)

    def test_the_window_leaves_out_a_session_older_than_the_days_given(self) -> None:
        sessions = self.chronological_sessions()
        sessions.append(session("ancient-1", 1, ORDERED_RUN, month=1))
        result = self.backtest(sessions, "--now", "2026-10-01T00:00:00Z")
        self.assertIn("| sessions outside the window | 1 |", result.stdout)

    def test_too_few_sessions_before_the_cutoff_backtests_nothing(self) -> None:
        result = self.backtest(
            [session("one-1", 20, ORDERED_RUN), session("one-2", 21, ORDERED_RUN)],
            "--now", "2026-10-01T00:00:00Z",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("backtested nothing for bugfix", result.stderr)

    def test_a_session_with_no_timestamp_is_counted_as_unchecked(self) -> None:
        sessions = self.chronological_sessions()
        undated = session("undated-1", 23, ORDERED_RUN)
        for step in undated["steps"]:
            step["ts"] = None
        sessions.append(undated)
        result = self.backtest(sessions, "--now", "2026-10-01T00:00:00Z")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| sessions with no timestamp (unchecked) | 1 |", result.stdout)

    def test_a_task_type_no_session_carries_is_named_as_such(self) -> None:
        result = self.backtest(
            [session("other-1", 20, ORDERED_RUN, task="ship-pr")],
            "--now", "2026-10-01T00:00:00Z",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("0 of 1 mined session(s) carry that task type", result.stderr)

    def test_a_window_that_excludes_every_session_is_named_as_such(self) -> None:
        result = self.backtest(
            [session("ancient-1", 1, ORDERED_RUN, month=1)],
            "--now", "2026-10-01T00:00:00Z",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 of 1 mined session(s) carry that task type", result.stderr)
        self.assertIn("none of the rest falls in the last 90 day(s)", result.stderr)

    def test_an_unreadable_now_stamp_is_unchecked_not_clean(self) -> None:
        result = self.backtest(self.chronological_sessions(), "--now", "yesterday")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--now unusable", result.stderr)


if __name__ == "__main__":
    unittest.main()
