#!/usr/bin/env python3
"""Pin the rule-text requirements this skill states, and the gates that run them.

A mined rule reaches skill prose through this skill, so the two requirements on
that text -- dateless, and stated as the general lesson -- live in its own
bullet. Each one names the checker that enforces it; a requirement whose
checker is renamed or deleted has to fail here rather than survive as prose
nothing runs.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "SKILL.md")
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
DATE_GATE = "scripts/ci/check_no_dated_provenance.py"
SCOPE_GATE = "engine/skills/make-pr/scripts/rule_scope_check.py"
CREATE_SKILL = "engine/skills/create-skill/SKILL.md"
PRODUCT_SKILLS = "/".join(("product", "skills"))
TECHNICAL_WRITING = f"{PRODUCT_SKILLS}/technical-writing/SKILL.md"
PROSE_GATE = f"{PRODUCT_SKILLS}/technical-writing/scripts/grade_prose.py"
CLUSTER_SCRIPT = "engine/skills/reflect/scripts/cluster_interventions.py"
CORPUS_SCAN = "engine/skills/reflect/scripts/corpus_scan.py"
STALE_SENTENCES = ("No `create-skill` built-in here", "No `unslop` skill exists")
DRAFT_PLACEHOLDER = "/".join(("corpus", "skills", "<handle>-mode", "SKILL.md"))


def skill_text() -> str:
    with open(SKILL, encoding="utf-8") as handle:
        return handle.read()


def rule_bullet() -> str:
    for line in skill_text().splitlines():
        if line.startswith("- **No dates or incident narrative"):
            return line
    return ""


def section(heading: str) -> str:
    """Return the body of the ``## <heading>`` section, up to the next ``## `` line."""
    text = skill_text()
    start = text.index(f"\n## {heading}")
    rest = text[start + 1 :]
    end = rest.find("\n## ", 1)
    return rest if end == -1 else rest[:end]


def grader_command() -> str:
    """Return the one fenced bash line in step 5 that runs the prose grader."""
    match = re.search(r"```bash\n(python3 -c .*?)\n```", section("5. Iterate on prose"), re.S)
    return match.group(1) if match else ""


def run_grader(draft_text: str) -> subprocess.CompletedProcess:
    """Run the skill's own grader line on a draft, from the repo root as the skill says."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
        handle.write(draft_text)
        path = handle.name
    try:
        command = grader_command().replace(DRAFT_PLACEHOLDER, path)
        command = command.replace("python3 -c", f"{sys.executable} -c", 1)
        return subprocess.run(command, shell=True, cwd=REPO_ROOT, capture_output=True, text=True)
    finally:
        os.unlink(path)


class TestRuleTextRequirements(unittest.TestCase):
    def test_inventory_installs_automate_me_to_all_harnesses(self):
        inventory = os.path.join(REPO_ROOT, "skills.toml")
        with open(inventory, encoding="utf-8") as handle:
            text = handle.read()
        block = text.split("[skills.automate-me]", 1)[1].split("[skills.", 1)[0]
        self.assertIn('harnesses = "all"', block)

    def test_skill_documents_codex_transcript_handling(self):
        self.assertIn("Codex rollout transcript", skill_text())

    def test_the_rule_bullet_bans_dates_and_incident_narrative(self):
        self.assertIn("dateless", rule_bullet())
        self.assertIn(DATE_GATE, rule_bullet())

    def test_the_rule_bullet_requires_the_general_lesson_in_the_main_sentence(self):
        bullet = rule_bullet()
        self.assertIn("general lesson", bullet)
        self.assertIn("only as an example", bullet)

    def test_the_rule_bullet_names_the_checker_that_reads_the_rule_scope(self):
        self.assertIn(SCOPE_GATE, rule_bullet())

    def test_both_named_checkers_exist(self):
        for gate in (DATE_GATE, SCOPE_GATE):
            self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, gate)), gate)

    def test_a_judge_that_cannot_answer_is_not_a_pass(self):
        self.assertIn("could not answer", rule_bullet())


class TestComposedSkills(unittest.TestCase):
    def test_the_stale_denials_are_gone(self):
        for sentence in STALE_SENTENCES:
            self.assertNotIn(sentence, skill_text(), sentence)

    def test_step_4_routes_drafting_through_create_skill(self):
        step = section("4. Draft the skill")
        self.assertIn(CREATE_SKILL, step)
        self.assertIn("install.sh", step)
        self.assertIn("check_skill_file_refs.py", step)

    def test_step_5_routes_prose_through_technical_writing(self):
        step = section("5. Iterate on prose")
        self.assertIn(TECHNICAL_WRITING, step)
        self.assertIn(PROSE_GATE, step)

    def test_step_1_clusters_before_any_agent_reads(self):
        step = section("1. Mine their history")
        self.assertIn(CLUSTER_SCRIPT, step)
        self.assertIn(CORPUS_SCAN, step)
        self.assertLess(step.index("Cluster first"), step.index("Run parallel `Agent`"))

    def test_step_1_uses_fresh_capped_slice_agents_and_the_parent_clusters(self):
        step = section("1. Mine their history")
        self.assertIn("fresh agent, never a fork", step)
        self.assertIn("Cap each slice at a stated number of sessions", step)
        self.assertIn("the parent clusters the returned lists itself", step)

    def test_single_project_mode_reads_only_this_projects_transcripts(self):
        self.assertIn(
            "Single-project mode reads only this project's transcript directory",
            section("1. Mine their history"),
        )

    def test_every_named_path_exists(self):
        for path in (CREATE_SKILL, TECHNICAL_WRITING, PROSE_GATE, CLUSTER_SCRIPT, CORPUS_SCAN):
            self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, path)), path)

    def require_grader(self):
        if not os.path.isfile(os.path.join(REPO_ROOT, PROSE_GATE)):
            self.skipTest(f"unchecked: {PROSE_GATE} is not installed in this checkout")

    def test_the_grader_command_fails_on_a_bad_draft(self):
        self.require_grader()
        result = run_grader("The loader parses the file; the compiler checks it.\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("semicolon", result.stdout)

    def test_the_grader_command_passes_a_clean_draft(self):
        self.require_grader()
        result = run_grader("The loader parses the file. The compiler checks it.\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "clean")


if __name__ == "__main__":
    unittest.main()
