#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_detector_backtested as gate  # noqa: E402
from git_test_repo import init_repo  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "detector_backtested"
SCRIPT = REPO / "scripts" / "check_detector_backtested.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

VALID_BLOCK = (
    "## Backtest\n\n"
    "- Command: python3 scripts/backtest_detector.py --detector engine/hooks/x/detect.py:hit --compare origin/main\n"
    "- Messages scanned: 1843\n- Hits before: 12\n- Hits after: 15\n"
    "- Newly caught: 4\n- Newly missed: 1\n- False positives accepted: 1\n"
)


def load(outcome: str) -> list[dict]:
    return json.loads((FIXTURES / f"{outcome}.json").read_text())


class TestPatternDetection(unittest.TestCase):
    def test_regex_widening_is_detected(self):
        before = 'import re\nRX = re.compile(r"\\bshould\\b")\n'
        after = 'import re\nRX = re.compile(r"\\b(?:should|might)\\b")\n'
        self.assertEqual(gate.changed_patterns(before, after), ["RX"])

    def test_threshold_change_is_detected(self):
        self.assertEqual(gate.changed_patterns("WINDOW = 6\n", "WINDOW = 8\n"), ["WINDOW"])

    def test_pattern_list_item_is_detected(self):
        before = "MARKERS = ('<task-notification', '<system')\n"
        after = "MARKERS = ('<task-notification', '<system', '<command-')\n"
        self.assertEqual(gate.changed_patterns(before, after), ["MARKERS"])

    def test_string_fragment_named_by_a_regex_is_detected(self):
        before = 'import re\n_VERB = "(?:do|use)"\nRX = re.compile(rf"\\b{_VERB}\\b")\n'
        after = 'import re\n_VERB = "(?:do|use|run)"\nRX = re.compile(rf"\\b{_VERB}\\b")\n'
        self.assertEqual(gate.changed_patterns(before, after), ["_VERB"])

    def test_inline_regex_inside_a_function_is_detected(self):
        before = "import re\n\ndef hit(t):\n    return re.search(r'\\bdone\\b', t)\n"
        after = "import re\n\ndef hit(t):\n    return re.search(r'\\b(?:done|shipped)\\b', t)\n"
        self.assertEqual(gate.changed_patterns(before, after), ["re.search() pattern at line 4"])

    def test_class_level_threshold_is_detected(self):
        before = "class Gate:\n    LIMIT = 3\n"
        after = "class Gate:\n    LIMIT = 5\n"
        self.assertEqual(gate.changed_patterns(before, after), ["Gate.LIMIT"])

    def test_new_detector_file_counts_as_a_pattern_change(self):
        self.assertEqual(gate.changed_patterns(None, "import re\nRX = re.compile('x')\n"), ["RX"])

    def test_message_string_change_is_not_a_pattern(self):
        self.assertEqual(gate.changed_patterns('MESSAGE = "a"\n', 'MESSAGE = "b"\n'), [])

    def test_moving_an_unchanged_pattern_is_not_a_change(self):
        before = "import re\nA = re.compile('a')\nB = 3\n"
        after = "import re\nB = 3\n\n\nA = re.compile('a')\n"
        self.assertEqual(gate.changed_patterns(before, after), [])

    def test_new_helper_function_is_not_a_pattern_change(self):
        before = "import re\nRX = re.compile('a')\n"
        after = before + "\n\ndef helper(rows):\n    return [r for r in rows if r]\n"
        self.assertEqual(gate.changed_patterns(before, after), [])

    def test_runtime_values_are_not_patterns(self):
        before = "import os\nHOME = os.path.expanduser('~')\nENABLED = True\n"
        after = "import os\nHOME = os.path.expanduser('~/x')\nENABLED = False\n"
        self.assertEqual(gate.changed_patterns(before, after), [])

    def test_gate_exemplars_are_not_patterns(self):
        self.assertEqual(gate.changed_patterns("GATE_EXEMPLARS = {'catch': []}\n", "GATE_EXEMPLARS = {'catch': ['x']}\n"), [])


