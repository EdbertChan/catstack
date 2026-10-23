#!/usr/bin/env python3
"""Tests for the hedge-runs-prove-it Stop hook.

Run: python3 -m unittest discover -s engine/hooks/hedge-runs-prove-it/tests -v

Fixtures in tests/fixtures/ are sanitized replies from real sessions
("presumably moving it to catstack" with no check run; "it's a zombie, not
slow" asserted off a capacity projection while ten workers were at 96% CPU)
plus the shapes the rule names. Each fixture carries `verified`: whether the
turn ran a verification tool. The diagnosis fixtures set it true on purpose
-- an unhedged root-cause claim is not cleared by having run a tool, only by
instrument-level proof in the same message.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def turn_lines(verified):
    lines = [{"type": "user", "message": {"role": "user", "content": "what is this file?"}}]
    if verified:
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status --porcelain"}}]}})
    return lines


ERROR_CAPABILITY_LIST = (
    'Error: Execution model "gpt-5.6-luna" is not supported for execution agent '
    '"codex". Known models: [gpt-5.5, gpt-5.5-pro, gpt-5.4, gpt-5.4-pro].'
)


def capability_lines(with_non_error_source=False):
    lines = turn_lines(False) + [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "models-error", "name": "Task", "input": {}}
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "models-error", "content": ERROR_CAPABILITY_LIST}
        ]}},
    ]
    if with_non_error_source:
        lines.extend([
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "models-answer", "name": "Task", "input": {}}
            ]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "models-answer", "content": (
                    "Supported execution models: gpt-5.5, gpt-5.5-pro, gpt-5.4, gpt-5.4-pro."
                )}
            ]}},
        ])
    return lines


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def run_hook(payload):
    payload = dict(payload)
    payload.setdefault("hook_event_name", "Stop")
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


class TestBlocksUnverifiedHedges(unittest.TestCase):
    def test_blocks_each_hedge_fixture(self):
        for case in load("hedges_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNotNone(detect.decide_from_lines(case["reply"], turn_lines(case["verified"])))

    def test_hook_blocks_presumably_reply_with_exit_2(self):
        case = load("hedges_fires.json")[0]
        path = transcript_file(turn_lines(False))
        try:
            code, err = run_hook({"last_assistant_message": case["reply"], "transcript_path": path})
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("prove-it", err)
        self.assertIn("presumably", err)

    def test_blocks_unverified_without_reason_even_with_no_transcript(self):
        self.assertIsNotNone(detect.decide({"last_assistant_message": load("hedges_fires.json")[2]["reply"]}))


class TestAllowsVerifiedOrReasonedHedges(unittest.TestCase):
    def test_allows_each_silent_fixture(self):
        for case in load("hedges_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.decide_from_lines(case["reply"], turn_lines(case["verified"])))

    def test_allows_hedge_when_read_tool_ran_this_turn(self):
        lines = turn_lines(False) + [{"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/repo/x.py"}}]}}]
        self.assertIsNone(detect.decide_from_lines(load("hedges_fires.json")[1]["reply"], lines))

    def test_allows_when_verification_was_in_a_previous_turn_only_if_rerun(self):
        lines = turn_lines(True) + [{"type": "user", "message": {"role": "user", "content": "and now?"}}]
        self.assertIsNotNone(detect.decide_from_lines(load("hedges_fires.json")[1]["reply"], lines))

    def test_allows_when_stop_hook_active(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("hedges_fires.json")[0]["reply"], "stop_hook_active": True,
        }))

    def test_fails_open_on_unreadable_transcript(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("hedges_fires.json")[0]["reply"],
            "transcript_path": "/nonexistent/x.jsonl",
        }))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                with self.assertRaises(SystemExit) as caught:
                    claude_stop_check.main()
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("catstack-hook-error hedge-runs-prove-it: JSONDecodeError", err.getvalue())


class TestQuotedHedgeSpans(unittest.TestCase):
    """A hedge cited inside a quote run is exempt wherever it sits in the run,
    not only when it is the run's first token."""

    def test_blocks_unquoted_mid_sentence_hedge(self):
        self.assertEqual(
            detect.code_hedges(
                "I might send you the matcher change near a PR; it should work "
                "for the heredoc case in claude.hook.json too."
            ),
            ["should work"],
        )

    def test_no_hit_hedge_quoted_past_the_first_token(self):
        for quote in ('"that should work"', "`that should work`", "'that should work'"):
            with self.subTest(quote=quote):
                self.assertEqual(
                    detect.code_hedges(f"I might send you {quote} near a PR."), []
                )

    def test_no_hit_when_describing_the_hooks_own_triggers(self):
        self.assertEqual(
            detect.code_hedges(
                'The gate fires on `I think`, "that should work", or a bare '
                "`UNVERIFIED:` next to a code noun in the same PR reply."
            ),
            [],
        )

    def test_blocks_hedge_when_apostrophes_are_the_only_single_quotes(self):
        self.assertEqual(
            detect.code_hedges("It's probably still on the branch and I don't think the build ran."),
            ["probably"],
        )

    def test_no_hit_apostrophe_does_not_open_a_span_over_a_possessive(self):
        self.assertEqual(
            detect.code_hedges("The workers' pool probably still holds the stale commit."),
            ["probably"],
        )

    def test_no_hit_after_an_unbalanced_opening_quote(self):
        self.assertEqual(detect.code_hedges('He said "should work for the test suite'), [])

    def test_quoted_spans_ignores_apostrophes(self):
        self.assertEqual(detect.quoted_spans("it's, don't, the workers' pool"), [])


