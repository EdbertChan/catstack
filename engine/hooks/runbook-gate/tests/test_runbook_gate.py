#!/usr/bin/env python3
"""Tests for runbook-gate: one measured row per step, and one block on a done claim over an unproven hard step."""
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

import counters  # noqa: E402
import detect  # noqa: E402
import progress  # noqa: E402

ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLAYBOOK = REPO / "engine" / "skills" / "create-playbook" / "playbooks" / "create-playbook.md"
TEST_MODEL = "gpt-5.6-sol"
HARNESS = "claude"
DONE_CLAIM = "All eight steps are done."
HARD_EVIDENCE_KEYS = (
    "router_trigger_free",
    "step_rule_binding",
    "prose_fixture_pair",
    "check_playbook_exit",
    "injected_steps_pasted",
    "pull_request_url",
)


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
    """A machine's own flag files, PostHog key and progress notes kept out of a row-writing run."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("CATSTACK_POSTHOG_") and name != "CATSTACK_HOOK_MODE_RUNBOOK_GATE"
    }
    environment.update({
        "CATSTACK_HOOK_METRICS_DIR": str(metrics),
        progress.STATE_DIR_ENV: str(metrics.parent / "runbook-notes"),
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


def measure_steps(payload: dict) -> list:
    """The per-step rows one Stop recorded, which the runtime logs without rendering them."""
    detect.detect(payload)
    return payload.get("_catstack_silent_findings") or []


def read_fixture(name: str) -> dict:
    """One gate fixture: the prompt to route, the session text, and the outcome it must get."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class NotesInTempDir(unittest.TestCase):
    """Every in-process test keeps its progress notes out of the machine's own cache."""

    def setUp(self) -> None:
        self.notes = tempfile.TemporaryDirectory()
        self.addCleanup(self.notes.cleanup)
        previous = os.environ.get(progress.STATE_DIR_ENV)
        os.environ[progress.STATE_DIR_ENV] = os.path.join(self.notes.name, "notes")
        self.addCleanup(self._restore, previous)

    def _restore(self, previous: str | None) -> None:
        if previous is None:
            os.environ.pop(progress.STATE_DIR_ENV, None)
        else:
            os.environ[progress.STATE_DIR_ENV] = previous

    def session(
        self,
        directory: Path,
        prompt: str,
        reply: str,
        tool_results: list[str],
        playbook_source: Path | None = None,
    ) -> str:
        """One transcript: the router's real injection, the agent's reply, then each tool result."""
        context = router_injection(prompt)
        if playbook_source is not None:
            routed = detect.last_injection([context])
            self.assertIsNotNone(routed)
            source = routed[1][-1]
            self.assertEqual(1, context.count(source))
            context = context.replace(source, str(playbook_source))
        rows = [injection_row(context), reply_row(reply)]
        rows.extend(tool_result_row(text) for text in tool_results)
        return write_transcript(directory, rows)

    def stop(self, transcript: str, harness: str = HARNESS, session_id: str = "") -> tuple[list, dict]:
        """One Stop payload through the detector, with the event the real harness would carry."""
        payload = {"hook_event_name": "Stop", "transcript_path": transcript, "_catstack_harness": harness}
        if session_id:
            payload["session_id"] = session_id
        return detect.detect(payload), payload

    def note(self, payload: dict) -> dict:
        return json.loads(Path(progress.note_path(counters.session_key(payload))).read_text(encoding="utf-8"))


