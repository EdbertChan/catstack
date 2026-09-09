#!/usr/bin/env python3
"""Tests for the ui-input-guard PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/ui-input-guard/tests -v

Fixtures are sanitized commands from a real recording session: AppleScript
keystrokes into Slack, an ffmpeg screen capture, and the wrapper script the
agent actually invoked. The silent set holds the neighbours that must stay
allowed -- a deep link, a geometry read, a still screenshot, and authoring a
driver script.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse_check  # noqa: E402
import detect  # noqa: E402

DRIVE_LINE = (
    "osascript -e 'tell application \"System Events\" to keystroke \"3\"'\n"
)

IOREG_UNLOCKED = '<key>CGSSessionScreenIsLocked</key>\t<false/>'
IOREG_LOCKED = '<key>CGSSessionScreenIsLocked</key>\t<true/>'


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


class FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout


def fake_probe(locked=False, idle_secs=300):
    def run(args, **kwargs):
        if "Root" in args:
            return FakeProc(IOREG_LOCKED if locked else IOREG_UNLOCKED)
        return FakeProc(f'    "HIDIdleTime" = {int(idle_secs * 1_000_000_000)}')
    return run


def materialize(case):
    """Write a fixture's wrapper script to disk; return its directory or None."""
    script = case.get("script")
    if not script:
        return None
    path = script["path"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script["body"])
    return path


def payload(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def run_hook(command, marker_exists=False):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload(command)))):
        with redirect_stderr(err):
            try:
                claude_pretooluse_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


class TestBlocksLiveSessionInput(unittest.TestCase):
    def test_hit_every_fire_fixture_is_detected(self):
        for case in load("commands_fire.json"):
            with self.subTest(label=case["label"]):
                written = materialize(case)
                try:
                    reason, _ = detect.find_reason(case["command"])
                finally:
                    if written and os.path.exists(written):
                        os.unlink(written)
                self.assertEqual(reason, case["reason"])

    def test_hit_blocks_when_no_window_is_open(self):
        case = load("commands_fire.json")[0]
        with tempfile.TemporaryDirectory() as tmp:
            message = detect.decide(
                payload(case["command"]),
                marker=os.path.join(tmp, "absent"),
                platform="darwin", run=fake_probe(),
            )
        self.assertIsNotNone(message)
        self.assertIn("No hands-off window", message)

    def test_hit_blocks_when_the_window_expired(self):
        with tempfile.NamedTemporaryFile(suffix=".marker") as marker:
            stale = lambda: 0  # noqa: E731 - now() far behind the marker's mtime
            message = detect.decide(
                payload(load("commands_fire.json")[1]["command"]),
                marker=marker.name,
                now=lambda: os.stat(marker.name).st_mtime + detect.MAX_WINDOW_AGE_SECS + 60,
                platform="darwin", run=fake_probe(),
            )
            self.assertIsNotNone(stale)
        self.assertIsNotNone(message)
        self.assertIn("expired", message)

    def test_hit_blocks_when_the_screen_is_locked(self):
        with tempfile.NamedTemporaryFile(suffix=".marker") as marker:
            message = detect.decide(
                payload(load("commands_fire.json")[0]["command"]),
                marker=marker.name,
                platform="darwin", run=fake_probe(locked=True),
            )
        self.assertIsNotNone(message)
        self.assertIn("locked", message)

    def test_hit_blocks_while_the_user_is_active(self):
        with tempfile.NamedTemporaryFile(suffix=".marker") as marker:
            message = detect.decide(
                payload(load("commands_fire.json")[0]["command"]),
                marker=marker.name,
                platform="darwin", run=fake_probe(idle_secs=1),
            )
        self.assertIsNotNone(message)
        self.assertIn("was active", message)

    def test_hit_exit_code_is_2_with_guidance(self):
        code, err = run_hook(load("commands_fire.json")[2]["command"])
        self.assertEqual(code, 2)
        self.assertIn("ui-input-guard", err)
        self.assertIn("hands-off window", err)

    def test_hit_names_the_wrapper_script_as_the_source(self):
        case = load("commands_fire.json")[-1]
        written = materialize(case)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                message = detect.decide(
                    payload(case["command"]),
                    marker=os.path.join(tmp, "absent"),
                    platform="darwin", run=fake_probe(),
                )
        finally:
            if written and os.path.exists(written):
                os.unlink(written)
        self.assertIsNotNone(message)
        self.assertIn("the script it runs", message)


