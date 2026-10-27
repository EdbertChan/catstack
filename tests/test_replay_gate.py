"""Replaying the runbook gate over fixture transcripts counts fired, would-block and false-fire stops."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPLAY = REPO / "scripts" / "runbook" / "replay_gate.py"
GATE_MODE_ENV = "CATSTACK_HOOK_MODE_RUNBOOK_GATE"
PLAYBOOK = """---
runbook: demo
version: 1
applies_to:
  - engine/hooks/alpha-gate/
compiled_from:
  - alpha-gate
playbook-trigger: demo task
enforcement_profile: guided
---

# Demo

## 1. Paste the command output [alpha-gate · hard · evidence: pasted_output · @Stop]

Run it and paste what it printed.
"""
PROJECT_DIRECTORY_NAME = "-home-user-repo"
RECENT_DAY = "2026-10-20"
HUMAN_PROMPT = "fix the broken widget"
INTERVENTION_PROMPT = "i already told you to paste the output"
DONE_REPLY = "Everything is done."
PROVEN_TOOL_RESULT = "ran the check: pasted_output 3 passed"


def attachment_row(text: str) -> dict:
    return {
        "type": "attachment",
        "attachment": {"type": "hook_additional_context", "content": [text], "hookEvent": "UserPromptSubmit"},
    }


def human_row(text: str, minute: int) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}, "timestamp": f"{RECENT_DAY}T10:{minute:02d}:00Z"}


def reply_row(text: str, minute: int) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        "timestamp": f"{RECENT_DAY}T10:{minute:02d}:00Z",
    }


def tool_result_row(text: str, minute: int) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": [{"type": "text", "text": text}]}]},
        "timestamp": f"{RECENT_DAY}T10:{minute:02d}:00Z",
    }


def replay_environment() -> dict[str, str]:
    """A machine's own gate-mode override and env files kept out of the replay."""
    environment = {name: value for name, value in os.environ.items() if name != GATE_MODE_ENV}
    environment["CATSTACK_SKIP_ENV_FILES"] = os.pathsep.join([
        os.path.join(os.path.expanduser("~"), ".catstack.env"),
        str(REPO / ".env"),
    ])
    return environment


class ReplayFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.projects = self.root / "projects" / PROJECT_DIRECTORY_NAME
        self.projects.mkdir(parents=True)
        self.playbook = self.root / "demo-playbook.md"
        self.playbook.write_text(PLAYBOOK, encoding="utf-8")
        self.injection = (
            f"Playbook: demo\nRead and apply the full source at {self.playbook}, including its constraints."
        )

    def write_session(self, name: str, rows: list[dict], directory: Path | None = None) -> Path:
        target = (directory or self.projects) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return target

    def blocked_without_intervention(self, name: str = "blocked-alone.jsonl") -> Path:
        return self.write_session(name, [
            human_row(HUMAN_PROMPT, 0),
            attachment_row(self.injection),
            reply_row(DONE_REPLY, 1),
        ])

    def blocked_then_intervened(self, name: str = "blocked-then-told.jsonl") -> Path:
        return self.write_session(name, [
            human_row(HUMAN_PROMPT, 0),
            attachment_row(self.injection),
            reply_row(DONE_REPLY, 1),
            human_row(INTERVENTION_PROMPT, 2),
            reply_row("Pasting it now.", 3),
        ])

    def proven(self, name: str = "proven.jsonl", directory: Path | None = None) -> Path:
        return self.write_session(name, [
            human_row(HUMAN_PROMPT, 0),
            attachment_row(self.injection),
            tool_result_row(PROVEN_TOOL_RESULT, 1),
            reply_row(DONE_REPLY, 2),
        ], directory)

    def without_injection(self, name: str = "no-injection.jsonl") -> Path:
        return self.write_session(name, [human_row("just chatting", 0), reply_row(DONE_REPLY, 1)])

    def replay(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REPLAY), *arguments],
            capture_output=True,
            text=True,
            env=replay_environment(),
        )

    def replay_report(self, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        report = self.root / "report.json"
        result = self.replay(*arguments, "--json", str(report))
        return result, json.loads(report.read_text(encoding="utf-8"))

    def replay_discovered(self, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        return self.replay_report(
            "--projects-dir", str(self.root / "projects"),
            "--now", f"{RECENT_DAY}T23:00:00Z",
            *arguments,
        )


class ReplayCountTests(ReplayFixture):
    def test_a_block_with_no_intervention_after_it_is_a_false_fire(self) -> None:
        self.blocked_without_intervention()
        result, report = self.replay_discovered()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["totals"]["would_block"], 1)
        self.assertEqual(report["totals"]["false_fire"], 1)
        self.assertEqual(report["totals"]["blocked_then_intervened"], 0)

    def test_a_block_followed_by_an_intervention_is_not_a_false_fire(self) -> None:
        self.blocked_then_intervened()
        result, report = self.replay_discovered()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["totals"]["would_block"], 1)
        self.assertEqual(report["totals"]["false_fire"], 0)
        self.assertEqual(report["totals"]["blocked_then_intervened"], 1)

    def test_a_proven_step_fires_without_blocking(self) -> None:
        self.proven()
        result, report = self.replay_discovered()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["totals"]["fired"], 1)
        self.assertEqual(report["totals"]["would_block"], 0)

    def test_a_session_with_no_injected_playbook_never_fires(self) -> None:
        self.without_injection()
        result, report = self.replay_discovered()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["totals"]["stops"], 1)
        self.assertEqual(report["totals"]["fired"], 0)

    def test_every_turn_ending_reply_is_replayed_as_its_own_stop(self) -> None:
        self.blocked_then_intervened()
        _result, report = self.replay_discovered()
        self.assertEqual(report["totals"]["stops"], 2)

    def test_a_block_at_the_last_stop_is_counted_on_its_own_line(self) -> None:
        self.blocked_without_intervention()
        result, report = self.replay_discovered()
        self.assertEqual(report["totals"]["final_stop_blocks"], 1)
        self.assertIn("sat at a session's last stop", result.stdout)


