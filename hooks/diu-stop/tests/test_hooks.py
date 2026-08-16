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

import claude_prompt_reminder  # noqa: E402
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


def run_prompt_reminder(stdin_obj):
    buf = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(stdin_obj))):
        with redirect_stdout(buf):
            claude_prompt_reminder.main()
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


class TestClaudePromptReminder(unittest.TestCase):
    def test_emits_additional_context_for_user_prompt_submit(self):
        out = run_prompt_reminder({"session_id": "abc123"})
        payload = json.loads(out)
        hook_out = payload["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "UserPromptSubmit")
        self.assertIn("diu", hook_out["additionalContext"])

    def test_reminder_mentions_the_core_rules(self):
        out = run_prompt_reminder({"session_id": "abc123"})
        reminder = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        for phrase in ("lead with the outcome", "no preamble", "ELI5", "cap lists at 5"):
            self.assertIn(phrase, reminder)

    def test_reminder_is_short(self):
        # This fires every single turn -- it must stay a nudge, not a copy
        # of the whole skill, or it becomes exactly the kind of bloat diu
        # tells the model to cut.
        out = run_prompt_reminder({"session_id": "abc123"})
        reminder = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(reminder.split()), 60)

    def test_missing_fields_still_emits_reminder(self):
        # Unlike claude_stop_check, this hook's output never depends on
        # stdin's content -- it always reminds, regardless of payload shape.
        out = run_prompt_reminder({})
        self.assertNotEqual(out, "")

    def test_malformed_stdin_json_does_not_crash(self):
        buf = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stdout(buf):
                claude_prompt_reminder.main()  # must not raise
        self.assertEqual(buf.getvalue(), "")


