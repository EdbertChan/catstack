#!/usr/bin/env python3
"""Mechanical checks for show-me-your-work: frontmatter (recommendable, not
always-on), log.sh row shape, and formula-prefix sanitizing.

Run: python3 -m unittest discover -s tests -v
"""
import os
import stat
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "show-me-your-work")
SKILL_PATH = os.path.join(SKILL_DIR, "SKILL.md")
LOG_SH = os.path.join(SKILL_DIR, "scripts", "log.sh")
TEMPLATE = os.path.join(SKILL_DIR, "references", "decision-log-template.tsv")


def read_skill():
    with open(SKILL_PATH, encoding="utf-8") as handle:
        return handle.read()


class TestShowMeYourWorkSkill(unittest.TestCase):
    def test_skill_files_exist(self):
        self.assertTrue(os.path.isfile(SKILL_PATH), SKILL_PATH)
        self.assertTrue(os.path.isfile(LOG_SH), LOG_SH)
        self.assertTrue(os.path.isfile(TEMPLATE), TEMPLATE)

    def test_log_sh_is_executable(self):
        mode = os.stat(LOG_SH).st_mode
        self.assertTrue(mode & stat.S_IXUSR, "log.sh must be executable")

    def test_no_disable_model_invocation(self):
        # pstack sets disable-model-invocation because poteto-mode routes it.
        # catstack has no router, so the description must stay eligible for
        # auto-recommend. Flipping this on would hide the skill.
        text = read_skill()
        self.assertNotIn("disable-model-invocation", text.split("---", 2)[1])

    def test_description_names_unattended_triggers_not_short_fixes(self):
        text = read_skill()
        frontmatter = text.split("---", 2)[1]
        self.assertIn("overnight", frontmatter)
        self.assertIn("babysit", frontmatter)
        self.assertIn("Not for a short same-turn fix", frontmatter)

    def test_distinguishes_prove_it(self):
        text = read_skill()
        self.assertIn("This is not prove-it", text)
        self.assertIn("same-turn", text)

    def test_template_is_header_only(self):
        with open(TEMPLATE, encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle if line.strip()]
        self.assertEqual(lines, ["ts\tphase\tdecision\twhy\tevidence\tresult"])


class TestLogSh(unittest.TestCase):
    def _run(self, logfile, *cells):
        return subprocess.run(
            ["bash", LOG_SH, logfile, *cells],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_writes_header_then_one_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            logfile = os.path.join(tmp, "decisions.tsv")
            result = self._run(
                logfile, "harness", "took baseline screenshots",
                "need old vs new", "scripts/snapshot.sh", "saved 12",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(logfile, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0], "ts\tphase\tdecision\twhy\tevidence\tresult")
            cells = lines[1].split("\t")
            self.assertEqual(len(cells), 6)
            self.assertRegex(cells[0], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertEqual(cells[1:], [
                "harness", "took baseline screenshots",
                "need old vs new", "scripts/snapshot.sh", "saved 12",
            ])

    def test_creates_audit_dir_and_prefixes_formula_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            logfile = os.path.join(tmp, ".audit", "port.tsv")
            result = self._run(
                logfile, "port", "kept helper", "looked cheaper",
                "=HYPERLINK(\"http://evil\")", "-1 files",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(logfile, encoding="utf-8") as handle:
                row = handle.read().splitlines()[1]
            cells = row.split("\t")
            self.assertTrue(cells[4].startswith("'="), cells[4])
            self.assertTrue(cells[5].startswith("'-"), cells[5])

    def test_wrong_argc_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", LOG_SH, os.path.join(tmp, "x.tsv"), "only", "five"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("usage:", result.stderr)

    def test_strips_tabs_and_newlines_from_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            logfile = os.path.join(tmp, "decisions.tsv")
            result = self._run(
                logfile, "phase", "decision\twith\ttab",
                "why\nnewline", "evidence", "result",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(logfile, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            self.assertEqual(len(lines), 2)
            cells = lines[1].split("\t")
            self.assertEqual(len(cells), 6)
            self.assertNotIn("\t", cells[2])
            self.assertIn("with", cells[2])
            self.assertNotIn("\n", cells[3])


if __name__ == "__main__":
    unittest.main()
