#!/usr/bin/env python3
"""Tests for runbook-gate: one measured row per step of the playbook the router injected."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOK_DIR = Path(__file__).resolve().parent.parent
HOOKS_ROOT = HOOK_DIR.parent
REPO = HOOKS_ROOT.parent.parent
sys.path.insert(0, str(HOOK_DIR))
sys.path.insert(0, str(HOOKS_ROOT / "_sdk"))

import detect  # noqa: E402

ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"
PLAYBOOK = REPO / "engine" / "skills" / "create-playbook" / "playbooks" / "create-playbook.md"
TEST_MODEL = "gpt-5.6-sol"


def router_injection(prompt: str) -> str | None:
    """The context the real playbook-router injects for this prompt in this checkout."""
    path = HOOKS_ROOT / "playbook-router" / "detect.py"
    spec = importlib.util.spec_from_file_location("runbook_gate_router_detect", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["runbook_gate_router_detect"] = module
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as empty_home:
        return module.decide({"prompt": prompt, "cwd": str(REPO)}, home=Path(empty_home))


def injection_row(context: str) -> str:
    """One Claude transcript row shaped like a recorded UserPromptSubmit injection."""
    return json.dumps({
        "type": "attachment",
        "attachment": {
            "type": "hook_additional_context",
            "content": [context],
            "hookEvent": "UserPromptSubmit",
        },
    })


def reply_row(text: str) -> str:
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


def tool_result_row(text: str) -> str:
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": [{"type": "text", "text": text}]}]},
    })


def write_transcript(directory: Path, rows: list[str], name: str = "session.jsonl") -> str:
    path = directory / name
    path.write_text("".join(row + "\n" for row in rows), encoding="utf-8")
    return str(path)


def statuses(findings: list) -> dict[str, str]:
    """Map each finding's subject to the status its rule id ends with."""
    return {finding.subject: finding.rule_id.rsplit(".", 1)[1] for finding in findings}


