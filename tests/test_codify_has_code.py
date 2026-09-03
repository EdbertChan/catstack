#!/usr/bin/env python3
"""Tests for scripts/check_codify_has_code.py. Diffs below are real hunks:
the 2026-09-01 prove-it-ship-gate SKILL.md pointer, and PR #89's
visual-proof prose (a rule added with no code, the exact drift shape)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_codify_has_code as cc  # noqa: E402

# real: PR #89 added this to product/skills/visual-proof/SKILL.md with no code change
PR89_DIFF = """diff --git a/product/skills/visual-proof/SKILL.md b/product/skills/visual-proof/SKILL.md
--- a/product/skills/visual-proof/SKILL.md
+++ b/product/skills/visual-proof/SKILL.md
@@ -20,0 +21,4 @@
+## Match the proof source to the claim
+
+By default, a screenshot means a pixel capture from the actual rendered flow.
+Mocked, redrawn, generated, or accessibility-only proxy UI does not satisfy a request for a screenshot.
"""
PR89_PATHS = ["product/skills/visual-proof/SKILL.md", "product/skills/visual-proof/tests/fires_example.md"]

# real: prove-it-ship-gate SKILL.md pointer, landed together with the hook code
HOOK_DIFF = """diff --git a/corpus/skills/prove-it-ship-gate/SKILL.md b/corpus/skills/prove-it-ship-gate/SKILL.md
--- a/corpus/skills/prove-it-ship-gate/SKILL.md
+++ b/corpus/skills/prove-it-ship-gate/SKILL.md
@@ -25,0 +26,3 @@
+## Mechanical enforcement
+
+The same-turn check is a Stop hook. It blocks the turn when a done/shipped/live claim sits
"""
HOOK_PATHS = ["corpus/skills/prove-it-ship-gate/SKILL.md", "engine/hooks/prove-it-ship-gate/detect.py"]


class TestFlagsProseOnlyRules(unittest.TestCase):
    def test_flags_pr89_shape_rule_without_code(self):
        problems = cc.check(PR89_DIFF, PR89_PATHS)
        self.assertTrue(problems, "expected a failure for rule prose with no code")
        self.assertIn("no code change", problems[0])
        self.assertTrue(any("does not satisfy" in p for p in problems), problems)

    def test_flags_claude_md_rule_without_code(self):
        diff = "+++ b/CLAUDE.md\n+- Never claim code works without evidence.\n"
        self.assertTrue(cc.check(diff, ["CLAUDE.md"]))


class TestStaysSilent(unittest.TestCase):
    def test_silent_when_code_lands_with_the_rule(self):
        self.assertEqual(cc.check(HOOK_DIFF, HOOK_PATHS), [])

    def test_silent_on_prose_without_rule_words(self):
        diff = "+++ b/corpus/skills/x/SKILL.md\n+Found via /reflect on a 2026-08-17 session.\n"
        self.assertEqual(cc.check(diff, ["corpus/skills/x/SKILL.md"]), [])

    def test_silent_on_test_fixture_prose(self):
        diff = "+++ b/corpus/skills/x/tests/fires_example.md\n+This MUST fire.\n"
        self.assertEqual(cc.check(diff, ["corpus/skills/x/tests/fires_example.md"]), [])

    def test_silent_on_removed_rule_lines(self):
        diff = "+++ b/CLAUDE.md\n-- Never do X.\n+- Do X when asked.\n"
        self.assertEqual(cc.check(diff, ["CLAUDE.md"]), [])


class TestCliAgainstRealGit(unittest.TestCase):
    """Builds a throwaway repo: base commit, then a prose-only rule commit."""

    def _run(self, repo: Path, *args: str):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(args, cwd=repo, capture_output=True, text=True, env=env)

    def test_cli_fails_then_passes_once_code_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._run(repo, "git", "init", "-q", "-b", "main")
            (repo / "scripts").mkdir()
            (repo / "scripts" / "check_codify_has_code.py").write_text((REPO / "scripts" / "check_codify_has_code.py").read_text())
            (repo / "CLAUDE.md").write_text("# rules\n")
            self._run(repo, "git", "add", "-A"); self._run(repo, "git", "commit", "-qm", "base")
            self._run(repo, "git", "checkout", "-qb", "feature")
            (repo / "CLAUDE.md").write_text("# rules\n- Never retry a denied tool call through another tool.\n")
            self._run(repo, "git", "commit", "-qam", "prose only")
            script = repo / "scripts" / "check_codify_has_code.py"
            fail = self._run(repo, sys.executable, str(script), "--base", "main")
            self.assertEqual(fail.returncode, 1, fail.stdout + fail.stderr)
            self.assertIn("no code change", fail.stderr)
            allowed = self._run(repo, sys.executable, str(script), "--base", "main", "--allow-prose-only")
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            (repo / "hook.py").write_text("print('enforced')\n")
            self._run(repo, "git", "add", "-A"); self._run(repo, "git", "commit", "-qm", "code")
            ok = self._run(repo, sys.executable, str(script), "--base", "main")
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)


if __name__ == "__main__":
    unittest.main()