class TestBlocksUnhedgedDiagnosis(unittest.TestCase):
    def test_blocks_each_diagnosis_fixture(self):
        for case in load("diagnosis_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNotNone(
                    detect.decide_from_lines(case["reply"], turn_lines(case["verified"]))
                )

    def test_blocks_zombie_claim_even_though_the_turn_ran_a_tool(self):
        case = load("diagnosis_fires.json")[0]
        self.assertTrue(detect.diagnosis_claims(case["reply"]))
        self.assertEqual(detect.code_hedges(case["reply"]), [])
        self.assertIsNotNone(detect.decide_from_lines(case["reply"], turn_lines(True)))

    def test_hook_blocks_zombie_claim_with_exit_2(self):
        case = load("diagnosis_fires.json")[0]
        path = transcript_file(turn_lines(True))
        try:
            code, err = run_hook({"last_assistant_message": case["reply"], "transcript_path": path})
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("instrument-level proof", err)
        self.assertIn("zombie", err)

    def test_blocks_diagnosis_with_no_transcript_at_all(self):
        case = load("diagnosis_fires.json")[2]
        self.assertIsNotNone(detect.decide({"last_assistant_message": case["reply"]}))


class TestAllowsProvenOrQuotedDiagnosis(unittest.TestCase):
    def test_allows_each_silent_diagnosis_fixture(self):
        for case in load("diagnosis_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(
                    detect.decide_from_lines(case["reply"], turn_lines(case["verified"]))
                )

    def test_no_hit_when_the_process_table_ships_in_the_same_message(self):
        self.assertEqual(detect.diagnosis_claims(load("diagnosis_silent.json")[0]["reply"]), [])

    def test_allows_diagnosis_when_stop_hook_active(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("diagnosis_fires.json")[0]["reply"],
            "stop_hook_active": True,
        }))

    def test_diagnosis_gate_ignores_an_unreadable_transcript(self):
        self.assertIsNotNone(detect.decide({
            "last_assistant_message": load("diagnosis_fires.json")[0]["reply"],
            "transcript_path": "/nonexistent/x.jsonl",
        }))


class TestBlocksCapabilitiesCopiedOnlyFromErrors(unittest.TestCase):
    def test_hook_blocks_two_values_repeated_beside_only_accepts(self):
        path = transcript_file(capability_lines())
        try:
            code, err = run_hook({
                "last_assistant_message": "codex only accepts [gpt-5.5, gpt-5.5-pro].",
                "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("error-shaped tool output", err)

    def test_allows_values_also_listed_by_non_error_tool_result(self):
        self.assertIsNone(detect.decide_from_lines(
            "codex only accepts [gpt-5.5, gpt-5.5-pro].",
            capability_lines(with_non_error_source=True),
        ))

    def test_allows_attributed_fallback_list(self):
        self.assertIsNone(detect.decide_from_lines(
            "The built-in fallback list says codex only accepts [gpt-5.5, gpt-5.5-pro].",
            capability_lines(),
        ))

    def test_allows_a_single_repeated_value(self):
        self.assertIsNone(detect.decide_from_lines(
            "codex only accepts gpt-5.5.",
            capability_lines(),
        ))


PROSE_ERROR_OUTPUT = (
    "Error: request failed after 3 tries, so I will tell you what I can, say the claim, "
    "get the files, stop, wait minutes, bypass the hook, turn it off. The p95 is 52.1."
)


def error_lines(error_text, previous_turn=False):
    result = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "err-1", "name": "Bash", "input": {"command": "curl x"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "err-1", "content": error_text, "is_error": True}]}},
    ]
    human = {"type": "user", "message": {"role": "user", "content": "next question"}}
    if previous_turn:
        return result + [human]
    return [human] + result


