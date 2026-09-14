#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.dirname(HERE)
sys.path.insert(0, HOOK)
sys.path.insert(0, os.path.join(os.path.dirname(HOOK), "llm-judge"))

from judge_test_base import JudgeTestCase  # noqa: E402

import backtest_judge  # noqa: E402

TAG_BODY = "the repair worker is off -- cannot verify: can't log in to the server to look"


def stub(answer: dict) -> list:
    return ["stub", [sys.executable, "-c", f"print({json.dumps(json.dumps(answer))})", "{prompt}"]]


def write_transcript(folder: str, with_tag: bool = True) -> str:
    path = os.path.join(folder, "session.jsonl")
    rows = [
        {"type": "user", "cwd": folder, "message": {"content": "is the worker repairing PRs?"}},
        "not json at all",
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Checking the server."}]}},
    ]
    if with_tag:
        rows.append({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Intro.\n\n{{CAT-UNVERIFIED: " + TAG_BODY + "}}\n\nTail."}]}})
    rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "LATER: the login worked."}]}})
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
    return path


class BacktestJudgeTests(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        super().tearDown()

    def case(self, **extra) -> dict:
        return {"id": "t1", "session": write_transcript(self.tmp.name), "tag": TAG_BODY, **extra}

    def test_hit_answered_case_records_judge_verdict(self):
        self.use_runners(stub({"blocker_false": True, "claim_status": "unknown", "report": "a login worked"}))
        result = backtest_judge.run_case(self.case(), "false", 30, self.tmp.name)
        self.assertEqual(result["outcome"], "answered")
        self.assertIs(result["predicted_blocker_false"], True)
        self.assertEqual(result["report"], "a login worked")
        self.assertEqual(result["unreadable_lines"], 1)

    def test_transcript_copy_stops_at_the_tagged_reply(self):
        dest = os.path.join(self.tmp.name, "cut.jsonl")
        cut = backtest_judge.cut_transcript(write_transcript(self.tmp.name), TAG_BODY, dest)
        self.assertTrue(cut["found"])
        self.assertEqual(cut["cwd"], self.tmp.name)
        with open(dest, encoding="utf-8") as handle:
            copied = handle.read()
        self.assertIn("CAT-UNVERIFIED", copied)
        self.assertNotIn("LATER: the login worked", copied)
        self.assertIn(TAG_BODY, cut["paragraph"])
        self.assertNotIn("Tail.", cut["paragraph"])

    def test_missing_transcript_is_unchecked_not_scored(self):
        result = backtest_judge.run_case({"id": "t1", "session": "/nonexistent/s.jsonl", "tag": TAG_BODY}, "false", 30, self.tmp.name)
        self.assertEqual(result["outcome"], "unchecked")
        self.assertIn("transcript missing", result["why"])

    def test_tag_absent_from_transcript_is_unchecked(self):
        session = write_transcript(self.tmp.name, with_tag=False)
        result = backtest_judge.run_case({"id": "t1", "session": session, "tag": TAG_BODY}, "false", 30, self.tmp.name)
        self.assertEqual(result["outcome"], "unchecked")
        self.assertIn("tag not found", result["why"])

    def test_malformed_tag_is_unchecked(self):
        result = backtest_judge.run_case(self.case(tag="no blocker named"), "false", 30, self.tmp.name)
        self.assertEqual(result["outcome"], "unchecked")
        self.assertIn("not well-formed", result["why"])

    def test_unusable_answer_is_unchecked_never_scored_clean(self):
        self.use_runners(stub({"match": False}))
        result = backtest_judge.run_case(self.case(), "true", 30, self.tmp.name)
        self.assertEqual(result["outcome"], "unchecked")

    def test_score_counts_each_outcome_and_skips_unlabeled(self):
        results = [
            {"label": "false", "outcome": "answered", "predicted_blocker_false": True},
            {"label": "false", "outcome": "answered", "predicted_blocker_false": False},
            {"label": "true", "outcome": "answered", "predicted_blocker_false": True},
            {"label": "true", "outcome": "answered", "predicted_blocker_false": False},
            {"label": "true", "outcome": "unchecked"},
            {"label": "unclear", "outcome": "answered", "predicted_blocker_false": True},
        ]
        self.assertEqual(backtest_judge.score(results), {"tp": 1, "fn": 1, "fp": 1, "tn": 1, "unchecked": 1, "unlabeled": 1})

    def test_malformed_input_file_exits_2(self):
        bad = os.path.join(self.tmp.name, "cases.jsonl")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json\n")
        with redirect_stdout(io.StringIO()):
            code = backtest_judge.main(["--cases", bad, "--labels", bad])
        self.assertEqual(code, 2)
