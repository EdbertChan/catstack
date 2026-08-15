#!/usr/bin/env python3
"""Unit tests for claude_stop_check.py and codex_notify.py.

Run: python3 -m unittest discover -s hooks/diu-stop/tests -v
(stdlib unittest only, matches skills/reflect/scripts/tests/test_token_audit.py)

Includes a regression test for the actual incident that motivated this file:
an earlier version of claude.hook.json and codex_notify.py had this
machine's real absolute path (username included) hardcoded in, which would
have broken on any other machine and leaked into git history. See
hooks/diu-stop/README.md's "Verified" table and the aaa4abe commit.
"""
import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import codex_notify  # noqa: E402
import install_claude_hook  # noqa: E402
import install_codex_notify  # noqa: E402


def run_claude_check(stdin_obj):
    buf = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(stdin_obj))):
        with redirect_stdout(buf):
            claude_stop_check.main()
    return buf.getvalue()


def run_codex_notify(argv_tail):
    buf = io.StringIO()
    with patch.object(sys, "argv", ["codex_notify.py"] + argv_tail):
        with redirect_stdout(buf):
            codex_notify.main()
    return buf.getvalue()


class TestClaudeStopCheck(unittest.TestCase):
    def test_under_limit_prints_nothing(self):
        out = run_claude_check({"last_assistant_message": "short reply"})
        self.assertEqual(out, "")

    def test_exactly_at_limit_prints_nothing(self):
        message = " ".join(["word"] * claude_stop_check.WORD_LIMIT)
        out = run_claude_check({"last_assistant_message": message})
        self.assertEqual(out, "")

    def test_over_limit_denies_with_word_count_in_reason(self):
        message = " ".join(["word"] * (claude_stop_check.WORD_LIMIT + 50))
        out = run_claude_check({"last_assistant_message": message})
        payload = json.loads(out)
        hook_out = payload["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "Stop")
        self.assertEqual(hook_out["permissionDecision"], "deny")
        self.assertIn(str(claude_stop_check.WORD_LIMIT + 50), hook_out["permissionDecisionReason"])

    def test_missing_field_treated_as_empty_and_allows(self):
        out = run_claude_check({})
        self.assertEqual(out, "")

    def test_malformed_stdin_json_does_not_crash(self):
        buf = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stdout(buf):
                claude_stop_check.main()  # must not raise
        self.assertEqual(buf.getvalue(), "")


class TestCodexNotify(unittest.TestCase):
    def test_no_argv_prints_nothing(self):
        out = run_codex_notify([])
        self.assertEqual(out, "")

    def test_short_message_prints_nothing(self):
        payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": "short"})
        out = run_codex_notify([payload])
        self.assertEqual(out, "")

    def test_long_message_warns_on_stderr_not_stdout(self):
        message = " ".join(["word"] * (codex_notify.WORD_LIMIT + 20))
        payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": message})
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["codex_notify.py", payload]):
            with redirect_stdout(stdout_buf):
                with patch("sys.stderr", stderr_buf):
                    codex_notify.main()
        self.assertEqual(stdout_buf.getvalue(), "")
        self.assertIn(str(codex_notify.WORD_LIMIT + 20), stderr_buf.getvalue())

    def test_non_agent_turn_complete_type_ignored(self):
        payload = json.dumps({"type": "something-else", "last-assistant-message": "x" * 2000})
        out = run_codex_notify([payload])
        self.assertEqual(out, "")

    def test_malformed_json_payload_does_not_crash(self):
        out = run_codex_notify(["not json"])
        self.assertEqual(out, "")

    def test_chain_command_invoked_with_payload_appended(self):
        payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": "short"})
        with patch.object(sys, "argv", ["codex_notify.py", "/some/chain-binary", "turn-ended", payload]):
            with patch("subprocess.run") as mock_run:
                codex_notify.main()
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        self.assertEqual(called_args, ["/some/chain-binary", "turn-ended", payload])

    def test_chain_failure_does_not_crash_and_check_still_runs(self):
        message = " ".join(["word"] * (codex_notify.WORD_LIMIT + 5))
        payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": message})
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["codex_notify.py", "/broken/binary", payload]):
            with patch("subprocess.run", side_effect=OSError("no such file")):
                with redirect_stdout(stdout_buf):
                    with patch("sys.stderr", stderr_buf):
                        codex_notify.main()  # must not raise
        # both the chain failure and the word-count warning should show up
        self.assertIn("chained notify failed", stderr_buf.getvalue())
        self.assertIn(str(codex_notify.WORD_LIMIT + 5), stderr_buf.getvalue())

    def test_no_chain_args_skips_subprocess(self):
        payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": "short"})
        with patch.object(sys, "argv", ["codex_notify.py", payload]):
            with patch("subprocess.run") as mock_run:
                codex_notify.main()
        mock_run.assert_not_called()


