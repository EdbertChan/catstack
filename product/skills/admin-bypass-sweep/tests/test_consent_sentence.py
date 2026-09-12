from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BRANCH_NAMES = ("main", "master")
CONSENT_RE = re.compile(
    r"^> (?P<template>I understand this bypasses CI and force-merges to "
    r"\{resolved_trunk_branch\})$",
    re.MULTILINE,
)


def consent_template() -> str:
    match = CONSENT_RE.search(SKILL)
    if match is None:
        raise AssertionError("consent template is missing or not in the expected form")
    return match.group("template")


def render_consent(trunk_branch: str) -> str:
    return consent_template().replace("{resolved_trunk_branch}", trunk_branch)


class ConsentSentenceTest(unittest.TestCase):
    def test_consent_template_embeds_no_literal_branch_name(self):
        template = consent_template()
        for branch_name in BRANCH_NAMES:
            self.assertNotRegex(template, rf"\b{re.escape(branch_name)}\b")
        self.assertIn("{resolved_trunk_branch}", template)

    def test_fixture_repos_render_required_sentence_for_their_trunk(self):
        for fixture in sorted(FIXTURES.iterdir()):
            with self.subTest(fixture=fixture.name):
                trunk_branch = (fixture / "trunk_branch.txt").read_text(encoding="utf-8").strip()
                self.assertEqual(
                    render_consent(trunk_branch),
                    f"I understand this bypasses CI and force-merges to {trunk_branch}",
                )

    def test_no_paraphrase_and_full_sentence_rules_remain_explicit(self):
        self.assertIn("must type the resolved consent sentence in full", SKILL)
        self.assertIn("Do not accept a paraphrase", SKILL)


if __name__ == "__main__":
    unittest.main()
