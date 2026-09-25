#!/usr/bin/env python3
"""Tests for make-pr's rule-scope check: a rule whose lead is one incident.

No test calls a real model. The stand-in judge answers from the shipped
`incident-scoped-rule` dictionary -- a text matches when it carries one of
the dictionary's own match examples -- so these cases exercise the real
dictionary and the real diff parsing, and only the model call is faked.

The three rule texts below are the ones the gate exists to tell apart: a
phone-alert rule whose lead is one tool and one error string (flagged), the
same lesson written generally (silent), and a general lead that names a
label only as an example (silent).
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

import preflight as pf  # noqa: E402
import rule_scope_check  # noqa: E402

RULE_FILE = "corpus/skills/cat-mode/references/autonomy.md"

PHONE_ALERT = [
    "- **Asked for a phone alert? Send a test push now.** A reply that ends",
    '  with "Mobile push not sent (Remote Control inactive)" means the alert',
    "  never left the machine, so send one test push before promising it.",
]
GENERAL_REWRITE = [
    "- **Anything set up to fire later gets one harmless test fire now.**",
    "  A delivery path that has never carried a message is a guess; one",
    "  throwaway send turns it into a reading.",
]
AUTO_MERGE_LABEL = [
    "- **An auto-merge label is a live trigger, not an annotation.** A label",
    "  such as `admin-bypass` is wired to a merge automation, so applying it",
    "  to a PR whose branch is still being worked on lands that work",
    "  half-finished the instant CI goes green, with no human in the loop.",
]


def diff_for(path: str, added: list[str], start: int = 21) -> str:
    head = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}",
            f"@@ -{start - 1},0 +{start},{len(added)} @@"]
    return "\n".join(head + ["+" + line for line in added]) + "\n"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def dictionary_judge():
    """Answer the way the dictionary's own examples say the meaning goes."""
    phrases = rule_scope_check._load("llm_judge_phrases", "phrases.py")
    dictionary = phrases.load(rule_scope_check.CHECKER)
    prompts: list[str] = []

    def ask(prompt: str) -> dict:
        prompts.append(prompt)
        text = _norm(prompt.split("TEXT:", 1)[-1])
        closest = next((ex for ex in dictionary["match"] if _norm(ex) in text), None)
        return {"outcome": "answered", "runner": "fake",
                "answer": {"match": closest is not None, "closest": closest or ""},
                "attempts": []}

    ask.prompts = prompts
    return ask


def silent(prompt: str) -> dict:
    return {"outcome": "unchecked", "runner": None, "answer": None,
            "attempts": [{"runner": "fake", "reason": "timed out"}]}