class TestNoHardcodedMachinePaths(unittest.TestCase):
    """Regression test for the actual incident: claude.hook.json's "command"
    and codex_notify.py's old CHAIN_TO constant both had this machine's real
    /Users/<name>/... path baked into a git-tracked file. Guards against
    reintroducing that in any file under hooks/diu-stop/ (this dir), not
    just the two that broke."""

    ABS_PATH_RE = re.compile(r"(?:/Users/|/home/)[^/\s\"']+/")
    # This directory's own tests/ subfolder and __pycache__ don't ship as
    # hook config and are exempt.
    EXEMPT_DIRS = {"tests", "__pycache__"}

    def test_no_real_home_directory_paths_in_committed_files(self):
        offenders = []
        for entry in sorted(os.listdir(HOOKS_DIR)):
            full = os.path.join(HOOKS_DIR, entry)
            if entry in self.EXEMPT_DIRS or not os.path.isfile(full):
                continue
            with open(full, "r", errors="replace") as f:
                text = f.read()
            for match in self.ABS_PATH_RE.finditer(text):
                offenders.append(f"{entry}: {match.group(0)}")
        self.assertEqual(
            offenders,
            [],
            "Found a real-looking absolute home-directory path baked into a "
            "committed hooks/diu-stop file -- use $HOME, a relative path, or "
            "argv/env instead:\n" + "\n".join(offenders),
        )

    def test_no_actual_current_home_dir_string_anywhere(self):
        home = os.path.expanduser("~")
        offenders = []
        for entry in sorted(os.listdir(HOOKS_DIR)):
            full = os.path.join(HOOKS_DIR, entry)
            if entry in self.EXEMPT_DIRS or not os.path.isfile(full):
                continue
            with open(full, "r", errors="replace") as f:
                if home in f.read():
                    offenders.append(entry)
        self.assertEqual(offenders, [], f"Found this machine's home dir ({home}) literally baked into: {offenders}")


class TestMergeClaudeStopHook(unittest.TestCase):
    FRAGMENT = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": "python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py", "timeout": 10}],
                }
            ]
        }
    }

    def test_adds_to_empty_settings(self):
        new_settings, changed = install_claude_hook.merge_stop_hook({}, self.FRAGMENT)
        self.assertTrue(changed)
        self.assertEqual(len(new_settings["hooks"]["Stop"]), 1)
        self.assertIn("claude_stop_check.py", new_settings["hooks"]["Stop"][0]["hooks"][0]["command"])

    def test_preserves_other_settings_keys(self):
        settings = {"model": "sonnet", "theme": "dark"}
        new_settings, _ = install_claude_hook.merge_stop_hook(settings, self.FRAGMENT)
        self.assertEqual(new_settings["model"], "sonnet")
        self.assertEqual(new_settings["theme"], "dark")

    def test_preserves_unrelated_stop_hooks(self):
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "some-other-hook.sh"}]}]}}
        new_settings, changed = install_claude_hook.merge_stop_hook(settings, self.FRAGMENT)
        self.assertTrue(changed)
        commands = [h["command"] for e in new_settings["hooks"]["Stop"] for h in e["hooks"]]
        self.assertIn("some-other-hook.sh", commands)
        self.assertTrue(any("claude_stop_check.py" in c for c in commands))

    def test_rerun_is_idempotent_no_duplicate(self):
        settings, _ = install_claude_hook.merge_stop_hook({}, self.FRAGMENT)
        settings, changed = install_claude_hook.merge_stop_hook(settings, self.FRAGMENT)
        self.assertFalse(changed)
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)

    def test_edit_to_fragment_replaces_stale_entry_not_appends(self):
        settings, _ = install_claude_hook.merge_stop_hook({}, self.FRAGMENT)
        edited_fragment = json.loads(json.dumps(self.FRAGMENT))
        edited_fragment["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 20
        new_settings, changed = install_claude_hook.merge_stop_hook(settings, edited_fragment)
        self.assertTrue(changed)
        self.assertEqual(len(new_settings["hooks"]["Stop"]), 1)
        self.assertEqual(new_settings["hooks"]["Stop"][0]["hooks"][0]["timeout"], 20)


class TestComputeCodexNotifyUpdate(unittest.TestCase):
    SCRIPT_PATH = "/home/x/.codex/hooks/diu-stop/codex_notify.py"

    def test_no_notify_line_inserts_before_first_section(self):
        text = 'model = "gpt-5"\n\n[projects."/x"]\ntrust_level = "trusted"\n'
        new_text, changed, _ = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        self.assertIn(f'notify = ["python3", "{self.SCRIPT_PATH}"]', new_text)
        self.assertLess(new_text.index("notify ="), new_text.index("[projects"))
        self.assertIn('model = "gpt-5"', new_text)

    def test_no_notify_line_no_sections_appends(self):
        text = 'model = "gpt-5"\n'
        new_text, changed, _ = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        self.assertTrue(new_text.rstrip("\n").endswith(f'notify = ["python3", "{self.SCRIPT_PATH}"]'))

    def test_existing_unrelated_notify_gets_chained_not_dropped(self):
        text = 'notify = ["/opt/old-notifier", "turn-ended"]\nmodel = "gpt-5"\n'
        new_text, changed, message = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        self.assertIn("chaining 2 prior arg", message)
        new_notify = json.loads(re.search(r"^notify = (\[.*\])$", new_text, re.MULTILINE).group(1))
        self.assertEqual(new_notify, ["python3", self.SCRIPT_PATH, "/opt/old-notifier", "turn-ended"])
        self.assertIn('model = "gpt-5"', new_text)  # untouched line still present

    def test_already_wired_is_a_noop(self):
        text = f'notify = ["python3", "{self.SCRIPT_PATH}", "/opt/old-notifier"]\n'
        new_text, changed, message = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertFalse(changed)
        self.assertEqual(new_text, text)
        self.assertIn("already wired", message)

    def test_only_the_notify_line_changes(self):
        text = 'a = 1\nnotify = ["/opt/old"]\nb = 2\n'
        new_text, changed, _ = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        lines = new_text.splitlines()
        self.assertIn("a = 1", lines)
        self.assertIn("b = 2", lines)


if __name__ == "__main__":
    unittest.main()