class TestUnverifiedClaimCheck(unittest.TestCase):
    """Regression tests for the three real unverified claims a session let
    through before self-correcting or being corrected by the user (see
    module docstring). Each `reproduces_the_incident` test asserts the OLD
    behavior (word-count-only check) would have let it through, then asserts
    the new check catches it."""

    def test_reproduces_the_incident_confirmed_root_cause_with_no_evidence(self):
        message = "Confirmed, with a complete timeline and root cause. The owner process was in a severe, sustained crash loop."
        out = run_claude_check({"last_assistant_message": message})
        payload = json.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("confirmed", payload["hookSpecificOutput"]["permissionDecisionReason"].lower())

    def test_reproduces_the_incident_never_pushed_claim(self):
        message = "This should work now -- the fix exists, but got stranded before it ever reached GitHub."
        out = run_claude_check({"last_assistant_message": message})
        payload = json.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_confirmed_as_bare_opener_is_flagged(self):
        out = run_claude_check({"last_assistant_message": "Confirmed -- the bug is in the retry loop."})
        payload = json.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_confirmed_with_markdown_bold_opener_is_flagged(self):
        out = run_claude_check({"last_assistant_message": "**Confirmed**, this is the root cause."})
        payload = json.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_unconditional_banned_phrase_flagged_even_mid_sentence(self):
        out = run_claude_check({"last_assistant_message": "I checked the logic and this fixes it completely."})
        payload = json.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_verified_mid_sentence_with_code_evidence_is_allowed(self):
        # The exact false-positive this check must avoid: "verified" used
        # legitimately, backed by real evidence (a command/output shown).
        message = "I verified this by running `git log -1 4df97a3d0c` and the date matches."
        out = run_claude_check({"last_assistant_message": message})
        self.assertEqual(out, "")

    def test_confirmed_opener_with_evidence_marker_is_allowed(self):
        message = "Confirmed via `gh api repos/.../git/refs/...` -- the branch is really there."
        out = run_claude_check({"last_assistant_message": message})
        self.assertEqual(out, "")

    def test_unverified_prefix_is_always_allowed(self):
        message = "UNVERIFIED: confirmed the crash loop, but I have not checked the actual log source yet."
        out = run_claude_check({"last_assistant_message": message})
        self.assertEqual(out, "")

    def test_ordinary_message_without_banned_language_passes(self):
        out = run_claude_check({"last_assistant_message": "I'll check the logs next and report back."})
        self.assertEqual(out, "")

    def test_word_count_violation_takes_priority_when_both_present(self):
        message = "Confirmed. " + " ".join(["word"] * (claude_stop_check.WORD_LIMIT + 10))
        out = run_claude_check({"last_assistant_message": message})
        payload = json.loads(out)
        self.assertIn("diu", payload["hookSpecificOutput"]["permissionDecisionReason"])


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
    HOOK_TYPE = "Stop"
    MARKER = "claude_stop_check.py"
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
        new_settings, changed = install_claude_hook.merge_hook({}, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        self.assertTrue(changed)
        self.assertEqual(len(new_settings["hooks"]["Stop"]), 1)
        self.assertIn("claude_stop_check.py", new_settings["hooks"]["Stop"][0]["hooks"][0]["command"])

    def test_preserves_other_settings_keys(self):
        settings = {"model": "sonnet", "theme": "dark"}
        new_settings, _ = install_claude_hook.merge_hook(settings, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        self.assertEqual(new_settings["model"], "sonnet")
        self.assertEqual(new_settings["theme"], "dark")

    def test_preserves_unrelated_stop_hooks(self):
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "some-other-hook.sh"}]}]}}
        new_settings, changed = install_claude_hook.merge_hook(settings, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        self.assertTrue(changed)
        commands = [h["command"] for e in new_settings["hooks"]["Stop"] for h in e["hooks"]]
        self.assertIn("some-other-hook.sh", commands)
        self.assertTrue(any("claude_stop_check.py" in c for c in commands))

    def test_rerun_is_idempotent_no_duplicate(self):
        settings, _ = install_claude_hook.merge_hook({}, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        settings, changed = install_claude_hook.merge_hook(settings, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        self.assertFalse(changed)
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)

    def test_edit_to_fragment_replaces_stale_entry_not_appends(self):
        settings, _ = install_claude_hook.merge_hook({}, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        edited_fragment = json.loads(json.dumps(self.FRAGMENT))
        edited_fragment["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 20
        new_settings, changed = install_claude_hook.merge_hook(settings, self.HOOK_TYPE, self.MARKER, edited_fragment)
        self.assertTrue(changed)
        self.assertEqual(len(new_settings["hooks"]["Stop"]), 1)
        self.assertEqual(new_settings["hooks"]["Stop"][0]["hooks"][0]["timeout"], 20)


class TestMergeUserPromptSubmitHook(unittest.TestCase):
    HOOK_TYPE = "UserPromptSubmit"
    MARKER = "claude_prompt_reminder.py"
    FRAGMENT = {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [{"type": "command", "command": "python3 $HOME/.claude/hooks/diu-stop/claude_prompt_reminder.py", "timeout": 10}],
                }
            ]
        }
    }

    def test_adds_to_empty_settings(self):
        new_settings, changed = install_claude_hook.merge_hook({}, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        self.assertTrue(changed)
        self.assertEqual(len(new_settings["hooks"]["UserPromptSubmit"]), 1)
        self.assertIn("claude_prompt_reminder.py", new_settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"])

    def test_coexists_with_stop_hook_in_same_settings(self):
        stop_fragment = TestMergeClaudeStopHook.FRAGMENT
        settings, _ = install_claude_hook.merge_hook({}, "Stop", "claude_stop_check.py", stop_fragment)
        settings, changed = install_claude_hook.merge_hook(settings, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        self.assertTrue(changed)
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)
        self.assertEqual(len(settings["hooks"]["UserPromptSubmit"]), 1)

    def test_rerun_is_idempotent_no_duplicate(self):
        settings, _ = install_claude_hook.merge_hook({}, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        settings, changed = install_claude_hook.merge_hook(settings, self.HOOK_TYPE, self.MARKER, self.FRAGMENT)
        self.assertFalse(changed)
        self.assertEqual(len(settings["hooks"]["UserPromptSubmit"]), 1)


class TestInstallClaudeHookMainRunsBothSpecs(unittest.TestCase):
    def test_hook_specs_cover_stop_and_user_prompt_submit(self):
        hook_types = [spec[0] for spec in install_claude_hook.HOOK_SPECS]
        self.assertEqual(sorted(hook_types), ["Stop", "UserPromptSubmit"])

    def test_fragment_files_referenced_by_hook_specs_exist(self):
        for _, _, fragment_path in install_claude_hook.HOOK_SPECS:
            self.assertTrue(os.path.exists(fragment_path), fragment_path)


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
