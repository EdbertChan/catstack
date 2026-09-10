#!/usr/bin/env python3
"""Tests for the agent-routing-guard PreToolUse (Agent) hook.

Run: python3 -m unittest discover -s engine/hooks/agent-routing-guard/tests -v

Every fixture under fixtures/ is a whole scenario: whether invoker-cli is on
PATH, what the user's current message says, and the Agent payload. Tests run
the real entrypoint with PATH pointed at a temp directory, so whether the
developer actually has invoker-cli installed never changes a result.
"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse_agent  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

INCIDENT_PROMPT = (
    "Work in your own worktree on the retry-budget fix, run the suite, then commit "
    "and push the branch and open a PR against main. Report the PR number."
)


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def fixture_names() -> list[str]:
    return sorted(n for n in os.listdir(FIXTURE_DIR) if n.endswith(".json"))


class Sandbox:
    """A PATH with or without invoker-cli, plus a transcript to read the
    user's current message from."""

    def __init__(self, invoker_on_path: bool = True) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bin_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin_dir)
        if invoker_on_path:
            self.install_invoker()

    def install_invoker(self) -> str:
        path = os.path.join(self.bin_dir, detect.INVOKER_CLI)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def transcript(self, user_message: str | None, extra_lines: list[str] | None = None) -> str:
        path = os.path.join(self.tmp.name, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "on it"}]}}) + "\n")
            if user_message is not None:
                handle.write(json.dumps({"type": "user", "message": {
                    "role": "user", "content": user_message}}) + "\n")
            for line in extra_lines or []:
                handle.write(line + "\n")
        return path

    def environ(self) -> dict:
        return {"PATH": self.bin_dir, "HOME": self.tmp.name}

    def cleanup(self) -> None:
        self.tmp.cleanup()


