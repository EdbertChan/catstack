#!/usr/bin/env python3
"""The bad case this gate exists for is real: five `plain-words-*` checkers,
including the jargon ban, shipped with no caller. The false-negative case is
real too -- `example` passed on a bare substring match against three files that
merely used the word in prose.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(REPO_ROOT, "scripts", "check_rules_are_wired.py")


def load_gate(hooks_root: str):
    spec = importlib.util.spec_from_file_location("gate_under_test", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HOOKS_ROOT = hooks_root
    module.REPO_ROOT = os.path.dirname(hooks_root)
    return module


class WiringGate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hooks = os.path.join(self.tmp.name, "engine", "hooks")
        os.makedirs(self.hooks)

    def _phrase(self, hook: str, name: str, **extra) -> str:
        directory = os.path.join(self.hooks, hook, "phrases")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{name}.json")
        payload = {
            "checker": name,
            "meaning": "whatever",
            "reads": "reply",
            "match": ["a"],
            "not_match": ["b"],
            "on_hit": "hit",
        }
        payload.update(extra)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def _caller(self, hook: str, body: str) -> None:
        directory = os.path.join(self.hooks, hook)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "detect.py"), "w", encoding="utf-8") as handle:
            handle.write(body)

    def test_a_checker_with_no_caller_fails(self) -> None:
        self._phrase("diu-stop", "plain-words-tech-jargon")
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 1)

    def test_a_quoted_caller_passes(self) -> None:
        self._phrase("diu-stop", "plain-words-tech-jargon")
        self._caller("diu-stop", 'CATEGORIES = ("plain-words-tech-jargon",)\n')
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 0)

    def test_a_quoted_caller_in_an_engine_skill_script_passes(self) -> None:
        self._phrase("llm-judge", "pr-description-history-claims")
        scripts = os.path.join(os.path.dirname(self.hooks), "skills", "make-pr", "scripts")
        os.makedirs(scripts)
        with open(os.path.join(scripts, "description_check.py"), "w", encoding="utf-8") as handle:
            handle.write('CHECKER = "pr-description-history-claims"\n')
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 0)

    def test_an_unquoted_prose_mention_is_not_a_caller(self) -> None:
        self._phrase("llm-judge", "example")
        self._caller("llm-judge", '"""For example, this is prose."""\n')
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 1)

    def test_an_explicit_unwired_reason_passes(self) -> None:
        self._phrase("llm-judge", "example", unwired_reason="sample only, never submitted")
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 0)

    def test_an_empty_unwired_reason_does_not_count(self) -> None:
        self._phrase("llm-judge", "example", unwired_reason="   ")
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 1)

    def test_a_phrase_file_with_no_checker_name_fails(self) -> None:
        directory = os.path.join(self.hooks, "diu-stop", "phrases")
        os.makedirs(directory)
        with open(os.path.join(directory, "broken.json"), "w", encoding="utf-8") as handle:
            json.dump({"meaning": "no checker key"}, handle)
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 1)

    def test_a_caller_inside_tests_does_not_count(self) -> None:
        self._phrase("diu-stop", "plain-words-tech-jargon")
        tests_dir = os.path.join(self.hooks, "diu-stop", "tests")
        os.makedirs(tests_dir)
        with open(os.path.join(tests_dir, "test_x.py"), "w", encoding="utf-8") as handle:
            handle.write('load("plain-words-tech-jargon")\n')
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 1)

    def test_the_real_repo_passes(self) -> None:
        result = subprocess.run([sys.executable, GATE], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RuntimeDiscovery(WiringGate):
    def test_a_hook_that_lists_its_phrases_dir_wires_all_of_them(self) -> None:
        self._phrase("diu-stop", "plain-words-tech-jargon")
        self._phrase("diu-stop", "plain-words-code-names")
        self._caller("diu-stop", 'import os\nnames = os.listdir("phrases")\n')
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 0)

    def test_mentioning_phrases_without_listing_it_is_not_wiring(self) -> None:
        self._phrase("diu-stop", "plain-words-tech-jargon")
        self._caller("diu-stop", '"""The phrases directory holds the word lists."""\n')
        gate = load_gate(self.hooks)
        self.assertEqual(gate.main(), 1)


if __name__ == "__main__":
    unittest.main()
