#!/usr/bin/env python3
"""Positive + negative tests for check_hook_test_coverage's unchecked-input rule.

A detector that opens a file has a third outcome besides hit and clean:
input it could not read. This gate requires a test that pins that outcome,
whichever way the hook resolves it, so an unchecked file cannot pass as
clean by default. Fixtures here are synthetic hook directories.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_hook_test_coverage as chtc  # noqa: E402

FIRES_AND_SILENT = (
    "def test_hit_detects_the_bad_case():\n    pass\n\n"
    "def test_no_hit_stays_silent_on_a_clean_case():\n    pass\n"
)
UNREADABLE_TEST = "\n\ndef test_fails_open_on_unreadable_input():\n    pass\n"
INLINE_DETECTOR = "import re\nPATTERN = re.compile('x')\n\ndef decide(payload):\n    return None\n"
FILE_READING_DETECTOR = (
    "import os\n\n"
    "def decide(payload):\n"
    "    path = payload['tool_input']['path']\n"
    "    if os.path.getsize(path) > 1024:\n"
    "        return None\n"
    "    with open(path) as handle:\n"
    "        return handle.read()[:1]\n"
)


def hook(root: Path, name: str, detector: str, tests: str) -> Path:
    hook_dir = root / name
    (hook_dir / "tests").mkdir(parents=True)
    (hook_dir / "detect.py").write_text(detector, encoding="utf-8")
    (hook_dir / "tests" / "test_hooks.py").write_text(tests, encoding="utf-8")
    return hook_dir


class TestUncheckedInputRule(unittest.TestCase):
    def test_file_reading_detector_without_an_unreadable_test_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = hook(Path(tmp), "reader", FILE_READING_DETECTOR, FIRES_AND_SILENT)
            problems = chtc.check_hook(str(hook_dir))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("could not read", problems[0])

    def test_file_reading_detector_with_an_unreadable_test_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = hook(
                Path(tmp), "reader", FILE_READING_DETECTOR, FIRES_AND_SILENT + UNREADABLE_TEST
            )
            self.assertEqual(chtc.check_hook(str(hook_dir)), [])

    def test_inline_only_detector_is_not_asked_for_an_unreadable_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = hook(Path(tmp), "inline", INLINE_DETECTOR, FIRES_AND_SILENT)
            self.assertEqual(chtc.check_hook(str(hook_dir)), [])

    def test_reads_external_input_detects_a_size_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "detect.py"
            path.write_text(FILE_READING_DETECTOR, encoding="utf-8")
            self.assertTrue(chtc.reads_external_input(str(path)))

    def test_reads_external_input_is_false_for_an_inline_detector(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "detect.py"
            path.write_text(INLINE_DETECTOR, encoding="utf-8")
            self.assertFalse(chtc.reads_external_input(str(path)))

    def test_missing_detector_file_fails_open_rather_than_erroring(self):
        self.assertFalse(chtc.reads_external_input("/nonexistent/detect.py"))


class TestExistingRulesStillHold(unittest.TestCase):
    def test_no_positive_test_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = hook(
                Path(tmp), "silent-only", INLINE_DETECTOR,
                "def test_no_hit_stays_silent():\n    pass\n",
            )
            problems = chtc.check_hook(str(hook_dir))
        self.assertTrue(any("no positive test" in p for p in problems), problems)

    def test_the_real_repo_passes_this_gate(self):
        problems = []
        for hook_dir in chtc.hooks_with_detector():
            problems.extend(chtc.check_hook(hook_dir))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()


JUDGE_CALLER = "def ask(text):\n    import judge\n    return judge.ask(text)\n"
USES_BASE = "from testing import JudgeTestCase\n\n\nclass TestCaller(JudgeTestCase):\n    pass\n"
NAMES_BASE_IN_COMMENT = "import unittest\n\n\nclass TestCaller(unittest.TestCase):\n    pass  # JudgeTestCase\n"


def judge_hook(root: Path, source: str, tests: str | None) -> Path:
    hook_dir = root / "caller"
    hook_dir.mkdir()
    (hook_dir / "caller.py").write_text(source, encoding="utf-8")
    if tests is not None:
        (hook_dir / "tests").mkdir()
        (hook_dir / "tests" / "test_caller.py").write_text(tests, encoding="utf-8")
    return hook_dir


class TestJudgeIsolationRule(unittest.TestCase):
    def test_hit_judge_caller_whose_tests_skip_the_base_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = chtc.judge_isolation_problems(str(judge_hook(Path(tmp), JUDGE_CALLER, FIRES_AND_SILENT)))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("JudgeTestCase", problems[0])

    def test_hit_base_named_only_in_a_comment_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = chtc.judge_isolation_problems(str(judge_hook(Path(tmp), JUDGE_CALLER, NAMES_BASE_IN_COMMENT)))
        self.assertEqual(len(problems), 1, problems)

    def test_no_hit_judge_caller_whose_tests_subclass_the_base_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(chtc.judge_isolation_problems(str(judge_hook(Path(tmp), JUDGE_CALLER, USES_BASE))), [])

    def test_no_hit_hook_that_never_imports_judge_is_not_asked_for_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(chtc.judge_isolation_problems(str(judge_hook(Path(tmp), INLINE_DETECTOR, FIRES_AND_SILENT))), [])

    def test_unreadable_source_is_reported_as_unchecked_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = chtc.judge_isolation_problems(str(judge_hook(Path(tmp), "def broken(:\n", USES_BASE)))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("could not read", problems[0])

    def test_hit_hook_without_detect_py_is_still_checked_by_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = judge_hook(Path(tmp), JUDGE_CALLER, FIRES_AND_SILENT)
            with patch.object(sys, "argv", ["check_hook_test_coverage.py", str(hook_dir)]):
                self.assertEqual(chtc.main(), 1)