def run_entrypoint(payload: dict, environ: dict) -> tuple[bool, str]:
    """(blocked, stderr). Blocked means the hook exited 2, which is how
    Claude Code refuses the tool call."""
    err = io.StringIO()
    out = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with patch.dict(os.environ, environ, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    claude_pretooluse_agent.main()
                except SystemExit as exc:
                    return exc.code == 2, err.getvalue()
    return False, err.getvalue()


class FixtureCase(unittest.TestCase):
    def run_fixture(self, name: str) -> tuple[dict, bool, str]:
        fixture = load_fixture(name)
        box = Sandbox(invoker_on_path=fixture["invoker_on_path"])
        try:
            payload = dict(fixture["payload"])
            payload["transcript_path"] = box.transcript(fixture["user_message"])
            blocked, message = run_entrypoint(payload, box.environ())
        finally:
            box.cleanup()
        return fixture, blocked, message

    def test_every_fixture_is_an_agent_payload_with_a_stated_expectation(self) -> None:
        names = fixture_names()
        self.assertGreaterEqual(len(names), 8, names)
        for name in names:
            fixture = load_fixture(name)
            self.assertEqual(fixture["payload"]["tool_name"], "Agent", name)
            self.assertIn(fixture["expect"], ("blocks", "silent"), name)
            self.assertTrue(fixture["why"].strip(), name)
        self.assertTrue(any(load_fixture(n)["expect"] == "blocks" for n in names))
        self.assertTrue(any(load_fixture(n)["expect"] == "silent" for n in names))

    def test_every_fixture_matches_its_stated_expectation(self) -> None:
        for name in fixture_names():
            with self.subTest(fixture=name):
                fixture, blocked, message = self.run_fixture(name)
                self.assertEqual(blocked, fixture["expect"] == "blocks", f"{name}: {message}")

    def test_the_block_names_the_routing_rule_and_the_invoker_skill(self) -> None:
        _fixture, blocked, message = self.run_fixture("blocks_eight_publishing_subagents.json")
        self.assertTrue(blocked, message)
        self.assertIn("execution routing rule 3", message)
        self.assertIn(detect.ROUTING_SKILL, message)
        self.assertIn("commit", message)
        self.assertIn("push", message)

    def test_the_nested_split_fixture_blocks_once_agent_id_is_removed(self) -> None:
        fixture = load_fixture("silent_nested_subagent_split.json")
        box = Sandbox()
        try:
            payload = dict(fixture["payload"])
            payload["transcript_path"] = box.transcript(fixture["user_message"])
            self.assertFalse(run_entrypoint(payload, box.environ())[0])
            payload.pop("agent_id")
            blocked, message = run_entrypoint(payload, box.environ())
        finally:
            box.cleanup()
        self.assertTrue(blocked, message)

    def test_a_silent_fixture_prints_nothing_at_all(self) -> None:
        _fixture, blocked, message = self.run_fixture("silent_read_only_research.json")
        self.assertFalse(blocked)
        self.assertEqual(message, "")


class VerbCase(unittest.TestCase):
    def test_action_verbs_are_detected(self) -> None:
        cases = {
            "commit and push when the suite is green": ["commit", "push"],
            "open a PR against main": ["open a PR"],
            "make a draft PR for each slice": ["open a PR"],
            "merge it once CI is green": ["merge"],
            "git push -u origin HEAD": ["push"],
            "land the PRs bottom to top": ["open a PR"],
        }
        for prompt, expected in cases.items():
            self.assertEqual(detect.publication_verbs(prompt), expected, prompt)

    def test_the_same_words_as_nouns_do_not_count(self) -> None:
        for prompt in (
            "read the last commit and say what changed",
            "find the commit that broke the build",
            "summarize each PR in the stack",
            "run the suite against the merge commit",
            "which PR introduced this?",
            "report the first push that failed",
        ):
            self.assertEqual(detect.publication_verbs(prompt), [], prompt)

    def test_a_negated_verb_does_not_count(self) -> None:
        for prompt in (
            "READ-ONLY task. Do not edit, create, commit, or push anything.",
            "You must not push or merge anything.",
            "Never commit to main.",
            "Report what you find without pushing.",
            "Neither commit nor push.",
            "Don't open a PR.",
            "Do not under any circumstances push.",
            "No pushing, no merging.",
            "No need to open a PR.",
        ):
            self.assertEqual(detect.publication_verbs(prompt), [], prompt)

    def test_a_hyphen_joined_name_does_not_count(self) -> None:
        for prompt in (
            "Apply principle-push-not-poll to the watcher loop and report the combined findings.",
            "Check whether merge-clone is still called anywhere.",
            "Say whether auto-merge is enabled on the repo.",
            "Read the commit-msg hook and explain it.",
        ):
            self.assertEqual(detect.publication_verbs(prompt), [], prompt)

    def test_a_request_beside_a_negation_is_still_detected(self) -> None:
        cases = {
            "commit and push the fix, then open a PR": ["commit", "push", "open a PR"],
            "Do not change the API. Commit and push the fix.": ["commit", "push"],
            "Don't touch the tests; commit the fix.": ["commit"],
            "Don't forget to commit and push the fix.": ["commit", "push"],
            "Do not stop until you have pushed the branch.": ["push"],
            "Never merge without review, but push the branch.": ["push"],
            "Don't touch the tests, fix it and commit.": ["commit"],
            "Apply principle-push-not-poll, then commit the fix.": ["commit"],
            "Make it a no-op and commit.": ["commit"],
            "Leave no TODOs and commit.": ["commit"],
            "Do not edit docs\ncommit and push": ["commit", "push"],
            "Do not rebase; open a PR against main.": ["open a PR"],
        }
        for prompt, expected in cases.items():
            self.assertEqual(detect.publication_verbs(prompt), expected, prompt)

    def test_a_hyphenated_verb_form_is_still_detected(self) -> None:
        cases = {
            "force-push the branch": ["push"],
            "squash-merge the PR once green": ["merge"],
            "re-push after the rebase": ["push"],
            "git push --force-with-lease": ["push"],
        }
        for prompt, expected in cases.items():
            self.assertEqual(detect.publication_verbs(prompt), expected, prompt)


class OverrideCase(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()

    def tearDown(self) -> None:
        self.box.cleanup()

    def payload(self, transcript: str) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "transcript_path": transcript,
            "tool_input": {"description": "fix", "prompt": INCIDENT_PROMPT},
        }

    def test_override_phrasings_all_allow_the_spawn(self) -> None:
        for message in (
            "do it locally",
            "just do this locally please",
            "don't use invoker",
            "do not use Invoker for this",
            "no invoker, we are debugging",
            "keep it local",
        ):
            transcript = self.box.transcript(message)
            blocked, _ = run_entrypoint(self.payload(transcript), self.box.environ())
            self.assertFalse(blocked, message)

    def test_an_override_quoted_deep_inside_a_paste_does_not_count(self) -> None:
        pasted = "do not use invoker\n" + ("filler log line\n" * 400) + "carry on with the plan"
        transcript = self.box.transcript(pasted)
        blocked, _ = run_entrypoint(self.payload(transcript), self.box.environ())
        self.assertTrue(blocked)

    def test_blocks_when_the_transcript_is_missing(self) -> None:
        payload = self.payload(os.path.join(self.box.tmp.name, "gone.jsonl"))
        blocked, message = run_entrypoint(payload, self.box.environ())
        self.assertTrue(blocked)
        self.assertIn("could not be checked", message)
        self.assertIn(detect.ROUTING_SKILL, message)

    def test_blocks_when_the_payload_carries_no_transcript_path(self) -> None:
        payload = self.payload("")
        payload.pop("transcript_path")
        blocked, message = run_entrypoint(payload, self.box.environ())
        self.assertTrue(blocked)
        self.assertIn("no transcript path", message)

    def test_blocks_when_the_transcript_is_too_large_to_scan(self) -> None:
        transcript = self.box.transcript("do it locally")
        with patch.object(detect, "TRANSCRIPT_SIZE_CAP_BYTES", 4):
            state, reason = detect.override_state(transcript)
        self.assertEqual(state, detect.OVERRIDE_UNCHECKED)
        self.assertIn("scan cap", reason)

    def test_blocks_when_the_transcript_holds_no_user_message(self) -> None:
        transcript = self.box.transcript(None)
        blocked, message = run_entrypoint(self.payload(transcript), self.box.environ())
        self.assertTrue(blocked)
        self.assertIn("no user message", message)

    def test_a_malformed_transcript_line_is_skipped_not_treated_as_the_message(self) -> None:
        transcript = self.box.transcript("do it locally", extra_lines=["{not json", ""])
        blocked, message = run_entrypoint(self.payload(transcript), self.box.environ())
        self.assertFalse(blocked, message)

    def test_an_injected_system_turn_is_not_the_users_message(self) -> None:
        injected = json.dumps({"type": "user", "message": {
            "role": "user", "content": "<task-notification>do it locally</task-notification>"}})
        transcript = self.box.transcript("carry on", extra_lines=[injected])
        blocked, _ = run_entrypoint(self.payload(transcript), self.box.environ())
        self.assertTrue(blocked)


class SilenceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()

    def tearDown(self) -> None:
        self.box.cleanup()

    def test_a_non_agent_tool_is_never_touched(self) -> None:
        payload = {
            "tool_name": "Bash",
            "transcript_path": self.box.transcript("go"),
            "tool_input": {"command": "git commit -am wip", "prompt": INCIDENT_PROMPT},
        }
        blocked, message = run_entrypoint(payload, self.box.environ())
        self.assertFalse(blocked)
        self.assertEqual(message, "")

    def test_an_agent_call_with_no_prompt_is_allowed(self) -> None:
        payload = {
            "tool_name": "Agent",
            "transcript_path": self.box.transcript("go"),
            "tool_input": {"description": "x"},
        }
        self.assertFalse(run_entrypoint(payload, self.box.environ())[0])

    def test_invoker_absent_allows_the_spawn_without_reading_the_transcript(self) -> None:
        box = Sandbox(invoker_on_path=False)
        try:
            payload = {
                "tool_name": "Agent",
                "transcript_path": os.path.join(box.tmp.name, "gone.jsonl"),
                "tool_input": {"prompt": INCIDENT_PROMPT},
            }
            blocked, message = run_entrypoint(payload, box.environ())
        finally:
            box.cleanup()
        self.assertFalse(blocked)
        self.assertEqual(message, "")


class FailOpenCase(unittest.TestCase):
    def test_malformed_stdin_allows_the_spawn(self) -> None:
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_pretooluse_agent.main()
        self.assertEqual(err.getvalue(), "")

    def test_a_detector_error_is_reported_and_fails_open(self) -> None:
        err = io.StringIO()
        payload = {"tool_name": "Agent", "tool_input": {"prompt": INCIDENT_PROMPT}}
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with patch.object(claude_pretooluse_agent, "decide", side_effect=RuntimeError("boom")):
                with redirect_stderr(err):
                    claude_pretooluse_agent.main()
        self.assertIn("check did not run (boom)", err.getvalue())


class InstallerCase(unittest.TestCase):
    def test_the_fragment_is_a_pretooluse_hook_on_the_agent_tool(self) -> None:
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        [entry] = fragment["hooks"]["PreToolUse"]
        self.assertEqual(entry["matcher"], "Agent")
        self.assertEqual(
            entry["hooks"][0]["command"],
            "python3 $HOME/.claude/hooks/agent-routing-guard/claude_pretooluse_agent.py",
        )

    def test_merge_is_idempotent_and_keeps_other_hooks(self) -> None:
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        settings = {"hooks": {"PreToolUse": [
            {"matcher": "Agent", "hooks": [{"type": "command", "command": "python3 other.py"}]}]}}
        settings, changed = install_claude_hook.merge_hook(settings, fragment)
        self.assertTrue(changed)
        settings, changed_again = install_claude_hook.merge_hook(settings, fragment)
        self.assertFalse(changed_again)
        commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertEqual(commands.count("python3 other.py"), 1)
        self.assertEqual(sum(install_claude_hook.MARKER in c for c in commands), 1)


if __name__ == "__main__":
    unittest.main()
