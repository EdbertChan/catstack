#!/usr/bin/env python3
"""lesson_route.py refuses to turn a restated existing rule into a new lesson.

Fail-before this gate: restated-rule.json on_hit called a restated existing
rule "automate-me evidence", and fires.jsonl (assistant: "It is; I skipped it.")
had no script that could print already-covered. These tests pin the buckets.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import lesson_route as lr  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "lesson_route.py")
FIRES = os.path.join(FIXTURES, "restated_rule", "fires.jsonl")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS))))
PHRASE = os.path.join(REPO, "engine", "hooks", "llm-judge", "phrases", "restated-rule.json")
SKILL_MD = os.path.join(os.path.dirname(SCRIPTS), "SKILL.md")


def run(*args):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestFiresFixtureIsAlreadyCovered(unittest.TestCase):
    def test_fires_transcript_prints_already_covered_not_automate_me(self):
        res = run("--from-transcript", FIRES, "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        payload = json.loads(res.stdout)
        self.assertEqual(payload["bucket"], lr.ALREADY_COVERED)
        self.assertNotEqual(payload["bucket"], lr.AUTOMATE_ME)
        self.assertIn("do not route to automate-me", payload["rationale"])

    def test_admitted_skip_pair_is_already_covered(self):
        result = lr.route(
            quote="I thought that was a skill that we enforce in catstack?",
            assistant_reply="It is; I skipped it.",
            kind="restated-rule",
        )
        self.assertEqual(result["bucket"], lr.ALREADY_COVERED)
        self.assertEqual(result["action"], "reject")


class TestAlreadyCoveredShowsItsOverlap(unittest.TestCase):
    def test_already_covered_rationale_names_the_shared_words_that_decided_it(self):
        result = lr.route(
            quote="split the worktree per review unit because engine and corpus changes fail preflight",
            skill_text="Group items by owning repo. Engine and corpus edits that fail preflight are split.",
            kind="durable-lesson",
        )
        self.assertEqual(result["bucket"], lr.ALREADY_COVERED)
        for word in ("engine", "corpus", "split"):
            self.assertIn(word, result["rationale"])

    def test_cli_json_rationale_names_the_shared_words(self):
        res = run(
            "--kind", "durable-lesson",
            "--quote", "split the worktree per review unit because engine and corpus changes fail preflight",
            "--skill-text", "Group items by owning repo. Engine and corpus edits that fail preflight are split.",
            "--json",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        payload = json.loads(res.stdout)
        self.assertEqual(payload["bucket"], lr.ALREADY_COVERED)
        self.assertIn("engine", payload["rationale"])

    def test_quote_whose_key_noun_is_absent_from_the_skill_is_not_already_covered(self):
        result = lr.route(
            quote="plan one worktree per review unit before spawning the apply agent",
            skill_text="Group Accepted items by owning repo.",
            kind="durable-lesson",
        )
        self.assertNotEqual(result["bucket"], lr.ALREADY_COVERED)
        self.assertNotIn("target skill already states the rule", result["rationale"])


class TestPreferenceStillAutomates(unittest.TestCase):
    def test_preference_with_no_skill_is_automate_me(self):
        res = run(
            "--kind", "preference",
            "--quote", "always open a PR after green without asking me",
            "--json",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        payload = json.loads(res.stdout)
        self.assertEqual(payload["bucket"], lr.AUTOMATE_ME)

    def test_no_rule_yet_preference_is_automate_me(self):
        result = lr.route(
            quote="we don't have a rule for this yet, can you add one?",
            kind="preference",
        )
        self.assertEqual(result["bucket"], lr.AUTOMATE_ME)


class TestSkillNotUsed(unittest.TestCase):
    def test_unopened_skill_is_skill_not_used(self):
        res = run(
            "--quote", "tighten the retry backoff table",
            "--kind", "durable-lesson",
            "--skill-used", "no",
            "--json",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        payload = json.loads(res.stdout)
        self.assertEqual(payload["bucket"], lr.SKILL_NOT_USED)
        self.assertEqual(payload["action"], "reject")

    def test_missed_trigger_tunes_description(self):
        result = lr.route(
            quote="tighten the retry backoff table",
            kind="durable-lesson",
            skill_used=False,
            missed_trigger=True,
        )
        self.assertEqual(result["bucket"], lr.SKILL_NOT_USED)
        self.assertEqual(result["action"], "tune-description")


class TestAcceptedGates(unittest.TestCase):
    def test_durable_decision_changing_is_accepted(self):
        result = lr.route(
            quote="batch small Edits into fewer passes when the file is unchanged",
            kind="durable-lesson",
            skill_used=True,
        )
        self.assertEqual(result["bucket"], lr.ACCEPTED)

    def test_session_specific_quote_is_not_accepted(self):
        result = lr.route(
            quote="fix the bug at /Users/edbert/proj/foo.py for ticker AUR",
            kind="durable-lesson",
            skill_used=True,
        )
        self.assertNotEqual(result["bucket"], lr.ACCEPTED)


class TestOnHitAndSkillProsePointAtTheGate(unittest.TestCase):
    def test_restated_rule_on_hit_names_already_covered_not_automate_me(self):
        with open(PHRASE, encoding="utf-8") as handle:
            data = json.load(handle)
        on_hit = data["on_hit"]
        self.assertIn("already-covered", on_hit)
        self.assertNotIn("automate-me evidence", on_hit)

    def test_synthesize_step_requires_lesson_route(self):
        with open(SKILL_MD, encoding="utf-8") as handle:
            text = handle.read()
        start = text.index("### 4. Synthesize")
        end = text.index("### 5.", start)
        section = text[start:end]
        self.assertIn("lesson_route.py", section)
        self.assertIn("already-covered", section)
        self.assertIn("does not by itself create an automate-me row", section)


if __name__ == "__main__":
    unittest.main()
