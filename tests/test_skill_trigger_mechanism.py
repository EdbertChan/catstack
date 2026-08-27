#!/usr/bin/env python3
"""Positive + negative tests for check_skill_trigger_mechanism."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_skill_trigger_mechanism as ctm  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skill(
    root: Path,
    bucket: str,
    name: str,
    *,
    disable_model_invocation: bool,
    description: str = "Apply when the user asks about widgets.",
    fires_text: str | None = None,
    silent_text: str | None = None,
) -> Path:
    skill_dir = root / bucket / "skills" / name
    flag_line = "disable-model-invocation: true\n" if disable_model_invocation else ""
    _write(
        skill_dir / "SKILL.md",
        f"---\nname: {name}\ndescription: \"{description}\"\n{flag_line}---\n\nBody.\n",
    )
    if fires_text is not None:
        _write(skill_dir / "tests" / "fires_example.md", fires_text)
    if silent_text is not None:
        _write(skill_dir / "tests" / "stays_silent_example.md", silent_text)
    return skill_dir


class TestMechanismVerified(unittest.TestCase):
    def test_correct_slash_command_fixtures_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(
                root,
                "corpus",
                "demo",
                disable_model_invocation=True,
                fires_text="User types `/demo` to load the principle.\n",
                silent_text="User asks something unrelated. No explicit invocation happens.\n",
            )
            errors, _ = ctm.check(root)
            self.assertEqual(errors, [])

    def test_natural_language_only_fires_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(
                root,
                "corpus",
                "demo",
                disable_model_invocation=True,
                fires_text="User asks about widgets in plain conversation.\n",
                silent_text="User asks about something else entirely.\n",
            )
            errors, _ = ctm.check(root)
            self.assertTrue(any("must contain that literal string" in e for e in errors), errors)

    def test_slash_command_in_negative_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(
                root,
                "corpus",
                "demo",
                disable_model_invocation=True,
                fires_text="User types `/demo`.\n",
                silent_text="No `/demo` was typed here, so it stays silent.\n",
            )
            errors, _ = ctm.check(root)
            self.assertTrue(any("can't credibly claim to stay silent" in e for e in errors), errors)


class TestVocabularyFloor(unittest.TestCase):
    def test_auto_invoked_skill_not_mechanism_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(
                root,
                "product",
                "demo",
                disable_model_invocation=False,
                description="Apply when the user asks about widgets.",
                fires_text="User asks about widgets in plain conversation.\n",
                silent_text="User asks about something unrelated.\n",
            )
            errors, warnings = ctm.check(root)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_auto_invoked_skill_no_shared_vocabulary_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(
                root,
                "product",
                "demo",
                disable_model_invocation=False,
                description="Apply when the user asks about widgets.",
                fires_text="Completely unrelated sentence about something else.\n",
                silent_text="Also unrelated.\n",
            )
            errors, warnings = ctm.check(root)
            self.assertEqual(errors, [])
            self.assertTrue(any("shares no significant word" in w for w in warnings), warnings)


class TestOutOfScope(unittest.TestCase):
    def test_skill_without_fixtures_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "engine", "demo", disable_model_invocation=True)
            errors, warnings = ctm.check(root)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