class TestScope(unittest.TestCase):
    def test_detector_files_are_in_scope(self):
        for path in ("engine/hooks/diu-stop/detect.py", "engine/hooks/diu-stop/claude_stop_check.py", "scripts/check_history_claims.py"):
            self.assertTrue(gate.in_scope(path), path)

    def test_tests_install_and_other_scripts_are_out_of_scope(self):
        for path in (
            "engine/hooks/diu-stop/tests/test_hooks.py",
            "engine/hooks/diu-stop/install_claude_hook.py",
            "engine/hooks/diu-stop/README.md",
            "scripts/backtest_detector.py",
            "scripts/sub/check_x.py",
            "tests/test_check_detector_backtested.py",
        ):
            self.assertFalse(gate.in_scope(path), path)


class TestBlockParsing(unittest.TestCase):
    def test_valid_block_parses(self):
        block = gate.parse_block(VALID_BLOCK)
        self.assertEqual(block.problems, [])
        self.assertEqual(block.values["messages scanned"], 1843)

    def test_missing_section_is_reported(self):
        block = gate.parse_block("## Summary\n\nWiden it.\n")
        self.assertFalse(block.present)

    def test_prose_with_digits_is_not_a_block(self):
        block = gate.parse_block("## Backtest\n\nRan the backtest on 1200 messages, 3 new hits, fine.\n")
        self.assertTrue(block.present)
        self.assertIn("missing field `Messages scanned:`", block.problems)

    def test_digits_outside_the_section_do_not_count(self):
        body = "## Summary\n\nMessages scanned: 10\n\n## Backtest\n\nsee above\n"
        self.assertIn("missing field `Messages scanned:`", gate.parse_block(body).problems)

    def test_non_numeric_value_is_rejected(self):
        body = VALID_BLOCK.replace("Hits after: 15", "Hits after: about 15")
        self.assertIn("`Hits after:` is not a whole number: 'about 15'", gate.parse_block(body).problems)

    def test_non_ascii_digit_is_rejected_not_crashed_on(self):
        body = VALID_BLOCK.replace("Hits after: 15", "Hits after: ²")
        self.assertIn("`Hits after:` is not a whole number: '²'", gate.parse_block(body).problems)

    def test_numbers_that_disagree_are_rejected(self):
        body = VALID_BLOCK.replace("Newly caught: 4", "Newly caught: 9")
        problems = gate.parse_block(body).problems
        self.assertTrue(any(p.startswith("numbers disagree") for p in problems), problems)

    def test_zero_messages_scanned_is_rejected(self):
        body = (VALID_BLOCK.replace("Messages scanned: 1843", "Messages scanned: 0")
                .replace("Hits before: 12", "Hits before: 0").replace("Hits after: 15", "Hits after: 0")
                .replace("Newly caught: 4", "Newly caught: 0").replace("Newly missed: 1", "Newly missed: 0")
                .replace("False positives accepted: 1", "False positives accepted: 0"))
        self.assertTrue(any("scanned is 0" in p for p in gate.parse_block(body).problems))

    def test_command_must_run_the_backtest_runner(self):
        body = VALID_BLOCK.replace("scripts/backtest_detector.py", "scripts/my_quick_check.py")
        self.assertTrue(any(p.startswith("`Command:` does not run") for p in gate.parse_block(body).problems))

    def test_duplicate_field_is_rejected(self):
        body = VALID_BLOCK + "- Hits after: 16\n"
        self.assertIn("field `Hits after:` appears 2 times", gate.parse_block(body).problems)

    def test_block_ends_at_the_next_heading(self):
        body = "## Backtest\n\n- Messages scanned: 5\n\n## Test Plan\n\n- Hits before: 1\n"
        self.assertIn("missing field `Hits before:`", gate.parse_block(body).problems)


