#!/usr/bin/env python3
"""Regression tests for the cat-mode-default UserPromptSubmit hook.

Every fixture under fixtures/ is a full scenario: process environment,
optional repo-root .env content, the hook payload, and whether the hook is
expected to fire or stay silent. Tests run the real entrypoint with a fake
HOME and a fake repo so nothing reads the developer's own .env files.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

REAL_PROMPT = "why isnt the 72,000,000 transaction recorded in my sheet?"


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def fixture_names() -> list[str]:
    return sorted(n for n in os.listdir(FIXTURE_DIR) if n.endswith(".json"))


class Sandbox:
    """Fake HOME with an installed cat-mode skill and a fake git repo."""

    def __init__(self, install_skill: bool = True) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "sub", "dir"))
        self.cwd = os.path.join(self.repo, "sub", "dir")
        self.skill_path = os.path.join(self.home, detect.SKILL_RELPATH)
        os.makedirs(os.path.dirname(self.skill_path))
        if install_skill:
            with open(self.skill_path, "w", encoding="utf-8") as handle:
                handle.write("---\nname: cat-mode\n---\n")

    def write_repo_env(self, text: str) -> str:
        path = os.path.join(self.repo, ".env")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_home_env(self, text: str) -> str:
        path = os.path.join(self.home, ".catstack.env")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def environ(self, extra: dict | None = None) -> dict:
        env = {"HOME": self.home, "PATH": os.environ.get("PATH", "")}
        env.update(extra or {})
        return env

    def cleanup(self) -> None:
        self.tmp.cleanup()


def run_entrypoint(payload: dict, environ: dict, home: str) -> str:
    out = io.StringIO()
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with patch.dict(os.environ, environ, clear=True):
            with patch.object(os.path, "expanduser", lambda p: p.replace("~", home, 1)):
                with redirect_stdout(out), redirect_stderr(err):
                    claude_prompt_submit.main()
    return out.getvalue()


def injected_context(stdout: str) -> str | None:
    if not stdout.strip():
        return None
    return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()

    def tearDown(self) -> None:
        self.box.cleanup()

    def run_fixture(self, name: str) -> tuple[dict, str | None]:
        fixture = load_fixture(name)
        if fixture.get("env_file"):
            self.box.write_repo_env(fixture["env_file"])
        payload = dict(fixture["payload"])
        payload.setdefault("cwd", self.box.cwd)
        stdout = run_entrypoint(payload, self.box.environ(fixture["environ"]), self.box.home)
        return fixture, injected_context(stdout)

    def test_every_fixture_declares_expect(self) -> None:
        for name in fixture_names():
            self.assertIn(load_fixture(name)["expect"], ("fires", "silent"), name)

    def test_fires_on_investigation_with_env_flag(self) -> None:
        fixture, context = self.run_fixture("fires_env_flag_investigation.json")
        self.assertEqual(fixture["payload"]["prompt"], REAL_PROMPT)
        self.assertIsNotNone(context)
        self.assertIn("CATSTACK_CAT_MODE_DEFAULT=1", context)
        self.assertIn(self.box.skill_path, context)

    def test_fires_on_dotenv_file_only(self) -> None:
        fixture, context = self.run_fixture("fires_dotenv_file_only.json")
        self.assertEqual(fixture["environ"], {})
        self.assertIsNotNone(context)
        self.assertNotIn("OTHER_KEY", context)
        self.assertNotIn("secret-value", context)

    def test_silent_when_flag_off(self) -> None:
        fixture, context = self.run_fixture("silent_flag_off.json")
        self.assertEqual(fixture["payload"]["prompt"], REAL_PROMPT)
        self.assertIsNone(context)

    def test_fires_on_one_word_ack(self) -> None:
        _fixture, context = self.run_fixture("silent_ack_ok.json")
        self.assertIsNotNone(context)

    def test_silent_when_user_typed_cat_mode(self) -> None:
        _fixture, context = self.run_fixture("silent_typed_cat_mode.json")
        self.assertIsNone(context)

    def test_effectiveness_prompt_matrix(self) -> None:
        prompts = (
            "ok",
            "thanks",
            "yes do it",
            "go ahead",
            "investigate why the build fails on main",
            "/cat-mode fix this",
        )
        for prompt in prompts:
            payload = {"prompt": prompt, "cwd": self.box.cwd}
            on = injected_context(run_entrypoint(payload, self.box.environ({detect.FLAG: "1"}), self.box.home))
            off = injected_context(run_entrypoint(payload, self.box.environ({detect.FLAG: "0"}), self.box.home))
            if prompt == "/cat-mode fix this":
                self.assertIsNone(on, prompt)
            else:
                self.assertIsNotNone(on, prompt)
                self.assertIn("read and apply", on)
            self.assertIsNone(off, prompt)


class FlagResolutionCase(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()

    def tearDown(self) -> None:
        self.box.cleanup()

    def test_process_env_wins_over_every_file(self) -> None:
        self.box.write_repo_env("CATSTACK_CAT_MODE_DEFAULT=1\n")
        self.box.write_home_env("CATSTACK_CAT_MODE_DEFAULT=1\n")
        env = self.box.environ({detect.FLAG: "0"})
        self.assertFalse(detect.flag_on(env, self.box.cwd, self.box.home))

    def test_explicit_env_file_is_checked_before_repo_root(self) -> None:
        explicit = os.path.join(self.box.tmp.name, "custom.env")
        with open(explicit, "w", encoding="utf-8") as handle:
            handle.write("CATSTACK_CAT_MODE_DEFAULT=0\n")
        self.box.write_repo_env("CATSTACK_CAT_MODE_DEFAULT=1\n")
        env = self.box.environ({detect.ENV_FILE_VAR: explicit})
        self.assertEqual(detect.env_file_candidates(env, self.box.cwd, self.box.home)[0], explicit)
        self.assertFalse(detect.flag_on(env, self.box.cwd, self.box.home))

    def test_repo_root_env_is_checked_before_home_env(self) -> None:
        self.box.write_repo_env("CATSTACK_CAT_MODE_DEFAULT=0\n")
        self.box.write_home_env("CATSTACK_CAT_MODE_DEFAULT=1\n")
        self.assertFalse(detect.flag_on(self.box.environ(), self.box.cwd, self.box.home))

    def test_home_env_fires_when_repo_env_is_silent_on_the_key(self) -> None:
        self.box.write_repo_env("UNRELATED=1\n")
        self.box.write_home_env("CATSTACK_CAT_MODE_DEFAULT=1\n")
        self.assertTrue(detect.flag_on(self.box.environ(), self.box.cwd, self.box.home))

    def test_lookup_order_is_explicit_then_repo_then_home(self) -> None:
        env = self.box.environ({detect.ENV_FILE_VAR: "~/explicit.env"})
        candidates = detect.env_file_candidates(env, self.box.cwd, self.box.home)
        self.assertEqual(candidates, [
            os.path.expanduser("~/explicit.env"),
            os.path.join(self.box.repo, ".env"),
            os.path.join(self.box.home, ".catstack.env"),
        ])

    def test_no_repo_root_skips_the_repo_candidate(self) -> None:
        outside = os.path.join(self.box.tmp.name, "loose")
        os.makedirs(outside)
        candidates = detect.env_file_candidates(self.box.environ(), outside, self.box.home)
        self.assertEqual(candidates, [os.path.join(self.box.home, ".catstack.env")])

    def test_env_file_parser_reads_only_the_flag(self) -> None:
        path = self.box.write_repo_env(
            "# comment\nexport OTHER='x'\nCATSTACK_CAT_MODE_DEFAULT=\"1\"\nTRAILING=1\n"
        )
        self.assertEqual(detect.read_flag_from_file(path), "1")
        self.assertIsNone(detect.read_flag_from_file(path, "MISSING"))

    def test_env_file_with_shell_syntax_is_never_executed(self) -> None:
        marker = os.path.join(self.box.tmp.name, "executed")
        path = self.box.write_repo_env(f"$(touch {marker})\nCATSTACK_CAT_MODE_DEFAULT=1\n")
        self.assertEqual(detect.read_flag_from_file(path), "1")
        self.assertFalse(os.path.exists(marker))

    def test_missing_file_is_silent(self) -> None:
        self.assertIsNone(detect.read_flag_from_file(os.path.join(self.box.tmp.name, "nope.env")))

    def test_false_values_stay_off(self) -> None:
        for value in ("0", "false", "no", "off", ""):
            self.assertFalse(detect.flag_on(self.box.environ({detect.FLAG: value}), self.box.cwd, self.box.home), value)

    def test_true_values_turn_on(self) -> None:
        for value in ("1", "true", "YES", "on"):
            self.assertTrue(detect.flag_on(self.box.environ({detect.FLAG: value}), self.box.cwd, self.box.home), value)


class PromptCommandCase(unittest.TestCase):
    def test_silent_when_cat_mode_typed_anywhere(self) -> None:
        self.assertTrue(detect.typed_cat_mode("/cat-mode fix it"))
        self.assertTrue(detect.typed_cat_mode("please /cat-mode fix it"))
        self.assertFalse(detect.typed_cat_mode("cat-mode is a skill"))
        self.assertFalse(detect.typed_cat_mode("/cat-modes"))


class MissingSkillCase(unittest.TestCase):
    def test_flags_missing_install_instead_of_dead_path(self) -> None:
        box = Sandbox(install_skill=False)
        try:
            payload = {"prompt": REAL_PROMPT, "cwd": box.cwd}
            context = injected_context(run_entrypoint(payload, box.environ({detect.FLAG: "1"}), box.home))
            self.assertIsNotNone(context)
            self.assertIn("not installed", context)
            self.assertIn("install.sh", context)
        finally:
            box.cleanup()


class FailOpenCase(unittest.TestCase):
    def test_malformed_stdin_prints_nothing(self) -> None:
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stdout(out):
                claude_prompt_submit.main()
        self.assertEqual(out.getvalue(), "")

    def test_detect_exception_prints_nothing(self) -> None:
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps({"prompt": REAL_PROMPT}))):
            with patch.object(claude_prompt_submit, "decide", side_effect=RuntimeError("boom")):
                with redirect_stdout(out):
                    claude_prompt_submit.main()
        self.assertEqual(out.getvalue(), "")


class InstallerCase(unittest.TestCase):
    def test_merge_adds_entry_once_and_keeps_others(self) -> None:
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        other = {"hooks": [{"type": "command", "command": "python3 other.py"}]}
        settings = {"model": "x", "hooks": {"UserPromptSubmit": [other]}}
        merged, changed = install_claude_hook.merge_hook(settings, fragment)
        self.assertTrue(changed)
        self.assertEqual(merged["model"], "x")
        commands = [h["command"] for e in merged["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
        self.assertEqual(commands.count("python3 other.py"), 1)
        self.assertEqual(sum(install_claude_hook.MARKER in c for c in commands), 1)
        again, changed_again = install_claude_hook.merge_hook(merged, fragment)
        self.assertFalse(changed_again)
        self.assertEqual(again, merged)

    def test_fragment_names_the_home_relative_entrypoint(self) -> None:
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        command = fragment["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertEqual(command, "python3 $HOME/.claude/hooks/cat-mode-default/claude_prompt_submit.py")


if __name__ == "__main__":
    unittest.main()