def hook_environment(metrics: Path) -> dict[str, str]:
    """A machine's own flag files and PostHog key kept out of a row-writing run."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("CATSTACK_POSTHOG_") and name != "CATSTACK_HOOK_MODE_RUNBOOK_GATE"
    }
    environment.update({
        "CATSTACK_HOOK_METRICS_DIR": str(metrics),
        "CATSTACK_HOOK_TEST_MODEL": TEST_MODEL,
        "CATSTACK_POSTHOG_API_KEY": "",
        "CATSTACK_SKIP_ENV_FILES": os.pathsep.join([
            os.path.join(os.path.expanduser("~"), ".catstack.env"),
            str(REPO / ".env"),
        ]),
    })
    return environment


def run_stdin(payload: str, metrics: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_environment(metrics),
    )


def run_entrypoint(payload: dict, metrics: Path) -> subprocess.CompletedProcess:
    return run_stdin(json.dumps(payload), metrics)


def rows_written(metrics: Path) -> list[dict]:
    return [
        json.loads(line)
        for path in sorted(metrics.glob("events-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


class TestRealInjection(unittest.TestCase):
    def test_router_still_injects_the_shape_this_gate_parses(self) -> None:
        context = router_injection("create playbook")
        self.assertIsNotNone(context)
        self.assertIsNotNone(detect.INJECTION.search(context))
        playbook, sources = detect.last_injection([context])
        self.assertEqual("create-playbook", playbook)
        self.assertEqual(str(PLAYBOOK), sources[-1])

    def test_detects_every_step_of_the_real_playbook(self) -> None:
        context = router_injection("create playbook")
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(Path(tmp), [injection_row(context)])
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        expected = detect.parse_steps(PLAYBOOK.read_text(encoding="utf-8"))
        self.assertEqual(8, len(expected))
        self.assertEqual(len(expected), len(findings))
        self.assertEqual(
            [f"{step.rule_id}.unknown" for step in expected],
            [finding.rule_id for finding in findings],
        )


class TestStatusPerStep(unittest.TestCase):
    def transcript(self, directory: Path, reply: str, tool_result: str) -> str:
        context = router_injection("create playbook")
        return write_transcript(directory, [
            injection_row(context),
            reply_row(reply),
            tool_result_row(tool_result),
        ])

    def test_flags_done_skipped_overridden_and_unknown_from_one_session(self) -> None:
        reply = (
            "Working the list.\n"
            "3. Pick each step's level from what an event can see -- skip: every level is already soft\n"
            "- 5. Write the fixture pair before installing -- override: the fixtures live in the sibling slice\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), reply, "clean: 1 playbook(s); check_playbook_exit 0")
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        found = statuses(findings)
        self.assertEqual(detect.STATUS_SKIPPED, found["create-playbook step 3"])
        self.assertEqual(detect.STATUS_OVERRIDDEN, found["create-playbook step 5"])
        self.assertEqual(detect.STATUS_DONE, found["create-playbook step 6"])
        self.assertEqual(detect.STATUS_UNKNOWN, found["create-playbook step 1"])

    def test_done_row_names_where_the_proof_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "no declarations here", "check_playbook_exit=0")
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        done = [finding for finding in findings if finding.rule_id.endswith(detect.STATUS_DONE)]
        self.assertEqual(1, len(done))
        self.assertIn("check_playbook_exit", done[0].evidence)
        self.assertIn(transcript, done[0].evidence)

    def test_a_step_word_declaration_still_flags_the_right_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "skip: step 4 needs no new evidence key", "")
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertEqual(detect.STATUS_SKIPPED, statuses(findings)["create-playbook step 4"])

    def test_evidence_key_in_the_reply_alone_is_not_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "I ran it, check_playbook_exit was 0", "")
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertNotIn(detect.STATUS_DONE, set(statuses(findings).values()))

    def test_a_bare_skip_with_no_reason_stays_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "3. Pick each step's level -- skip:", "")
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertEqual(detect.STATUS_UNKNOWN, statuses(findings)["create-playbook step 3"])

    def test_a_soft_step_with_no_evidence_key_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "nothing declared", "")
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        soft = [finding for finding in findings if finding.subject == "create-playbook step 3"]
        self.assertIn("names no evidence key", soft[0].evidence)


class TestSilent(unittest.TestCase):
    def test_stays_silent_when_no_playbook_was_injected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(Path(tmp), [
                reply_row("Just a normal turn with no routed playbook."),
                tool_result_row("check_playbook_exit 0"),
            ])
            self.assertEqual([], detect.detect({"hook_event_name": "Stop", "transcript_path": transcript}))

    def test_stays_silent_on_a_second_stop_in_one_turn(self) -> None:
        context = router_injection("create playbook")
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(Path(tmp), [injection_row(context)])
            findings = detect.detect({
                "hook_event_name": "Stop",
                "transcript_path": transcript,
                "stop_hook_active": True,
            })
        self.assertEqual([], findings)

    def test_a_prompt_the_router_ignores_leaves_nothing_to_measure(self) -> None:
        self.assertIsNone(router_injection("explain create playbook to me"))


class TestUnchecked(unittest.TestCase):
    def unchecked_reason(self, payload: dict) -> str:
        findings = detect.detect(payload)
        self.assertEqual(1, len(findings))
        self.assertEqual(detect.RULE_UNCHECKED, findings[0].rule_id)
        return findings[0].evidence

    def test_unreadable_playbook_reports_one_unchecked_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "gone" / "playbook.md"
            context = (
                "Playbook: widget-repair\n"
                f"Read and apply the full source at {missing}, including its constraints.\n"
                "Follow these steps in order:\n"
            )
            transcript = write_transcript(Path(tmp), [injection_row(context)])
            reason = self.unchecked_reason({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertIn("playbook unreadable", reason)

    def test_a_playbook_with_no_bound_steps_reports_unchecked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare.md"
            bare.write_text("# Widget repair\n\n## Steps\n\n1. Do the thing\n", encoding="utf-8")
            context = (
                "Playbook: widget-repair\n"
                f"Read and apply the full source at {bare}, including its constraints.\n"
                "Follow these steps in order:\n"
            )
            transcript = write_transcript(Path(tmp), [injection_row(context)])
            reason = self.unchecked_reason({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertIn("no bound step lines", reason)

    def test_missing_transcript_reports_one_unchecked_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reason = self.unchecked_reason({
                "hook_event_name": "Stop",
                "transcript_path": str(Path(tmp) / "never-written.jsonl"),
            })
        self.assertIn("transcript unreadable", reason)

    def test_a_payload_with_no_transcript_path_reports_unchecked(self) -> None:
        reason = self.unchecked_reason({"hook_event_name": "Stop", "session_id": "no-transcript"})
        self.assertIn("named no transcript", reason)

    def test_malformed_transcript_lines_are_skipped_and_the_rest_measured(self) -> None:
        context = router_injection("create playbook")
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(Path(tmp), ["{not json at all", injection_row(context), "[]"])
            findings = detect.detect({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertEqual(8, len(findings))


class TestEntrypoint(unittest.TestCase):
    def test_writes_one_row_per_step_and_never_speaks(self) -> None:
        context = router_injection("create playbook")
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            transcript = write_transcript(Path(tmp), [
                injection_row(context),
                tool_result_row("clean: 1 playbook(s) -- check_playbook_exit 0"),
            ])
            result = run_entrypoint({
                "hook_event_name": "Stop",
                "session_id": "runbook-gate-entrypoint",
                "transcript_path": transcript,
            }, metrics)
            rows = rows_written(metrics)

        self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))
        self.assertEqual(8, len(rows))
        self.assertEqual({"runbook-gate"}, {row["hook"] for row in rows})
        self.assertEqual({"off"}, {row["mode"] for row in rows})
        self.assertEqual({"silent"}, {row["action"] for row in rows})
        self.assertIn("principle-prove-it.done", {row["rule_id"] for row in rows})
        self.assertEqual(1, len({row["subject_hash"] for row in rows if row["rule_id"].endswith(".done")}))

    def test_an_unreadable_playbook_writes_an_unchecked_row_not_silence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            context = (
                "Playbook: widget-repair\n"
                f"Read and apply the full source at {Path(tmp) / 'gone.md'}, including its constraints.\n"
                "Follow these steps in order:\n"
            )
            transcript = write_transcript(Path(tmp), [injection_row(context)])
            result = run_entrypoint({
                "hook_event_name": "Stop",
                "session_id": "runbook-gate-unchecked",
                "transcript_path": transcript,
            }, metrics)
            rows = rows_written(metrics)

        self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))
        self.assertEqual(1, len(rows))
        self.assertEqual(detect.RULE_UNCHECKED, rows[0]["rule_id"])
        self.assertEqual("unchecked", rows[0]["action"])

    def test_a_session_with_no_playbook_writes_one_silent_row_with_no_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            transcript = write_transcript(Path(tmp), [reply_row("ordinary turn")])
            result = run_entrypoint({
                "hook_event_name": "Stop",
                "session_id": "runbook-gate-clean",
                "transcript_path": transcript,
            }, metrics)
            rows = rows_written(metrics)

        self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))
        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["rule_id"])
        self.assertEqual("silent", rows[0]["action"])

    def test_garbage_on_stdin_fails_open_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_stdin("not json", Path(tmp) / "metrics")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("catstack-hook-error runbook-gate", result.stderr)


if __name__ == "__main__":
    unittest.main()