def rows_written(metrics: Path) -> list[dict]:
    return [
        json.loads(line)
        for path in sorted(metrics.glob("events-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


class TestRealInjection(NotesInTempDir):
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
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        expected = detect.parse_steps(PLAYBOOK.read_text(encoding="utf-8"))
        self.assertEqual(8, len(expected))
        self.assertEqual(len(expected), len(findings))
        self.assertEqual(
            [f"{step.rule_id}.unknown" for step in expected],
            [finding.rule_id for finding in findings],
        )


class TestStatusPerStep(NotesInTempDir):
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
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        found = statuses(findings)
        self.assertEqual(detect.STATUS_SKIPPED, found["create-playbook step 3"])
        self.assertEqual(detect.STATUS_OVERRIDDEN, found["create-playbook step 5"])
        self.assertEqual(detect.STATUS_DONE, found["create-playbook step 6"])
        self.assertEqual(detect.STATUS_UNKNOWN, found["create-playbook step 1"])

    def test_done_row_names_where_the_proof_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "no declarations here", "check_playbook_exit=0")
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        done = [finding for finding in findings if finding.rule_id.endswith(detect.STATUS_DONE)]
        self.assertEqual(1, len(done))
        self.assertIn("check_playbook_exit", done[0].evidence)
        self.assertIn(transcript, done[0].evidence)

    def test_a_step_word_declaration_still_flags_the_right_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "skip: step 4 needs no new evidence key", "")
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertEqual(detect.STATUS_SKIPPED, statuses(findings)["create-playbook step 4"])

    def test_evidence_key_in_the_reply_alone_is_not_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "I ran it, check_playbook_exit was 0", "")
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertNotIn(detect.STATUS_DONE, set(statuses(findings).values()))

    def test_a_bare_skip_with_no_reason_stays_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "3. Pick each step's level -- skip:", "")
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertEqual(detect.STATUS_UNKNOWN, statuses(findings)["create-playbook step 3"])

    def test_a_soft_step_with_no_evidence_key_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.transcript(Path(tmp), "nothing declared", "")
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        soft = [finding for finding in findings if finding.subject == "create-playbook step 3"]
        self.assertIn("names no evidence key", soft[0].evidence)


class TestSilent(NotesInTempDir):
    def test_stays_silent_when_no_playbook_was_injected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(Path(tmp), [
                reply_row("Just a normal turn with no routed playbook."),
                tool_result_row("check_playbook_exit 0"),
            ])
            payload = {"hook_event_name": "Stop", "transcript_path": transcript}
            self.assertEqual([], detect.detect(payload))
            self.assertEqual([], payload.get("_catstack_silent_findings") or [])

    def test_stays_silent_on_a_second_stop_in_one_turn(self) -> None:
        context = router_injection("create playbook")
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(Path(tmp), [injection_row(context)])
            payload = {
                "hook_event_name": "Stop",
                "transcript_path": transcript,
                "stop_hook_active": True,
            }
            findings = detect.detect(payload)
        self.assertEqual([], findings)
        self.assertEqual([], payload.get("_catstack_silent_findings") or [])

    def test_a_prompt_the_router_ignores_leaves_nothing_to_measure(self) -> None:
        self.assertIsNone(router_injection("explain create playbook to me"))


class TestUnchecked(NotesInTempDir):
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
            findings = measure_steps({"hook_event_name": "Stop", "transcript_path": transcript})
        self.assertEqual(8, len(findings))