class TestCapabilityIgnoresProseInErrorOutput(unittest.TestCase):
    """Reported false positives: ordinary words between commas in an error log."""

    def test_silent_on_dictionary_words_harvested_from_error_prose(self):
        reply = (
            "The log only says what it did, so I can tell, say, claim, files, get, stop, "
            "minutes, p95, bypass, hook and turn apart."
        )
        self.assertIsNone(detect.decide_from_lines(reply, error_lines(PROSE_ERROR_OUTPUT)))

    def test_silent_on_comma_run_with_no_list_label(self):
        text = "Error: failed for gpt-5.5, gpt-5.5-pro, gpt-5.4 in the last run"
        self.assertIsNone(detect.decide_from_lines(
            "codex only accepts [gpt-5.5, gpt-5.5-pro].", error_lines(text)))

    def test_silent_when_the_error_is_from_an_earlier_turn(self):
        self.assertIsNone(detect.decide_from_lines(
            "codex only accepts [gpt-5.5, gpt-5.5-pro].",
            error_lines(ERROR_CAPABILITY_LIST, previous_turn=True),
        ))

    def test_silent_on_plain_word_values_in_a_labelled_list(self):
        text = "Error: invalid option. Valid values: fast, slow, medium."
        self.assertIsNone(detect.decide_from_lines(
            "The tool only accepts fast, slow and medium.", error_lines(text)))

    def test_still_blocks_an_unbracketed_labelled_list_from_this_turns_error(self):
        text = "Error: bad model. Supported models: gpt-5.5, gpt-5.5-pro, gpt-5.4."
        feedback = detect.decide_from_lines(
            "codex only supports gpt-5.5 and gpt-5.5-pro here", error_lines(text))
        self.assertIn("error-shaped tool output", feedback)

    def test_still_blocks_a_bracketed_list_from_this_turns_error(self):
        feedback = detect.decide_from_lines(
            "codex only accepts [gpt-5.5, gpt-5.5-pro].", error_lines(ERROR_CAPABILITY_LIST))
        self.assertIn("gpt-5.5", feedback)


SKILL_READ_WITH_ERROR_WORD = (
    "# ci-job-timing\n\nStep times live in the GitLab job logs. The parser can show ci_step rows "
    "per job. If a fetch fails with an error, check the logs, parser, plus the job id, then retry."
)


def read_result_lines(text):
    return [
        {"type": "user", "message": {"role": "user", "content": "where do the step times come from?"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "read-1", "name": "Read", "input": {"file_path": "SKILL.md"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "read-1", "content": SKILL_READ_WITH_ERROR_WORD}]}},
    ]


class TestCapabilityIgnoresOrdinaryProseWithOnly(unittest.TestCase):
    """Reported false positives: the word "only" in ordinary prose beside words from a Read."""

    def test_silent_on_only_live_in_logs_after_a_skill_read_that_mentions_error(self):
        reply = "The step times only live in GitLab job logs; the parser shows ci_step rows."
        self.assertIsNone(detect.decide_from_lines(reply, read_result_lines(SKILL_READ_WITH_ERROR_WORD)))
        self.assertEqual(detect.detect({
            "last_assistant_message": reply,
            "transcript_path": transcript_file(read_result_lines(SKILL_READ_WITH_ERROR_WORD)),
        }), [])

    def test_silent_on_read_only_question_after_an_error_with_label_we(self):
        text = "Error: could not render the diagram: label, we, arrow are not valid node names."
        reply = "Want me to label that arrow read-only?"
        self.assertIsNone(detect.decide_from_lines(reply, error_lines(text)))

    def test_still_blocks_known_models_after_a_real_error(self):
        feedback = detect.decide_from_lines(
            "codex only accepts [gpt-5.5, gpt-5.5-pro].", capability_lines())
        self.assertIn("gpt-5.5, gpt-5.5-pro", feedback)


if __name__ == "__main__":
    unittest.main()