class TestLargeAndIndirectScripts(unittest.TestCase):
    def _staged(self, body):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "drive.sh")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def test_hit_mechanism_past_the_old_size_cap_is_still_found(self):
        padding = "# filler line to push the real call far into the file\n" * 4000
        path = self._staged("#!/usr/bin/env bash\n" + padding + DRIVE_LINE)
        self.assertGreater(os.path.getsize(path), 64 * 1024)
        reason, _ = detect.scan_file(path)
        self.assertEqual(reason, "AppleScript System Events input")

    def test_hit_wrapper_reached_through_a_shell_variable(self):
        path = self._staged("#!/usr/bin/env bash\n" + DRIVE_LINE)
        directory = os.path.dirname(path)
        command = f"S={directory}; $S/drive.sh \"3\""
        with tempfile.TemporaryDirectory() as tmp:
            message = detect.decide(payload(command), marker=os.path.join(tmp, "absent"), platform="darwin", run=fake_probe())
        self.assertIsNotNone(message)
        self.assertIn("the script it runs", message)

    def test_hit_unreadable_script_is_refused_not_assumed_clean(self):
        path = self._staged("#!/usr/bin/env bash\necho hello\n")
        with tempfile.TemporaryDirectory() as tmp:
            message = detect.decide(
                payload(f"bash {path}"),
                marker=os.path.join(tmp, "absent"),
                platform="darwin", run=fake_probe(),
                getsize=lambda _p: detect.MAX_SCRIPT_BYTES + 1,
            )
        self.assertIsNotNone(message)
        self.assertIn("could not be read to the end", message)
        self.assertIn("scan ceiling", message)

    def test_no_hit_large_script_with_no_mechanism(self):
        path = self._staged("#!/usr/bin/env bash\n" + ("echo padding\n" * 20000))
        self.assertGreater(os.path.getsize(path), 64 * 1024)
        self.assertEqual(detect.scan_file(path), (None, None))
        self.assertIsNone(detect.decide(payload(f"bash {path}"), marker="/nonexistent/marker"))

    def test_no_hit_unscannable_script_inside_a_granted_window(self):
        path = self._staged("#!/usr/bin/env bash\necho hello\n")
        with tempfile.NamedTemporaryFile(suffix=".marker") as marker:
            message = detect.decide(
                payload(f"bash {path}"),
                marker=marker.name,
                platform="darwin", run=fake_probe(idle_secs=120),
                getsize=lambda _p: detect.MAX_SCRIPT_BYTES + 1,
            )
        self.assertIsNone(message)


class TestAllowsEverythingElse(unittest.TestCase):
    def test_no_hit_on_any_silent_fixture(self):
        for case in load("commands_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.decide(payload(case["command"]), marker="/nonexistent/marker"))

    def test_allows_input_inside_a_granted_window(self):
        with tempfile.NamedTemporaryFile(suffix=".marker") as marker:
            message = detect.decide(
                payload(load("commands_fire.json")[0]["command"]),
                marker=marker.name,
                platform="darwin", run=fake_probe(locked=False, idle_secs=120),
            )
        self.assertIsNone(message)

    def test_allows_a_non_bash_payload_without_a_command(self):
        self.assertIsNone(detect.decide({"tool_name": "Read", "tool_input": {"file_path": "/x"}}))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_pretooluse_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_no_hit_probes_are_skipped_off_macos(self):
        self.assertIsNone(detect.screen_is_locked(platform="linux"))
        self.assertIsNone(detect.idle_seconds(platform="linux"))

    def test_fails_open_when_probes_raise(self):
        def boom(*args, **kwargs):
            raise OSError("no ioreg here")

        self.assertIsNone(detect.screen_is_locked(run=boom, platform="darwin"))
        self.assertIsNone(detect.idle_seconds(run=boom, platform="darwin"))

    def test_no_hit_search_pattern_is_not_a_pipe(self):
        command = 'git grep -n -iE "keystroke|System Events" origin/main | head -3'
        self.assertTrue(detect.is_read_only_pipeline(command))
        self.assertEqual(detect.find_reason(command), ("", ""))

    def test_shell_heredoc_still_counts_as_execution(self):
        command = "osascript <<'AS'\ntell application \"System Events\" to keystroke \"3\"\nAS"
        self.assertEqual(detect.find_reason(command)[0], "AppleScript System Events input")

    def test_write_heredoc_body_is_not_treated_as_execution(self):
        command = load("commands_silent.json")[-2]["command"]
        self.assertNotIn("keystroke", detect.strip_write_heredocs(command))


if __name__ == "__main__":
    unittest.main()
