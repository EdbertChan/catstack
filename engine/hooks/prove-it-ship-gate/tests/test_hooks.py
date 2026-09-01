#!/usr/bin/env python3
"""Tests for the prove-it-ship-gate Stop hook.

Run: python3 -m unittest discover -s engine/hooks/prove-it-ship-gate/tests -v

Fixture texts are verbatim assistant messages mined from this machine's
~/.claude/projects transcripts on 2026-09-01 (Invoker sessions), plus the
skill's own fires/stays_silent examples. The positive cases are the exact
shape the incident had: a ship/done claim about live work with only
narrative or fixture evidence.
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

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


def transcript_with_commands(commands):
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "ship it"}})]
    for cmd in commands:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}
            ]},
        }))
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return tmp.name


# --- real messages: should FIRE (claim + live noun, no chaseable evidence) ---
REAL_FIRE = [
    # skill's incident fixture
    "The Linear-sync worker is done and shipped — it passed its unit tests and "
    "shows up registered in the settings panel UI.",
    # Invoker session, 2026-08: deploy claim with no sha/exit code/URL
    "Confirmed the duplicate-close worker is already deployed but has no signal "
    "for this \"same title as an already-merged PR\" case — that's the real gap. "
    "Building a safe, comment-only flag for it.",
    # Invoker session: bare landed-and-deployed header
    "Confirmed — the contracts dist was freshly built by required-builds.sh itself, "
    "not my manual patch. The full pipeline is self-sufficient now.\n\n"
    "**Everything's landed and deployed:**",
    # Invoker session: production sweep summary with prose-only proof
    "Deployed upstream/master to Digital Ocean 1, rebuilt all packages, restarted "
    "the slack-manager service — confirmed live and running.",
]

# --- real messages: should stay SILENT ---
REAL_SILENT = [
    # skill's stays_silent fixture: done, but no live side effect
    "I fixed the typo in the README and updated the local CHANGELOG entry — done.",
    # local-only test work with a backticked path, no live noun
    "The bet-accounting task is done: `backend/tests/predictions_betting_test.py` "
    "(new, 6 tests) all pass, covering success, insufficient credits, and a "
    "concurrent same-user race.",
    # deploy claim WITH sha + exit code + timestamp (chaseable evidence)
    "Yes — the DO1 deploy finished successfully.\n\n- Log ends: `DO1 deploy complete`, "
    "`sha=7a9f91ca49c234c3122440ee713bdbb456c986e4`, `EXIT_CODE=0`\n- Slack bot "
    "restarted and came back up: `MainPID=348256`, `ActiveEnterTimestamp=Thu "
    "2026-08-27 19:40:49 UTC`\n\nThat build is live on DigitalOcean 1 now.",
    # merged + deployed WITH PR numbers, sha, and a Linear ticket id
    "1. All 3 fix PRs merged (#11212, #11213, #11214).\n2. DO1 deployed and running "
    "the fully-fixed code (`8262dc40a6`).\n3. Linear ticket **INV-284** filed for the "
    "deeper architecture cleanup.",
    # explicit escape hatch
    "UNVERIFIED: live path — the Linear-sync worker is shipped; unit tests pass "
    "and it registers in the settings panel, but I have not seen a real ticket write.",
    # backtest false positives (2026-09-01): progress talk and adjectives
    "Yes — DO1 (the production server) is actively working on it right now, checked "
    "a couple minutes ago. Most PRs are stuck — blocked mainly by a failing check.",
    "DO1 is up and booting (11s in, actively working). Given the deployed timeout is "
    "still 300s (bump PR not merged yet) it may still hit the wall once.",
    "Shorter recap: Fix built (not deployed): the planning agent is added and "
    "registered, 3 tests pass, full suite still running on the production box.",
    # status update, no ship claim
    "Status so far, while the deploy finishes in the background: DO1 deploy is "
    "running now (fetched master, deps installed, packages building). I won't claim "
    "it's done until I see that.",
]


class TestDetectFires(unittest.TestCase):
    def test_fires_on_each_real_unproven_ship_claim(self):
        for text in REAL_FIRE:
            with self.subTest(text=text[:60]):
                self.assertTrue(detect.claims_live_ship(text))
                self.assertFalse(detect.has_evidence(text))
                self.assertIsNotNone(detect.decide({"last_assistant_message": text}))

    def test_hook_blocks_with_exit_2_and_guidance(self):
        code, err = run_claude({"last_assistant_message": REAL_FIRE[0]})
        self.assertEqual(code, 2)
        self.assertIn("UNVERIFIED: live path", err)

    def test_fires_when_only_fixture_tests_ran_this_turn(self):
        path = transcript_with_commands(["python3 -m pytest packages/app -q", "npm test"])
        try:
            self.assertIsNotNone(detect.decide({
                "last_assistant_message": REAL_FIRE[0], "transcript_path": path,
            }))
        finally:
            os.unlink(path)


class TestDetectStaysSilent(unittest.TestCase):
    def test_silent_on_each_real_clean_message(self):
        for text in REAL_SILENT:
            with self.subTest(text=text[:60]):
                self.assertIsNone(detect.decide({"last_assistant_message": text}))

    def test_silent_when_a_live_command_ran_this_turn(self):
        path = transcript_with_commands(["ssh do1 'systemctl status slack-manager'"])
        try:
            self.assertIsNone(detect.decide({
                "last_assistant_message": REAL_FIRE[0], "transcript_path": path,
            }))
        finally:
            os.unlink(path)

    def test_silent_when_stop_hook_active(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": REAL_FIRE[0], "stop_hook_active": True,
        }))

    def test_fails_open_on_unreadable_transcript(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": REAL_FIRE[0], "transcript_path": "/nonexistent/x.jsonl",
        }))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
