#!/usr/bin/env python3
"""Tests for scripts/check_skills_three_harnesses.py and link helper."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(REPO_ROOT, "scripts", "check_skills_three_harnesses.py")
LINK = os.path.join(REPO_ROOT, "scripts", "link_skill_three_harnesses.sh")


class TestCheckRepoMode(unittest.TestCase):
    def test_repo_check_passes_on_this_checkout(self):
        result = subprocess.run(
            ["python3", CHECK],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("ok", result.stdout)


class TestCheckHomeMode(unittest.TestCase):
    def test_partial_same_source_symlinks_fail(self):
        with tempfile.TemporaryDirectory() as home:
            src = os.path.join(home, "src", "wipe-bad-pr")
            os.makedirs(src)
            with open(os.path.join(src, "SKILL.md"), "w") as handle:
                handle.write("---\nname: wipe-bad-pr\n---\n")
            for agent in (".claude", ".cursor"):
                skills = os.path.join(home, agent, "skills")
                os.makedirs(skills)
                os.symlink(src, os.path.join(skills, "wipe-bad-pr"))
            # Missing ~/.codex/skills/wipe-bad-pr on purpose.
            result = subprocess.run(
                ["python3", CHECK, "--home", "--home-dir", home],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("wipe-bad-pr", result.stderr)
            self.assertIn("codex", result.stderr)

    def test_all_three_same_source_passes(self):
        with tempfile.TemporaryDirectory() as home:
            src = os.path.join(home, "src", "wipe-bad-pr")
            os.makedirs(src)
            with open(os.path.join(src, "SKILL.md"), "w") as handle:
                handle.write("---\nname: wipe-bad-pr\n---\n")
            for agent in (".claude", ".cursor", ".codex"):
                skills = os.path.join(home, agent, "skills")
                os.makedirs(skills)
                os.symlink(src, os.path.join(skills, "wipe-bad-pr"))
            result = subprocess.run(
                ["python3", CHECK, "--home", "--home-dir", home],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_unrelated_real_dirs_in_two_harnesses_are_ignored(self):
        with tempfile.TemporaryDirectory() as home:
            for agent in (".claude", ".codex"):
                path = os.path.join(home, agent, "skills", "invoker-make-pr")
                os.makedirs(path)
                with open(os.path.join(path, "SKILL.md"), "w") as handle:
                    handle.write("---\nname: invoker-make-pr\n---\n")
            result = subprocess.run(
                ["python3", CHECK, "--home", "--home-dir", home],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


class TestLinkScript(unittest.TestCase):
    def test_links_all_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "demo-skill")
            os.makedirs(skill)
            with open(os.path.join(skill, "SKILL.md"), "w") as handle:
                handle.write("---\nname: demo-skill\n---\n")
            home = os.path.join(tmp, "home")
            env = {**os.environ, "HOME": home}
            result = subprocess.run(
                ["bash", LINK, skill],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            for agent in (".claude", ".cursor", ".codex"):
                target = os.path.join(home, agent, "skills", "demo-skill")
                self.assertTrue(os.path.islink(target), target)
                self.assertEqual(os.readlink(target), skill)


if __name__ == "__main__":
    unittest.main()
