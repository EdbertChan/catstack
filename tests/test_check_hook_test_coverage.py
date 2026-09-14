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


PLATFORM_DETECTOR = (
    "import sys\n\n"
    "def screen_is_locked(platform=None):\n"
    "    if (platform or sys.platform) != 'darwin':\n"
    "        return None\n"
    "    return False\n"
)
PLATFORM_INJECTING_TEST = (
    "\n\ndef test_no_hit_off_macos():\n"
    "    assert screen_is_locked(platform='linux') is None\n"
)


class TestPlatformBranchRule(unittest.TestCase):
    """A branch taken per operating system only runs on the host running it.

    A suite green on a developer's machine says nothing about the branch CI
    takes, which is how a macOS-only probe shipped and went red on Linux.
    """

    def test_platform_branch_without_an_injecting_test_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = hook(Path(tmp), "probe", PLATFORM_DETECTOR, FIRES_AND_SILENT)
            problems = [p for p in chtc.check_hook(str(hook_dir)) if "platform" in p]
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("injects a platform", problems[0])

    def test_platform_branch_with_an_injecting_test_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = hook(
                Path(tmp), "probe", PLATFORM_DETECTOR,
                FIRES_AND_SILENT + PLATFORM_INJECTING_TEST,
            )
            problems = [p for p in chtc.check_hook(str(hook_dir)) if "platform" in p]
        self.assertEqual(problems, [])

    def test_a_detector_with_no_platform_branch_is_not_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook_dir = hook(Path(tmp), "inline", INLINE_DETECTOR, FIRES_AND_SILENT)
            problems = [p for p in chtc.check_hook(str(hook_dir)) if "platform" in p]
        self.assertEqual(problems, [])


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
