import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "_sdk")
sys.path.insert(0, HOOKS_DIR)
sys.path.insert(0, SDK_DIR)

import detect  # noqa: E402
from finding import Finding  # noqa: E402
from render import render  # noqa: E402


def launch(session="s1", tool="Agent", description="work", tool_use_id="u1"):
    return {
        "tool_name": tool,
        "tool_input": {"description": description},
        "session_id": session,
        "tool_use_id": tool_use_id,
    }


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_installer():
    path = os.path.join(HOOKS_DIR, "install_claude_hook.py")
    spec = importlib.util.spec_from_file_location("agent_launch_guard_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAgentLaunchGuard(unittest.TestCase):
    def run_detection(self, event, budget=None, now=100.0, ledger=None, babysit=None):
        environment = {detect.BUDGET_ENV: budget} if budget is not None else {}
        if babysit is not None:
            environment[detect.BABYSIT_FLAG] = babysit
        if ledger is not None:
            environment[detect.LEDGER_ENV] = ledger
        with patch.dict(os.environ, environment, clear=True):
            return detect.detect(event, now=now)

    def test_flag_off_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            self.assertEqual(self.run_detection(launch(), ledger=path), [])
            self.assertFalse(os.path.exists(path))

    def test_under_cap_logs_launch_without_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            self.assertEqual(self.run_detection(launch(), "2:600", ledger=path), [])
            self.assertEqual(len(rows(path)), 1)

    def test_over_cap_emits_exactly_one_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            findings = [self.run_detection(launch(tool_use_id=f"u{i}"), "2:600", ledger=path) for i in range(4)]
            self.assertEqual([len(item) for item in findings], [0, 0, 1, 0])
            self.assertEqual(findings[2][0].rule_id, detect.RULE_ID)

    def test_window_expiry_prunes_old_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            self.assertEqual(self.run_detection(launch(tool_use_id="u1"), "3:10", now=0, ledger=path), [])
            self.assertEqual(self.run_detection(launch(tool_use_id="u2"), "3:10", now=1, ledger=path), [])
            self.assertEqual(self.run_detection(launch(tool_use_id="u3"), "3:10", now=2, ledger=path), [])
            self.assertEqual(self.run_detection(launch(tool_use_id="u4"), "3:10", now=20, ledger=path), [])
            self.assertEqual(len(rows(path)), 1)

    def test_unparseable_env_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            self.assertEqual(self.run_detection(launch(), "many:seconds", ledger=path), [])
            self.assertFalse(os.path.exists(path))

    def test_unwritable_ledger_fails_open_with_logged_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            stderr = io.StringIO()
            with patch.object(detect, "_write_rows", side_effect=OSError("read only")), contextlib.redirect_stderr(stderr):
                findings = self.run_detection(launch(), "1:600", ledger=path)
            self.assertEqual(findings, [])
            self.assertIn("ledger failure", stderr.getvalue())

    def test_non_agent_tools_are_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            self.assertEqual(self.run_detection(launch(tool="Bash"), "1:600", ledger=path), [])
            self.assertFalse(os.path.exists(path))

    def test_babysit_prompt_injects_updated_input(self):
        event = launch(description="Watch the merge queue and rebase until green")
        findings = self.run_detection(event, babysit="1")
        self.assertEqual(len(findings), 1)
        updated = findings[0].output["updatedInput"]
        self.assertEqual(updated["description"].count(event["tool_input"]["description"]), 1)
        self.assertTrue(updated["description"].endswith(event["tool_input"]["description"]))
        self.assertIn(detect.FOLD_SCRIPT, updated["description"])

    def test_babysit_non_match_is_untouched(self):
        event = launch(description="Implement the parser and add unit tests")
        self.assertEqual(self.run_detection(event, babysit="1"), [])

    def test_babysit_flag_off_is_silent(self):
        event = launch(description="Monitor the merge queue")
        self.assertEqual(self.run_detection(event, babysit="off"), [])

    def test_babysit_prefix_is_idempotent(self):
        description = f"{detect.BABYSIT_PREFIX}\n\nWatch the merge queue"
        event = launch(description=description)
        self.assertEqual(self.run_detection(event, babysit="1"), [])

    def test_babysit_incident_replay_fires(self):
        event = launch(
            session="9c8136a8",
            description="Babysit the PR stack: watch statusCheckRollup, rebase failures, and land the merge queue when ready",
        )
        findings = self.run_detection(event, babysit="1")
        self.assertEqual(len(findings), 1)
        self.assertIn("state-artifact ledger", findings[0].output["updatedInput"]["description"])

    def test_step_one_rate_warning_still_fires_with_babysit_detector(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            findings = self.run_detection(
                launch(description="Watch the merge queue", tool_use_id="u1"),
                "1:600",
                ledger=path,
                babysit="1",
            )
            self.assertEqual({finding.rule_id for finding in findings}, {detect.BABYSIT_RULE_ID})
            findings = self.run_detection(
                launch(description="Watch the merge queue", tool_use_id="u2"),
                "1:600",
                ledger=path,
                babysit="1",
            )
            self.assertEqual(
                {finding.rule_id for finding in findings},
                {detect.RULE_ID, detect.BABYSIT_RULE_ID},
            )

    def test_sanitized_incident_burst_warns_on_crossing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            findings = [
                self.run_detection(launch(session="incident", tool_use_id=f"u{i}"), "10:300", now=i, ledger=path)
                for i in range(14)
            ]
            self.assertEqual(sum(bool(item) for item in findings), 1)
            self.assertEqual(len(findings[10]), 1)

    def test_warn_render_has_no_mutation_or_deny(self):
        finding = Finding("rule", "session:s1", "warning", "evidence")
        stdout, stderr, exit_code = render("claude", "PreToolUse", "warn", [finding])
        body = json.loads(stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(exit_code, 0)
        self.assertNotIn("updatedInput", body)
        self.assertNotIn("deny", body)

    def test_install_merge_replaces_only_our_entry(self):
        installer = load_installer()
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}, {"hooks": [{"command": installer.MARKER}]}]}}
        changed = installer.merge_hook(settings, {"hooks": {"PreToolUse": [{"matcher": "Agent", "hooks": [{"command": "agent-launch-guard/claude_pretooluse.py"}]}]}})
        self.assertTrue(changed)
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 2)
        self.assertEqual(settings["hooks"]["PreToolUse"][0]["matcher"], "Bash")

    def test_manifest_targets_installed_claude_hook(self):
        with open(os.path.join(HOOKS_DIR, "claude.hook.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        command = manifest["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("$HOME/.claude/hooks/agent-launch-guard/claude_pretooluse.py", command)


if __name__ == "__main__":
    unittest.main()