class TestEntrypoint(NotesInTempDir):
    def test_writes_one_row_per_step_and_stays_silent_without_a_done_claim(self) -> None:
        context = router_injection("create playbook")
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            transcript = write_transcript(Path(tmp), [
                injection_row(context),
                reply_row("Step 6 is run; the rest of the list is still open."),
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
        self.assertEqual({"stop"}, {row["mode"] for row in rows})
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


class TestFixtures(NotesInTempDir):
    def outcome(self, name: str) -> tuple[list, dict, dict]:
        fixture = read_fixture(name)
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(
                Path(tmp),
                fixture["prompt"],
                fixture["reply"],
                fixture["tool_results"],
                FIXTURES / fixture["playbook_source"] if fixture.get("playbook_source") else None,
            )
            findings, payload = self.stop(transcript)
        return findings, fixture, payload

    def check(self, name: str) -> list:
        findings, fixture, _payload = self.outcome(name)
        blocks = [finding for finding in findings if finding.rule_id == detect.RULE_UNPROVEN]
        self.assertEqual(fixture["expect_block"], bool(blocks), [finding.rule_id for finding in findings])
        for phrase in fixture["expect_message_contains"]:
            self.assertIn(phrase, blocks[0].message)
        return blocks

    def test_fail_before_a_done_claim_over_an_unproven_hard_step_is_blocked(self) -> None:
        blocks = self.check("fail_before_done_claim_over_unproven_hard_step")
        self.assertIn(detect.OVERRIDE_SYNTAX, blocks[0].message)

    def test_pass_after_every_hard_step_proven_allows_the_same_claim(self) -> None:
        self.assertEqual([], self.check("pass_after_every_hard_step_proven"))

    def test_an_override_with_a_reason_clears_the_block(self) -> None:
        self.assertEqual([], self.check("override_with_a_reason_clears_the_block"))

    def test_an_advisory_playbook_is_never_blocked(self) -> None:
        findings, _fixture, payload = self.outcome("advisory_profile_is_never_blocked")
        blocks = [finding for finding in findings if finding.rule_id == detect.RULE_UNPROVEN]
        note = self.note(payload)
        self.assertEqual([], blocks)
        self.assertEqual("advisory", note["profile"])
        self.assertEqual(["hard"], [row["level"] for row in note["steps"]])
        self.assertEqual(["soft"], [row["effective_level"] for row in note["steps"]])

    def test_every_fixture_says_why_it_lands_on_its_side(self) -> None:
        names = sorted(path.stem for path in FIXTURES.glob("*.json"))
        self.assertEqual(
            [
                "advisory_profile_is_never_blocked",
                "fail_before_done_claim_over_unproven_hard_step",
                "override_with_a_reason_clears_the_block",
                "pass_after_every_hard_step_proven",
            ],
            names,
        )
        for name in names:
            with self.subTest(name=name):
                self.assertGreater(len(read_fixture(name)["why"].split()), 20)


class TestDoneClaim(NotesInTempDir):
    def findings(self, reply: str, tool_results: list[str] | None = None, prompt: str = "create playbook") -> list:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(Path(tmp), prompt, reply, tool_results or [])
            findings, _payload = self.stop(transcript)
        return findings

    def rule_ids(self, reply: str, tool_results: list[str] | None = None) -> list[str]:
        return [finding.rule_id for finding in self.findings(reply, tool_results)]

    def test_a_reply_that_claims_nothing_is_not_blocked(self) -> None:
        self.assertEqual([], self.rule_ids("Working the list; step 1 is still open."))

    def test_a_negated_done_claim_is_not_a_claim(self) -> None:
        self.assertEqual([], self.rule_ids("Step 1 is not done yet, so I am staying on it."))

    def test_a_done_claim_inside_a_fenced_block_is_not_a_claim(self) -> None:
        self.assertEqual([], self.rule_ids("The runner printed:\n```\nOK, all done\n```\nStill on step 1."))

    def test_a_skip_does_not_clear_a_hard_step(self) -> None:
        self.assertIn(
            detect.RULE_UNPROVEN,
            self.rule_ids(f"skip: step 1 looked fine to me\n{DONE_CLAIM}"),
        )

    def test_an_override_naming_no_reason_does_not_clear_the_block(self) -> None:
        self.assertIn(detect.RULE_UNPROVEN, self.rule_ids(f"override: 1\n{DONE_CLAIM}"))

    def test_a_conditional_step_does_not_block_under_the_guided_profile(self) -> None:
        findings = self.findings(DONE_CLAIM, [" ".join(HARD_EVIDENCE_KEYS)])
        self.assertEqual([], [finding.rule_id for finding in findings])

    def test_the_block_names_every_unproven_hard_step_once(self) -> None:
        findings = self.findings(DONE_CLAIM, ["check_playbook_exit 0"])
        self.assertEqual([detect.RULE_UNPROVEN], [finding.rule_id for finding in findings])
        self.assertEqual("1, 2, 5, 7, 8", findings[0].step)

    def test_a_second_stop_in_one_turn_never_blocks_the_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(Path(tmp), "create playbook", DONE_CLAIM, [])
            findings = detect.detect({
                "hook_event_name": "Stop",
                "transcript_path": transcript,
                "_catstack_harness": HARNESS,
                "stop_hook_active": True,
            })
        self.assertEqual([], findings)

    def test_the_claim_is_read_from_the_stop_payload_when_it_names_the_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(Path(tmp), "create playbook", "Still on step 1.", [])
            findings = detect.detect({
                "hook_event_name": "Stop",
                "transcript_path": transcript,
                "_catstack_harness": HARNESS,
                "last_assistant_message": DONE_CLAIM,
            })
        self.assertEqual([detect.RULE_UNPROVEN], [finding.rule_id for finding in findings])

    def test_a_payload_reply_that_claims_nothing_beats_a_claim_left_in_the_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(Path(tmp), "create playbook", DONE_CLAIM, [])
            findings = detect.detect({
                "hook_event_name": "Stop",
                "transcript_path": transcript,
                "_catstack_harness": HARNESS,
                "last_assistant_message": "One more step to go.",
            })
        self.assertEqual([], findings)

    def test_an_unnamed_harness_reaches_unchecked_and_never_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(Path(tmp), "create playbook", DONE_CLAIM, [])
            findings, payload = self.stop(transcript, harness="")
        self.assertEqual([], findings)
        levels = {row["effective_level"] for row in self.note(payload)["steps"] if row["level"] == "hard"}
        self.assertEqual({"unchecked"}, levels)


class TestProgressNote(NotesInTempDir):
    def test_the_note_records_the_current_step_its_proof_and_each_reason(self) -> None:
        reply = f"override: 1 the phrase came from the task\nskip: step 2 is unchanged here\n{DONE_CLAIM}"
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(Path(tmp), "create playbook", reply, ["check_playbook_exit 0"])
            _findings, payload = self.stop(transcript, session_id="note-shape")
            note = self.note(payload)
        rows = {row["step"]: row for row in note["steps"]}
        self.assertEqual(progress.SCHEMA, note["schema"])
        self.assertEqual("create-playbook", note["playbook"])
        self.assertEqual("guided", note["profile"])
        self.assertEqual(3, note["current_step"])
        self.assertEqual("done", rows[6]["status"])
        self.assertEqual("check_playbook_exit", rows[6]["evidence_ref"])
        self.assertEqual("overridden", rows[1]["status"])
        self.assertEqual("the phrase came from the task", rows[1]["reason"])
        self.assertEqual("skipped", rows[2]["status"])
        self.assertEqual("step 2 is unchanged here", rows[2]["reason"])

    def test_a_step_proven_in_an_earlier_stop_survives_losing_its_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(
                Path(tmp), "create playbook", "Step 6 ran.", ["check_playbook_exit 0"]
            )
            self.stop(transcript, session_id="carry-forward")
            compacted = self.session(Path(tmp), "create playbook", DONE_CLAIM, [])
            findings, payload = self.stop(compacted, session_id="carry-forward")
            rows = {row["step"]: row for row in self.note(payload)["steps"]}
        self.assertEqual("done", rows[6]["status"])
        self.assertIn("carried forward", rows[6]["proof"])
        self.assertNotIn("6", (findings[0].step if findings else "").split(", "))

    def test_an_unreadable_note_says_so_and_still_measures_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self.session(Path(tmp), "create playbook", DONE_CLAIM, [])
            payload = {
                "hook_event_name": "Stop",
                "transcript_path": transcript,
                "_catstack_harness": HARNESS,
                "session_id": "note-unreadable",
            }
            path = Path(progress.note_path(counters.session_key(payload)))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json at all", encoding="utf-8")
            findings = detect.detect(payload)
        self.assertEqual([detect.RULE_UNPROVEN], [finding.rule_id for finding in findings])
        self.assertTrue(any(
            "progress note unreadable" in line for line in payload["_catstack_stderr_lines"]
        ), payload.get("_catstack_stderr_lines"))


class TestProfile(NotesInTempDir):
    def playbook_with(self, directory: Path, front_matter: str) -> str:
        path = directory / "widget-repair.md"
        path.write_text(
            f"---\n{front_matter}---\n\n# Widget repair\n\n"
            "## 1. Run the check [principle-prove-it · hard · evidence: widget_exit · @Stop]\n\nRun it.\n",
            encoding="utf-8",
        )
        return str(path)

    def unchecked_reason(self, front_matter: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            source = self.playbook_with(Path(tmp), front_matter)
            context = (
                "Playbook: widget-repair\n"
                f"Read and apply the full source at {source}, including its constraints.\n"
                "Follow these steps in order:\n"
            )
            transcript = write_transcript(Path(tmp), [injection_row(context), reply_row(DONE_CLAIM)])
            findings, _payload = self.stop(transcript)
        self.assertEqual([detect.RULE_UNCHECKED], [finding.rule_id for finding in findings])
        return findings[0].evidence

    def test_a_playbook_declaring_no_profile_reports_unchecked_not_clean(self) -> None:
        self.assertIn("enforcement_profile is missing", self.unchecked_reason("runbook: widget-repair\n"))

    def test_a_playbook_declaring_an_unknown_profile_reports_unchecked(self) -> None:
        self.assertIn(
            "enforcement_profile is relaxed",
            self.unchecked_reason("runbook: widget-repair\nenforcement_profile: relaxed\n"),
        )

    def test_a_binding_level_this_gate_does_not_know_reaches_unchecked_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self.playbook_with(
                Path(tmp), "runbook: widget-repair\nenforcement_profile: strict\n"
            )
            text = Path(source).read_text(encoding="utf-8").replace("· hard ·", "· mandatory ·")
            Path(source).write_text(text, encoding="utf-8")
            context = (
                "Playbook: widget-repair\n"
                f"Read and apply the full source at {source}, including its constraints.\n"
                "Follow these steps in order:\n"
            )
            transcript = write_transcript(Path(tmp), [injection_row(context), reply_row(DONE_CLAIM)])
            payload = {
                "hook_event_name": "Stop",
                "transcript_path": transcript,
                "_catstack_harness": HARNESS,
                "session_id": "unknown-level",
            }
            blocks = detect.detect(payload)
            rows = payload.get("_catstack_silent_findings") or []
            note = self.note(payload)
        self.assertEqual([], blocks)
        self.assertIn("it reaches unchecked here", rows[0].message)
        self.assertEqual("unchecked", note["steps"][0]["effective_level"])
        self.assertIn("not a level this gate knows", note["steps"][0]["level_reason"])

    def test_the_strict_profile_also_refuses_over_a_conditional_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self.playbook_with(
                Path(tmp), "runbook: widget-repair\nenforcement_profile: strict\n"
            )
            text = Path(source).read_text(encoding="utf-8").replace("· hard ·", "· conditional ·")
            Path(source).write_text(text, encoding="utf-8")
            context = (
                "Playbook: widget-repair\n"
                f"Read and apply the full source at {source}, including its constraints.\n"
                "Follow these steps in order:\n"
            )
            transcript = write_transcript(Path(tmp), [injection_row(context), reply_row(DONE_CLAIM)])
            findings, _payload = self.stop(transcript)
        self.assertEqual([detect.RULE_UNPROVEN], [finding.rule_id for finding in findings])
        self.assertIn("conditional", findings[0].message)


class TestBlockRendering(NotesInTempDir):
    def test_the_entrypoint_exits_2_and_names_the_step_key_and_override_syntax(self) -> None:
        context = router_injection("create playbook")
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            transcript = write_transcript(Path(tmp), [
                injection_row(context),
                reply_row(DONE_CLAIM),
                tool_result_row("clean: 1 playbook(s) -- check_playbook_exit 0"),
            ])
            result = run_entrypoint({
                "hook_event_name": "Stop",
                "session_id": "runbook-gate-block",
                "transcript_path": transcript,
            }, metrics)
            rows = rows_written(metrics)

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn("router_trigger_free", result.stderr)
        self.assertIn("override: 1 <reason>", result.stderr)
        self.assertIn(detect.OVERRIDE_SYNTAX, result.stderr)
        self.assertEqual(9, len(rows))
        blocked = [row for row in rows if row["rule_id"] == detect.RULE_UNPROVEN]
        self.assertEqual(1, len(blocked))
        self.assertEqual("stopped", blocked[0]["action"])
        self.assertEqual({"silent"}, {row["action"] for row in rows if row["rule_id"] != detect.RULE_UNPROVEN})


if __name__ == "__main__":
    unittest.main()