class TestThreeOutcomes(unittest.TestCase):
    def test_no_body_needed_when_no_pattern_changed(self):
        self.assertEqual(gate.decide({}, [], None, None).outcome, gate.PASS)

    def test_unreadable_body_is_unchecked_not_pass(self):
        verdict = gate.decide({}, [], None, "FileNotFoundError: x")
        self.assertEqual(verdict.outcome, gate.UNCHECKED)

    def test_pattern_change_without_supplied_body_is_unchecked(self):
        self.assertEqual(gate.decide({"a.py": ["RX"]}, [], None, None).outcome, gate.UNCHECKED)

    def test_unparseable_detector_file_is_unchecked_not_pass(self):
        verdict = gate.evaluate_sources("engine/hooks/x/detect.py", "RX = 1\n", "RX = (\n", "## Summary\n")
        self.assertEqual(verdict.outcome, gate.UNCHECKED)

    def test_unparseable_detector_file_passes_with_a_valid_block(self):
        verdict = gate.evaluate_sources("engine/hooks/x/detect.py", "RX = 1\n", "RX = (\n", VALID_BLOCK)
        self.assertEqual(verdict.outcome, gate.PASS)

    def test_exit_codes_are_distinct(self):
        self.assertEqual(len(set(gate.EXIT_CODES.values())), 3)
        self.assertEqual(gate.EXIT_CODES[gate.PASS], 0)


class TestGateExemplars(unittest.TestCase):
    def test_catch_exemplars_are_caught(self):
        for i, ex in enumerate(gate.GATE_EXEMPLARS["catch"]):
            self.assertTrue(gate.gate_check(ex), f"catch[{i}]")

    def test_allow_exemplars_are_allowed(self):
        for i, ex in enumerate(gate.GATE_EXEMPLARS["allow"]):
            self.assertFalse(gate.gate_check(ex), f"allow[{i}]")

    def test_gate_check_refuses_an_undecidable_exemplar(self):
        with self.assertRaises(ValueError):
            gate.gate_check(("engine/hooks/x/detect.py", "RX = 1\n", "RX = (\n", ""))


class TestFixturesThroughRealGit(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=ENV, check=True)

    def _run_case(self, case: dict) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            init_repo(repo, "-b", "main")
            (repo / "scripts").mkdir()
            script = repo / "scripts" / "check_detector_backtested.py"
            script.write_text(SCRIPT.read_text())
            target = repo / case["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if case["before"] is not None:
                target.write_text(case["before"])
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-qm", "base")
            self._git(repo, "checkout", "-qb", "feature")
            target.write_text(case["after"])
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-qm", "change")
            body_path = Path(tmp) / "body.md"
            if case["body"] is not None:
                body_path.write_text(case["body"])
            args = [sys.executable, str(script), "--base", case.get("base", "main"), "--body-file", str(body_path)]
            return subprocess.run(args, cwd=repo, capture_output=True, text=True, env=ENV)

    def _check_outcome(self, outcome: str) -> None:
        cases = load(outcome)
        self.assertEqual(len(cases), 2, f"{outcome}.json should hold a pair")
        for case in cases:
            with self.subTest(case["label"]):
                res = self._run_case(case)
                out = res.stdout + res.stderr
                self.assertEqual(case["expected"], outcome.upper())
                self.assertEqual(res.returncode, gate.EXIT_CODES[case["expected"]], out)
                self.assertTrue(out.startswith(f"{case['expected']} detector-backtested:"), out)

    def test_pass_fixtures(self):
        self._check_outcome("pass")

    def test_fail_fixtures(self):
        self._check_outcome("fail")

    def test_unchecked_fixtures(self):
        self._check_outcome("unchecked")

    def test_unparseable_detector_file_is_unchecked_through_git(self):
        case = {"path": "engine/hooks/x/detect.py", "before": "RX = 1\n", "after": "RX = (\n", "body": "## Summary\n"}
        res = self._run_case(case)
        self.assertEqual(res.returncode, gate.EXIT_CODES[gate.UNCHECKED], res.stdout + res.stderr)
        self.assertIn("SyntaxError line 1", res.stderr)

    def test_file_outside_scope_passes_through_git(self):
        case = {"path": "scripts/backtest_detector.py", "before": "WINDOW = 6\n", "after": "WINDOW = 8\n", "body": "## Summary\n"}
        res = self._run_case(case)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
