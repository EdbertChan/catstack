#!/usr/bin/env python3
"""Regression tests for the cat-mode-default PreToolUse (Agent) companion.

UserPromptSubmit never fires for a subagent, so the Agent tool's prompt is
the only surface the default can ride on. Fixtures named agent_*.json under
fixtures/ each carry the environment and the PreToolUse payload; tests run
the real entrypoint with a fake HOME so nothing reads the developer's own
.env files.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claude_pretooluse_agent  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402
from test_hooks import Sandbox, fixture_names, load_fixture  # noqa: E402

REAL_AGENT_PROMPT = (
    "You are the reflect-apply agent for the hidden_stock repo. Work ONLY inside the git "
    "worktree .worktrees/reflect-coverage (branch reflect/coverage): apply the Accepted items "
    "from the reflect pass, run the full test suite, and open a PR with make-pr. Never merge. "
    "Report back under 300 words with the PR URL and the test pass lines."
)


def run_entrypoint(payload: dict, environ: dict, home: str) -> str:
    out = io.StringIO()
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with patch.dict(os.environ, environ, clear=True):
            with patch.object(os.path, "expanduser", lambda p: p.replace("~", home, 1)):
                with redirect_stdout(out), redirect_stderr(err):
                    claude_pretooluse_agent.main()
    return out.getvalue()


def updated_input(stdout: str) -> dict | None:
    if not stdout.strip():
        return None
    body = json.loads(stdout)["hookSpecificOutput"]
    assert body["hookEventName"] == "PreToolUse", body
    return body["updatedInput"]


class AgentFixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()

    def tearDown(self) -> None:
        self.box.cleanup()

    def run_fixture(self, name: str) -> tuple[dict, dict | None]:
        fixture = load_fixture(name)
        if fixture.get("env_file"):
            self.box.write_repo_env(fixture["env_file"])
        payload = dict(fixture["payload"])
        payload.setdefault("cwd", self.box.cwd)
        stdout = run_entrypoint(payload, self.box.environ(fixture["environ"]), self.box.home)
        return fixture, updated_input(stdout)

    def test_every_agent_fixture_targets_the_agent_tool(self) -> None:
        names = [n for n in fixture_names() if n.startswith("agent_")]
        self.assertEqual(len(names), 3, names)
        for name in names:
            fixture = load_fixture(name)
            self.assertEqual(fixture["payload"]["tool_name"], "Agent", name)
            self.assertIn(fixture["expect"], ("fires", "silent"), name)

    def test_fires_on_plain_agent_prompt_with_flag_on(self) -> None:
        fixture, updated = self.run_fixture("agent_fires_flag_on_plain_prompt.json")
        self.assertIsNotNone(updated)
        original = fixture["payload"]["tool_input"]
        first_line, _, rest = updated["prompt"].partition("\n\n")
        self.assertEqual(first_line, f"cat-mode default is on: read and apply {self.box.skill_path} before starting.")
        self.assertEqual(rest, original["prompt"])
        self.assertEqual(updated["description"], original["description"])
        self.assertEqual(updated["subagent_type"], original["subagent_type"])
        self.assertEqual(set(updated), set(original))

    def test_silent_when_flag_off(self) -> None:
        _fixture, updated = self.run_fixture("agent_silent_flag_off.json")
        self.assertIsNone(updated)

    def test_silent_when_prompt_already_mentions_cat_mode(self) -> None:
        fixture, updated = self.run_fixture("agent_silent_prompt_mentions_cat_mode.json")
        self.assertIn("cat-mode", fixture["payload"]["tool_input"]["prompt"])
        self.assertIsNone(updated)

    def test_effectiveness_real_session_agent_prompt_flag_on_vs_off(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "cwd": self.box.cwd,
            "tool_input": {"description": "Apply reflect items: hidden_stock", "prompt": REAL_AGENT_PROMPT},
        }
        on = updated_input(run_entrypoint(payload, self.box.environ({detect.FLAG: "1"}), self.box.home))
        off = updated_input(run_entrypoint(payload, self.box.environ(), self.box.home))
        self.assertIsNotNone(on)
        self.assertTrue(on["prompt"].startswith("cat-mode default is on: read and apply "))
        self.assertIn(self.box.skill_path, on["prompt"].splitlines()[0])
        self.assertTrue(on["prompt"].endswith(REAL_AGENT_PROMPT))
        self.assertIsNone(off)

    def test_silent_for_a_non_agent_tool_even_with_flag_on(self) -> None:
        payload = {"tool_name": "Bash", "cwd": self.box.cwd, "tool_input": {"command": "ls", "prompt": "x"}}
        self.assertIsNone(updated_input(run_entrypoint(payload, self.box.environ({detect.FLAG: "1"}), self.box.home)))

    def test_silent_for_an_agent_call_with_no_prompt(self) -> None:
        payload = {"tool_name": "Agent", "cwd": self.box.cwd, "tool_input": {"description": "x"}}
        self.assertIsNone(updated_input(run_entrypoint(payload, self.box.environ({detect.FLAG: "1"}), self.box.home)))

    def test_repo_dotenv_alone_fires_for_agent_prompts_too(self) -> None:
        self.box.write_repo_env("CATSTACK_CAT_MODE_DEFAULT=1\n")
        payload = {"tool_name": "Agent", "cwd": self.box.cwd, "tool_input": {"prompt": REAL_AGENT_PROMPT}}
        self.assertIsNotNone(updated_input(run_entrypoint(payload, self.box.environ(), self.box.home)))

    def test_not_installed_line_when_skill_is_missing(self) -> None:
        box = Sandbox(install_skill=False)
        try:
            payload = {"tool_name": "Agent", "cwd": box.cwd, "tool_input": {"prompt": REAL_AGENT_PROMPT}}
            updated = updated_input(run_entrypoint(payload, box.environ({detect.FLAG: "1"}), box.home))
            self.assertIsNotNone(updated)
            self.assertIn("not installed", updated["prompt"].splitlines()[0])
        finally:
            box.cleanup()


class MentionCase(unittest.TestCase):
    def test_any_mention_counts_not_only_a_typed_command(self) -> None:
        for prompt in ("/cat-mode fix it", "read the cat-mode skill first", "apply Cat-Mode conventions"):
            self.assertTrue(detect.mentions_cat_mode(prompt), prompt)

    def test_unrelated_prompt_does_not_count(self) -> None:
        for prompt in ("fix the chart", "the cat sat on the mat", ""):
            self.assertFalse(detect.mentions_cat_mode(prompt), prompt)


class FailOpenCase(unittest.TestCase):
    def test_malformed_stdin_prints_nothing(self) -> None:
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stdout(out):
                claude_pretooluse_agent.main()
        self.assertEqual(out.getvalue(), "")

    def test_detect_exception_prints_nothing(self) -> None:
        out = io.StringIO()
        payload = {"tool_name": "Agent", "tool_input": {"prompt": "x"}}
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with patch.object(claude_pretooluse_agent, "agent_updated_input", side_effect=RuntimeError("boom")):
                with redirect_stdout(out):
                    claude_pretooluse_agent.main()
        self.assertEqual(out.getvalue(), "")


class InstallerCase(unittest.TestCase):
    def test_agent_fragment_is_a_pretooluse_hook_on_the_agent_tool(self) -> None:
        with open(install_claude_hook.AGENT_FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        [entry] = fragment["hooks"]["PreToolUse"]
        self.assertEqual(entry["matcher"], "Agent")
        self.assertEqual(entry["hooks"][0]["command"], "python3 $HOME/.claude/hooks/cat-mode-default/claude_pretooluse_agent.py")

    def test_merge_adds_both_events_once_and_is_idempotent(self) -> None:
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 other.py"}]}]}}
        for hook_type, marker, fragment_path in install_claude_hook.HOOK_SPECS:
            with open(fragment_path, encoding="utf-8") as handle:
                fragment = json.load(handle)
            settings, changed = install_claude_hook.merge_hook(settings, fragment, hook_type, marker)
            self.assertTrue(changed, hook_type)
            settings, changed_again = install_claude_hook.merge_hook(settings, fragment, hook_type, marker)
            self.assertFalse(changed_again, hook_type)
        pretool = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertEqual(pretool.count("python3 other.py"), 1)
        self.assertEqual(sum(install_claude_hook.AGENT_MARKER in c for c in pretool), 1)
        prompt = [h["command"] for e in settings["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
        self.assertEqual(sum(install_claude_hook.MARKER in c for c in prompt), 1)


if __name__ == "__main__":
    unittest.main()