class ReplayTableTests(ReplayFixture):
    def test_the_table_and_the_false_fire_percentage_are_printed(self) -> None:
        self.blocked_without_intervention()
        self.blocked_then_intervened()
        self.proven()
        self.without_injection()
        result, report = self.replay_discovered()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| session | stops | fired | would-block | false-fire |", result.stdout)
        self.assertIn("| totals (4 session(s)) | 5 | 4 | 2 | 1 | 1 | 0 |", result.stdout)
        self.assertIn("folded 1 session(s) the gate did nothing in into the totals row", result.stdout)
        self.assertIn("false-fire rate: 1 of 2 would-block(s) = 50.0 percent", result.stdout)
        self.assertEqual(report["false_fire_percent"], 50.0)

    def test_all_sessions_lists_the_ones_the_gate_did_nothing_in(self) -> None:
        self.blocked_without_intervention()
        self.without_injection()
        result, _report = self.replay_discovered("--all-sessions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no-injection.jsonl", result.stdout)
        self.assertNotIn("folded", result.stdout)

    def test_a_rate_over_the_ceiling_says_the_hard_gate_may_not_stay_hard(self) -> None:
        self.blocked_without_intervention()
        result, _report = self.replay_discovered()
        self.assertIn("over the ceiling, so the hard gate may not stay hard", result.stdout)

    def test_no_block_reports_the_rate_as_unchecked_not_as_zero(self) -> None:
        self.proven()
        self.without_injection()
        result, report = self.replay_discovered()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("false-fire rate: unchecked", result.stdout)
        self.assertIsNone(report["false_fire_percent"])


class ReplayDiscoveryTests(ReplayFixture):
    def test_a_transcript_older_than_the_window_is_skipped(self) -> None:
        self.blocked_without_intervention()
        old = self.proven("older-than-the-window.jsonl")
        os.utime(old, (0, 0))
        result, report = self.replay_discovered("--days", "90")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped 1 transcript(s) older than the 90-day window", result.stdout)
        self.assertEqual(len(report["sessions"]), 1)

    def test_a_subagent_transcript_is_skipped_as_the_parent_session_work(self) -> None:
        self.blocked_without_intervention()
        self.proven("agent-1.jsonl", directory=self.projects / "session-a" / "subagents")
        result, report = self.replay_discovered()
        self.assertIn("skipped 1 subagent transcript(s)", result.stdout)
        self.assertEqual(len(report["sessions"]), 1)

    def test_a_missing_transcript_directory_is_unchecked_not_clean(self) -> None:
        result = self.replay("--projects-dir", str(self.root / "absent"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no transcript directory", result.stderr)

    def test_an_empty_window_replays_nothing_and_says_so(self) -> None:
        old = self.proven()
        os.utime(old, (0, 0))
        result = self.replay(
            "--projects-dir", str(self.root / "projects"),
            "--now", f"{RECENT_DAY}T23:00:00Z",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("no transcript to replay in this window", result.stderr)

    def test_an_unreadable_now_stamp_is_unchecked_not_clean(self) -> None:
        self.blocked_without_intervention()
        result = self.replay("--projects-dir", str(self.root / "projects"), "--now", "yesterday")
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not an ISO timestamp", result.stderr)

    def test_named_paths_replace_discovery_and_say_the_window_was_not_applied(self) -> None:
        path = self.blocked_without_intervention()
        result, report = self.replay_report(str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("so the 90-day window was not applied", result.stdout)
        self.assertEqual(len(report["sessions"]), 1)


class ReplayUncheckedTests(ReplayFixture):
    def test_a_malformed_line_is_reported_and_never_counted_clean(self) -> None:
        self.blocked_without_intervention()
        (self.projects / "broken.jsonl").write_text("not json at all\n", encoding="utf-8")
        result, report = self.replay_discovered()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("were not readable rows", result.stderr)
        broken = [entry for entry in report["sessions"] if entry["path"].endswith("broken.jsonl")][0]
        self.assertEqual(broken["stops"], 0)
        self.assertTrue(broken["unchecked"])

    def test_a_partly_checked_session_is_named_with_its_reason(self) -> None:
        self.blocked_without_intervention()
        result, _report = self.replay_discovered()
        self.assertIn("replayed only partly", result.stderr)
        self.assertIn("restated-rule", result.stderr)

    def test_a_transcript_set_with_no_replayable_stop_is_unchecked(self) -> None:
        (self.projects / "broken.jsonl").write_text("not json at all\n", encoding="utf-8")
        result, _report = self.replay_discovered()
        self.assertEqual(result.returncode, 2)
        self.assertIn("no stop was replayed", result.stderr)


if __name__ == "__main__":
    unittest.main()
