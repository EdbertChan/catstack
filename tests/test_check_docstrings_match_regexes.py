#!/usr/bin/env python3
"""Every scripts/check_*.py keeps the promises its own docstring makes.

A gate declares PROMISED_CATCH and PROMISED_ALLOW next to its patterns. Each
entry pairs a phrase quoted from the gate's module docstring with an exemplar
input, and exemplar_flagged(exemplar) runs the gate's real decision on it.
Every catch must be flagged, every allow must pass, every phrase must appear
in the docstring, and an exemplar the gate cannot judge (it raises, or answers
with something other than a bool) is reported as unchecked, never as clean.
A gate that declares nothing fails, so a new gate cannot land without one.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

GATES = sorted(SCRIPTS.glob("check_*.py"))
DECLARATIONS = (("PROMISED_CATCH", True), ("PROMISED_ALLOW", False))


def load_gate(path: Path):
    spec = importlib.util.spec_from_file_location(f"docstring_promises_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def broken_promises(module) -> list[str]:
    doc = _squash(module.__doc__ or "")
    judge = getattr(module, "exemplar_flagged", None)
    problems: list[str] = []
    if not doc:
        problems.append("has no module docstring to hold its patterns to")
    if not callable(judge):
        problems.append("declares no exemplar_flagged(exemplar) -> bool")
    for name, should_flag in DECLARATIONS:
        promises = getattr(module, name, None)
        if not promises:
            problems.append(f"declares no {name}")
            continue
        for phrase, exemplar in promises:
            if _squash(phrase) not in doc:
                problems.append(f"{name} phrase {phrase!r} is not in the module docstring")
            if not callable(judge):
                continue
            try:
                verdict = judge(exemplar)
            except Exception as exc:
                problems.append(f"{name} {exemplar!r} unchecked: exemplar_flagged raised {exc!r}")
                continue
            if not isinstance(verdict, bool):
                problems.append(f"{name} {exemplar!r} unchecked: exemplar_flagged answered {verdict!r}, not a bool")
            elif verdict != should_flag:
                promised = "catch" if should_flag else "allow"
                actual = "flags" if verdict else "allows"
                problems.append(f"{name} {exemplar!r}: docstring promises to {promised} ({phrase!r}) but the gate {actual} it")
    return problems


class TestEveryGateKeepsItsDocstringPromises(unittest.TestCase):
    def test_walk_finds_the_gates(self):
        self.assertIn(SCRIPTS / "check_no_dated_provenance.py", GATES)
        self.assertIn(SCRIPTS / "check_history_claims.py", GATES)
        self.assertIn(SCRIPTS / "check_codify_has_code.py", GATES)

    def test_every_gate_keeps_its_docstring_promises(self):
        for path in GATES:
            with self.subTest(gate=path.name):
                problems = broken_promises(load_gate(path))
                self.assertEqual(problems, [], f"{path.name}:\n  " + "\n  ".join(problems))


SOUND_GATE = '''
    """Fail on the word banana."""

    PROMISED_CATCH = (("the word banana", "a banana split"),)
    PROMISED_ALLOW = (("the word banana", "an apple pie"),)


    def exemplar_flagged(exemplar):
        return "banana" in exemplar
'''


class TestMetaGateVerdicts(unittest.TestCase):
    def _problems(self, source: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "check_demo.py"
            path.write_text(textwrap.dedent(source), encoding="utf-8")
            return broken_promises(load_gate(path))

    def test_kept_promises_pass_clean(self):
        self.assertEqual(self._problems(SOUND_GATE), [])

    def test_gate_without_a_declaration_fails(self):
        problems = self._problems('"""Fail on the word banana."""\n')
        self.assertIn("declares no exemplar_flagged(exemplar) -> bool", problems)
        self.assertIn("declares no PROMISED_CATCH", problems)
        self.assertIn("declares no PROMISED_ALLOW", problems)

    def test_gate_without_a_docstring_fails(self):
        problems = self._problems(SOUND_GATE.replace('"""Fail on the word banana."""', ""))
        self.assertIn("has no module docstring to hold its patterns to", problems)

    def test_phrase_missing_from_the_docstring_fails(self):
        problems = self._problems(SOUND_GATE.replace("Fail on the word banana.", "Fail on fruit."))
        self.assertTrue(any("is not in the module docstring" in p for p in problems), problems)

    def test_promised_catch_the_gate_allows_fails(self):
        problems = self._problems(SOUND_GATE.replace('"banana" in exemplar', "False"))
        self.assertTrue(any("promises to catch" in p and "the gate allows it" in p for p in problems), problems)

    def test_promised_allow_the_gate_flags_fails(self):
        problems = self._problems(SOUND_GATE.replace('"banana" in exemplar', "True"))
        self.assertTrue(any("promises to allow" in p and "the gate flags it" in p for p in problems), problems)

    def test_exemplar_the_gate_cannot_judge_is_unchecked_not_clean(self):
        problems = self._problems(SOUND_GATE.replace('return "banana" in exemplar', "raise OSError(exemplar)"))
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(all("unchecked: exemplar_flagged raised" in p for p in problems), problems)

    def test_non_bool_verdict_is_unchecked_not_clean(self):
        problems = self._problems(SOUND_GATE.replace('return "banana" in exemplar', "return None"))
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(all("not a bool" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
