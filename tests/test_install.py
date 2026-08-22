#!/usr/bin/env python3
"""End-to-end tests for install.sh, run as real subprocesses against a fake
$HOME so this never touches the real developer's actual ~/.claude,
~/.cursor, or ~/.codex directories.

Run: python3 -m unittest discover -s tests -v
(stdlib unittest + subprocess only, matches hooks/diu-stop/tests/test_hooks.py
and skills/reflect/scripts/tests/test_token_audit.py)

Sandboxing: every test overrides the HOME env var for a subprocess run of
the real install.sh. Confirmed safe by tracing every write in install.sh,
install_claude_hook.py, and install_codex_notify.py -- every write target is
built from $HOME (or os.path.expanduser("~/..."), which respects the
overridden env var, including inside the python3 subprocesses install.sh
shells out to -- each is a fresh process that inherits the overridden
environment). Every *read* is against the real $REPO_DIR/skills and
$REPO_DIR/hooks -- correct, since that's the real content under test -- and
nothing anywhere writes back into $REPO_DIR.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_SH = os.path.join(REPO_ROOT, "install.sh")
REAL_HOME = os.path.expanduser("~")


def run_install(fake_home, args=None):
    """Runs the REAL install.sh as a subprocess with HOME overridden to
    fake_home. Returns the completed process (stdout/stderr captured)."""
    assert fake_home != REAL_HOME, "refusing to run install.sh against the real home directory"
    env = {**os.environ, "HOME": fake_home}
    return subprocess.run(
        ["bash", INSTALL_SH] + (args or []),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def real_skill_names():
    return sorted(
        name
        for name in os.listdir(os.path.join(REPO_ROOT, "skills"))
        if os.path.isdir(os.path.join(REPO_ROOT, "skills", name))
    )


class TestNeverTouchesRealHome(unittest.TestCase):
    """Safety-guard meta-test: every other test in this file builds its fake
    $HOME the same way (tempfile.TemporaryDirectory()) -- this asserts that
    mechanism can never accidentally resolve to the real developer home
    directory, independent of any individual test's own assertions."""

    def test_temp_dir_is_never_the_real_home(self):
        with tempfile.TemporaryDirectory() as fake_home:
            self.assertNotEqual(os.path.realpath(fake_home), os.path.realpath(REAL_HOME))

    def test_run_install_refuses_a_home_equal_to_the_real_one(self):
        with self.assertRaises(AssertionError):
            run_install(REAL_HOME)