class TestRuleScope(unittest.TestCase):
    def test_incident_scoped_rule_fires_and_names_its_lead(self):
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, PHONE_ALERT))
        outcome, lines = rule_scope_check.check(blocks, ask=dictionary_judge())
        self.assertEqual(outcome, "hit", lines)
        self.assertTrue(any(line.startswith("hit") for line in lines), lines)
        self.assertIn(f"{RULE_FILE}:21", lines[0])
        self.assertIn("Asked for a phone alert? Send a test push now.", lines[0])
        self.assertIn("general lesson", lines[-1])

    def test_the_same_lesson_stated_generally_stays_silent(self):
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, GENERAL_REWRITE))
        ask = dictionary_judge()
        outcome, lines = rule_scope_check.check(blocks, ask=ask)
        self.assertEqual((outcome, lines), ("clean", []))
        self.assertEqual(len(ask.prompts), 1)

    def test_a_general_lead_that_names_a_label_as_an_example_stays_silent(self):
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, AUTO_MERGE_LABEL))
        ask = dictionary_judge()
        outcome, lines = rule_scope_check.check(blocks, ask=ask)
        self.assertEqual((outcome, lines), ("clean", []))
        self.assertIn("admin-bypass", ask.prompts[0])

    def test_no_runner_answering_is_unchecked_not_clean(self):
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, GENERAL_REWRITE))
        outcome, lines = rule_scope_check.check(blocks, ask=silent)
        self.assertEqual(outcome, "unchecked")
        self.assertIn("timed out", lines[0])
        self.assertIn(f"{RULE_FILE}:21", lines[0])

    def test_hit_outranks_unchecked(self):
        blocks = (rule_scope_check.added_blocks(diff_for(RULE_FILE, GENERAL_REWRITE))
                  + rule_scope_check.added_blocks(diff_for(RULE_FILE, PHONE_ALERT, start=40)))
        self.assertEqual(len(blocks), 2)
        answered = {"outcome": "answered", "runner": "fake",
                    "answer": {"match": True, "closest": ""}, "attempts": []}
        answers = iter([silent(""), answered])
        outcome, _ = rule_scope_check.check(blocks, ask=lambda prompt: next(answers))
        self.assertEqual(outcome, "hit")

    def test_a_whole_rule_reaches_the_judge_not_just_its_first_line(self):
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, PHONE_ALERT))
        self.assertEqual(len(blocks), 1)
        self.assertIn("never left the machine", blocks[0]["text"])

    def test_markdown_outside_the_skill_buckets_is_never_judged(self):
        for path in ("docs/ecosystem.md", "README.md", "engine/hooks/llm-judge/README.md"):
            self.assertEqual(rule_scope_check.added_blocks(diff_for(path, PHONE_ALERT)), [], path)

    def test_quoted_trigger_examples_under_tests_are_never_judged(self):
        blocks = rule_scope_check.added_blocks(
            diff_for("engine/skills/automate-me/tests/fires_example.md", PHONE_ALERT))
        self.assertEqual(blocks, [])

    def test_headings_fences_and_tables_are_not_rule_lines(self):
        added = ["## Autonomy", "```sh", "python3 scripts/ci/check_no_dated_provenance.py --base main", "```",
                 "| gate | what it reads | when it runs | who owns it |"]
        self.assertEqual(rule_scope_check.added_blocks(diff_for(RULE_FILE, added)), [])

    def test_an_added_line_with_no_added_lead_is_not_judged_headless(self):
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, ["  never left the machine."]))
        self.assertEqual(blocks, [])

    def test_a_hard_wrapped_paragraph_is_one_rule_not_one_per_line(self):
        """Rule prose wraps at the same indent it starts at, so line shape alone
        reads every wrapped line as its own lead. Judged that way, the closing
        line of make-pr's own gate paragraph was flagged as a rule about
        check_no_dated_provenance.py -- a fragment, matched on the tool it
        quotes, with its real lead sitting three lines above."""
        added = ["A PR that adds rule lines to skill prose runs one more gate,",
                 "which sends each added rule to the judge and fails on a hit.",
                 "It runs beside `scripts/ci/check_no_dated_provenance.py`, which",
                 "reads shapes rather than meaning and stays as it is."]
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, added, start=1))
        self.assertEqual(len(blocks), 1, blocks)
        self.assertEqual(blocks[0]["line"], 1)
        self.assertIn("stays as it is", blocks[0]["text"])

    def test_a_paragraph_continued_from_unchanged_context_is_not_judged(self):
        diff = "\n".join([
            f"--- a/{RULE_FILE}", f"+++ b/{RULE_FILE}", "@@ -20,2 +20,3 @@",
            " A rule is stated as the general lesson it teaches, so that the next",
            "+case of the same kind, worded differently, still meets it.",
            " ",
        ]) + "\n"
        self.assertEqual(rule_scope_check.added_blocks(diff), [])

    def test_a_bullet_still_leads_when_it_follows_prose(self):
        added = ["Gates that read meaning report three outcomes, never two.",
                 "- **A check that could not run is not a pass.** Say unchecked."]
        blocks = rule_scope_check.added_blocks(diff_for(RULE_FILE, added, start=1))
        self.assertEqual([b["line"] for b in blocks], [1, 2], blocks)

    def test_dictionary_loads_with_the_checker_name(self):
        phrases = rule_scope_check._load("llm_judge_phrases", "phrases.py")
        dictionary = phrases.load(rule_scope_check.CHECKER)
        self.assertEqual(dictionary["checker"], "incident-scoped-rule")
        self.assertIn("Asked for a phone alert? Send a test push now.", " ".join(dictionary["match"]))
        self.assertTrue(any("auto-merge label is a live trigger" in ex for ex in dictionary["not_match"]))

    def test_unreadable_base_is_unchecked_not_clean(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status = rule_scope_check.main(["--base", "refs/heads/no-such-base-for-tests"])
        self.assertEqual(status, 2)
        self.assertIn("unchecked rule scope", err.getvalue())

    def test_unchecked_judge_exits_non_zero(self):
        original = rule_scope_check.check
        rule_scope_check.check = lambda blocks: ("unchecked", ["unchecked rule scope: no judge runner answered"])
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                status = rule_scope_check.main(["--base", "HEAD"])
        finally:
            rule_scope_check.check = original
        self.assertEqual(status, 1)
        self.assertIn("rule scope unchecked", out.getvalue())


class TestPreflightWiring(unittest.TestCase):
    """Which paths get the gate is pinned in test_preflight.TestGates; this is
    the other half -- that a non-zero exit from it stops the PR."""

    def test_the_gate_preflight_runs_is_this_script(self):
        self.assertEqual(os.path.join(pf.REPO_ROOT, pf.RULE_SCOPE_CHECK),
                         os.path.abspath(rule_scope_check.__file__))

    def test_a_failing_rule_scope_gate_fails_preflight(self):
        original = pf.gates_for
        pf.gates_for = lambda paths, base=None: [
            [sys.executable, "-c", "import sys; print('unchecked rule scope'); sys.exit(1)"]]
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                status = pf.main(["--paths", "corpus/skills/cat-mode/SKILL.md"])
        finally:
            pf.gates_for = original
        self.assertEqual(status, 1, out.getvalue())
        self.assertIn("unchecked rule scope", out.getvalue())


if __name__ == "__main__":
    unittest.main()