class TestSkillSymlinks(unittest.TestCase):
    CLAUDE_ONLY = {"reflect", "automate-me", "cat-mode", "narrow-the-scope"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake_home = self.tmp.name
        self.result = run_install(self.fake_home)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exits_zero(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_all_skills_symlinked_for_claude(self):
        for name in real_skill_names():
            target = os.path.join(self.fake_home, ".claude", "skills", name)
            self.assertTrue(os.path.islink(target), f"{name} not symlinked for claude")
            self.assertEqual(os.readlink(target), os.path.join(REPO_ROOT, "skills", name))

    def test_non_claude_only_skills_symlinked_for_cursor_and_codex(self):
        for name in real_skill_names():
            if name in self.CLAUDE_ONLY:
                continue
            for agent, skills_dir in (("cursor", ".cursor"), ("codex", ".codex")):
                target = os.path.join(self.fake_home, skills_dir, "skills", name)
                self.assertTrue(os.path.islink(target), f"{name} not symlinked for {agent}")
                self.assertEqual(os.readlink(target), os.path.join(REPO_ROOT, "skills", name))

    def test_claude_only_skills_absent_for_cursor_and_codex(self):
        for name in self.CLAUDE_ONLY:
            for skills_dir in (".cursor", ".codex"):
                target = os.path.join(self.fake_home, skills_dir, "skills", name)
                self.assertFalse(os.path.exists(target) or os.path.islink(target), f"{name} should be absent for {skills_dir}")

    def test_hooks_dir_symlinked_for_claude_and_codex(self):
        for agent_dir in (".claude", ".codex"):
            target = os.path.join(self.fake_home, agent_dir, "hooks", "diu-stop")
            self.assertTrue(os.path.islink(target))
            self.assertEqual(os.readlink(target), os.path.join(REPO_ROOT, "hooks", "diu-stop"))

    def test_cursor_hooks_json_seeded_as_real_file(self):
        target = os.path.join(self.fake_home, ".cursor", "hooks.json")
        self.assertTrue(os.path.exists(target))
        self.assertFalse(os.path.islink(target))

    def test_claude_global_claude_md_symlinked(self):
        target = os.path.join(self.fake_home, ".claude", "CLAUDE.md")
        self.assertTrue(os.path.islink(target))
        self.assertEqual(os.readlink(target), os.path.join(REPO_ROOT, "CLAUDE.md"))

    def test_claude_global_claude_md_absent_for_cursor_and_codex(self):
        for agent_dir in (".cursor", ".codex"):
            target = os.path.join(self.fake_home, agent_dir, "CLAUDE.md")
            self.assertFalse(os.path.exists(target) or os.path.islink(target))

    def test_cursor_always_on_pr_skill_rule_symlinked(self):
        rule = os.path.join(self.fake_home, ".cursor", "rules", "draft-pr-precedence.mdc")
        self.assertTrue(os.path.islink(rule), self.result.stdout)
        self.assertEqual(
            os.readlink(rule),
            os.path.join(REPO_ROOT, "cursor", "rules", "draft-pr-precedence.mdc"),
        )
        with open(rule) as f:
            text = f.read()
        self.assertIn("alwaysApply: true", text)
        self.assertIn("gh pr create", text)
        self.assertIn("/pr-skill", text)

    def test_pr_skill_commands_symlinked_for_claude_cursor_and_codex(self):
        for agent_dir in (".cursor", ".claude", ".codex"):
            for cmd in ("pr-skill", "draft-pr", "make-pr"):
                target = os.path.join(self.fake_home, agent_dir, "commands", f"{cmd}.md")
                self.assertTrue(os.path.islink(target), target)
                self.assertEqual(
                    os.readlink(target),
                    os.path.join(REPO_ROOT, "commands", f"{cmd}.md"),
                )

    def test_codex_agents_md_gets_draft_pr_block(self):
        path = os.path.join(self.fake_home, ".codex", "AGENTS.md")
        self.assertTrue(os.path.exists(path), self.result.stdout)
        with open(path) as f:
            text = f.read()
        self.assertIn("<!-- catstack-draft-pr -->", text)
        self.assertIn("<!-- /catstack-draft-pr -->", text)
        self.assertIn("gh pr create", text)
        self.assertIn("draft-pr", text)


class TestClaudeSettingsMerge(unittest.TestCase):
    def test_fresh_home_gets_both_hooks(self):
        with tempfile.TemporaryDirectory() as fake_home:
            run_install(fake_home)
            settings_path = os.path.join(fake_home, ".claude", "settings.json")
            self.assertTrue(os.path.exists(settings_path))
            with open(settings_path) as f:
                settings = json.load(f)
            stop_commands = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
            prompt_commands = [h["command"] for e in settings["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
            self.assertTrue(any("claude_stop_check.py" in c for c in stop_commands))
            self.assertTrue(any("claude_prompt_reminder.py" in c for c in prompt_commands))

    def test_preexisting_unrelated_keys_survive(self):
        with tempfile.TemporaryDirectory() as fake_home:
            claude_dir = os.path.join(fake_home, ".claude")
            os.makedirs(claude_dir)
            with open(os.path.join(claude_dir, "settings.json"), "w") as f:
                json.dump({"model": "sonnet", "theme": "dark"}, f)
            run_install(fake_home)
            with open(os.path.join(claude_dir, "settings.json")) as f:
                settings = json.load(f)
            self.assertEqual(settings["model"], "sonnet")
            self.assertEqual(settings["theme"], "dark")
            self.assertIn("Stop", settings["hooks"])
            self.assertIn("UserPromptSubmit", settings["hooks"])


class TestCodexNotifyWiring(unittest.TestCase):
    def test_fresh_home_with_no_config_toml_is_a_noop(self):
        with tempfile.TemporaryDirectory() as fake_home:
            result = run_install(fake_home)
            config_path = os.path.join(fake_home, ".codex", "config.toml")
            self.assertFalse(os.path.exists(config_path))
            self.assertIn("does not exist, nothing to wire", result.stdout)

    def test_preseeded_config_toml_gets_notify_wired(self):
        with tempfile.TemporaryDirectory() as fake_home:
            codex_dir = os.path.join(fake_home, ".codex")
            os.makedirs(codex_dir)
            config_path = os.path.join(codex_dir, "config.toml")
            with open(config_path, "w") as f:
                f.write('model = "gpt-5"\n')
            run_install(fake_home)
            with open(config_path) as f:
                text = f.read()
            self.assertIn('model = "gpt-5"', text)
            match = re.search(r"^notify = (\[.*\])$", text, re.MULTILINE)
            self.assertIsNotNone(match, text)
            notify = json.loads(match.group(1))
            self.assertTrue(any("codex_notify.py" in item for item in notify))


class TestIdempotency(unittest.TestCase):
    def test_rerun_reports_already_done_and_produces_no_duplicates(self):
        with tempfile.TemporaryDirectory() as fake_home:
            codex_dir = os.path.join(fake_home, ".codex")
            os.makedirs(codex_dir)
            with open(os.path.join(codex_dir, "config.toml"), "w") as f:
                f.write('model = "gpt-5"\n')

            first = run_install(fake_home)
            self.assertEqual(first.returncode, 0, first.stderr)

            settings_path = os.path.join(fake_home, ".claude", "settings.json")
            with open(settings_path) as f:
                settings_after_first = f.read()
            with open(os.path.join(codex_dir, "config.toml")) as f:
                config_after_first = f.read()

            second = run_install(fake_home)
            self.assertEqual(second.returncode, 0, second.stderr)

            self.assertNotIn("relink", second.stdout)
            self.assertNotIn("backup", second.stdout)
            self.assertIn("already linked", second.stdout)
            self.assertIn("already up to date", second.stdout)
            self.assertIn("already wired", second.stdout)

            with open(settings_path) as f:
                settings_after_second = f.read()
            with open(os.path.join(codex_dir, "config.toml")) as f:
                config_after_second = f.read()
            self.assertEqual(settings_after_first, settings_after_second)
            self.assertEqual(config_after_first, config_after_second)

            settings = json.loads(settings_after_second)
            self.assertEqual(len(settings["hooks"]["Stop"]), 1)
            self.assertEqual(len(settings["hooks"]["UserPromptSubmit"]), 2)


class TestForceAndRelink(unittest.TestCase):
    def test_real_directory_without_force_is_left_alone(self):
        with tempfile.TemporaryDirectory() as fake_home:
            target = os.path.join(fake_home, ".claude", "skills", "diu")
            os.makedirs(target)
            marker = os.path.join(target, "marker.txt")
            with open(marker, "w") as f:
                f.write("do not touch")

            result = run_install(fake_home)

            self.assertIn("skip", result.stdout)
            self.assertIn("rerun with --force", result.stdout)
            self.assertFalse(os.path.islink(target))
            self.assertTrue(os.path.exists(marker))
            with open(marker) as f:
                self.assertEqual(f.read(), "do not touch")

    def test_real_directory_with_force_gets_backed_up_and_replaced(self):
        with tempfile.TemporaryDirectory() as fake_home:
            target = os.path.join(fake_home, ".claude", "skills", "diu")
            os.makedirs(target)
            marker = os.path.join(target, "marker.txt")
            with open(marker, "w") as f:
                f.write("do not touch")

            result = run_install(fake_home, args=["--force"])

            self.assertIn("backup", result.stdout)
            self.assertTrue(os.path.islink(target))
            self.assertEqual(os.readlink(target), os.path.join(REPO_ROOT, "skills", "diu"))

            skills_dir = os.path.join(fake_home, ".claude", "skills")
            backups = [n for n in os.listdir(skills_dir) if re.match(r"^diu\.bak\.", n)]
            self.assertEqual(len(backups), 1, os.listdir(skills_dir))
            backed_up_marker = os.path.join(skills_dir, backups[0], "marker.txt")
            self.assertTrue(os.path.exists(backed_up_marker))
            with open(backed_up_marker) as f:
                self.assertEqual(f.read(), "do not touch")

    def test_real_claude_md_file_without_force_is_left_alone(self):
        """The common real-world case this feature was built for: a machine
        that already has a real (non-symlink) ~/.claude/CLAUDE.md, same as
        link_item already handles for a real skill directory -- covers a
        FILE target specifically, not just a directory."""
        with tempfile.TemporaryDirectory() as fake_home:
            claude_dir = os.path.join(fake_home, ".claude")
            os.makedirs(claude_dir)
            target = os.path.join(claude_dir, "CLAUDE.md")
            with open(target, "w") as f:
                f.write("my own real rules, do not touch")

            result = run_install(fake_home)

            self.assertIn("skip", result.stdout)
            self.assertFalse(os.path.islink(target))
            with open(target) as f:
                self.assertEqual(f.read(), "my own real rules, do not touch")

    def test_real_claude_md_file_with_force_gets_backed_up_and_replaced(self):
        with tempfile.TemporaryDirectory() as fake_home:
            claude_dir = os.path.join(fake_home, ".claude")
            os.makedirs(claude_dir)
            target = os.path.join(claude_dir, "CLAUDE.md")
            with open(target, "w") as f:
                f.write("my own real rules, do not touch")

            result = run_install(fake_home, args=["--force"])

            self.assertIn("backup", result.stdout)
            self.assertTrue(os.path.islink(target))
            self.assertEqual(os.readlink(target), os.path.join(REPO_ROOT, "CLAUDE.md"))

            backups = [n for n in os.listdir(claude_dir) if re.match(r"^CLAUDE\.md\.bak\.", n)]
            self.assertEqual(len(backups), 1, os.listdir(claude_dir))
            with open(os.path.join(claude_dir, backups[0])) as f:
                self.assertEqual(f.read(), "my own real rules, do not touch")

    def test_wrong_symlink_gets_relinked(self):
        with tempfile.TemporaryDirectory() as fake_home:
            skills_dir = os.path.join(fake_home, ".claude", "skills")
            os.makedirs(skills_dir)
            target = os.path.join(skills_dir, "diu")
            wrong_source = os.path.join(fake_home, "somewhere-else")
            os.makedirs(wrong_source)
            os.symlink(wrong_source, target)

            result = run_install(fake_home)

            self.assertIn("relink", result.stdout)
            self.assertTrue(os.path.islink(target))
            self.assertEqual(os.readlink(target), os.path.join(REPO_ROOT, "skills", "diu"))


class TestCodexAgentsMdMerge(unittest.TestCase):
    def test_preexisting_agents_md_keeps_other_rules(self):
        with tempfile.TemporaryDirectory() as fake_home:
            agents = os.path.join(fake_home, ".codex", "AGENTS.md")
            os.makedirs(os.path.dirname(agents))
            with open(agents, "w") as f:
                f.write("# Evidence rules\n\nKeep me.\n")
            result = run_install(fake_home)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(agents) as f:
                text = f.read()
            self.assertIn("# Evidence rules", text)
            self.assertIn("Keep me.", text)
            self.assertIn("<!-- catstack-draft-pr -->", text)
            self.assertEqual(text.count("<!-- catstack-draft-pr -->"), 1)

    def test_rerun_does_not_duplicate_the_block(self):
        with tempfile.TemporaryDirectory() as fake_home:
            run_install(fake_home)
            second = run_install(fake_home)
            self.assertEqual(second.returncode, 0, second.stderr)
            with open(os.path.join(fake_home, ".codex", "AGENTS.md")) as f:
                text = f.read()
            self.assertEqual(text.count("<!-- catstack-draft-pr -->"), 1)
            self.assertIn("already up to date", second.stdout)


if __name__ == "__main__":
    unittest.main()
