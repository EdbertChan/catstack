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
    "The Linear-sync worker is shipped; unit tests pass "
    "and it registers in the settings panel, but I have not seen a real ticket write. "
    "{{CAT-UNVERIFIED: the live ticket write -- cannot verify: no Linear credentials in this sandbox}}",
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
        self.assertIn("{{CAT-UNVERIFIED", err)

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

    def test_retry_still_fires_on_an_unproven_ship_claim(self):
        self.assertIsNotNone(detect.decide({
            "last_assistant_message": REAL_FIRE[0], "stop_hook_active": True,
        }))

    def test_naming_the_blocker_ends_the_turn_on_retry(self):
        tagged = REAL_FIRE[0] + (
            " {{CAT-UNVERIFIED: the live path -- cannot verify: the deploy host is unreachable}}"
        )
        for retry in (False, True):
            self.assertIsNone(detect.decide({
                "last_assistant_message": tagged, "stop_hook_active": retry,
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


SESSION_CLAIM_SHAPES = [
    "Proof: yes, and it caught a real bug. The scorer, copied standalone to DO1, "
    "scores both heavy sessions from the rollout log.",
    "Real tick proven end to end. Duplicate probe cancelled.",
    "Proven, on DO1, against the real sessions. All commands run this turn.",
    "All three asks are done. PR 12006 merged at 21:15:22 UTC. Workers on DO1 "
    "are picking the new code up.",
    "The nightly pipeline is working end to end again.",
    "Three things confirmed working that were broken an hour ago: nightly cut, "
    "the fleet model pin, and the session miner on DO1.",
]

SESSION_NON_CLAIMS = [
    "I'll check the deployed timeout value in the worker config.",
    "Actively working on the nightly bump script now.",
    "This is not deployed to production yet.",
    "Reading the repair plan builder locally while, on DO1, enabling the e2e toggle.",
]

LIVE_RECEIPTS = [
    "Real tick proven end to end on DO1: filed wf-1788934611938-7.",
    "The nightly pipeline is working end to end again -- "
    "https://github.com/EdbertChan/catstack/actions/runs/34259072426 is green.",
    "Proven on DO1: the cut published daily-20260909.",
    "All three asks are done. Delegated to live owner; the follow-up landed.",
]

PR_REFERENCE_ONLY = [
    "All three asks are done. PR #12027 fixes all three, with a six-check "
    "self-test and this live proof on DO1.",
    "The nightly pipeline is working end to end again -- see #12023.",
]


class TestSessionClaimShapes(unittest.TestCase):
    def test_fires_on_each_claim_shape_the_session_used(self):
        for text in SESSION_CLAIM_SHAPES:
            with self.subTest(text=text[:60]):
                self.assertTrue(detect.claims_live_ship(text))
                self.assertIsNotNone(detect.decide({"last_assistant_message": text}))

    def test_silent_on_near_miss_progress_talk(self):
        for text in SESSION_NON_CLAIMS:
            with self.subTest(text=text[:60]):
                self.assertFalse(detect.claims_live_ship(text))
                self.assertIsNone(detect.decide({"last_assistant_message": text}))


class TestLiveReceiptVsPrReference(unittest.TestCase):
    def test_silent_when_a_live_output_receipt_is_present(self):
        for text in LIVE_RECEIPTS:
            with self.subTest(text=text[:60]):
                self.assertTrue(detect.has_live_receipt(text))
                self.assertIsNone(detect.decide({"last_assistant_message": text}))

    def test_fires_when_the_only_id_is_the_changes_own_pr_number(self):
        for text in PR_REFERENCE_ONLY:
            with self.subTest(text=text[:60]):
                self.assertFalse(detect.has_live_receipt(text))
                self.assertFalse(detect.has_evidence(text))
                self.assertIsNotNone(detect.decide({"last_assistant_message": text}))


INCIDENT_SHIP_MESSAGE = (
    'Shipped. Both PRs are live with full bodies: [#12927](https://github.com/Neko-Catpital-Labs/Invoker/pull/12927) (base `master`) and [#12928](https://github.com/Neko-Catpital-Labs/Invoker/pull/12928) (stacked on it).\n'
    '\n'
    'The popups are stopped on your machine, and 586 stale test checkouts were patched so a retry refuses instead of opening windows.\n'
    '\n'
    "**Waiting on:** the reflect pass. It's checking whether this same complaint happened before. If it did, the rule says the fix belongs in your always-on working-style rules — the `automate-me` skill, which rewrites the habit so you don't have to catch it again — rather than another one-off patch. Estimate: back by **00:41 PDT**; a fallback wake is armed, and it may land sooner.\n"
    '\n'
    '**Still open:**\n'
    '1. `packages/app/e2e/fixtures/electron-app.ts` has no hidden-window path on macOS.\n'
    "2. Invoker's default pool still includes your Mac, so these jobs still get sent here — they just refuse now.\n"
    "3. Your catstack hooks are stale (checkout sits on `install-hook-open-probe`), so merged hook fixes aren't live here.\n")

INCIDENT_STACK_MESSAGE = (
    'Stack is live and correctly formed:\n'
    '\n'
    '| PR | Title | Base |\n'
    '|---|---|---|\n'
    '| [#12927](https://github.com/Neko-Catpital-Labs/Invoker/pull/12927) | `[Headless E2E Guard](1) Refuse Electron e2e on an interactive desktop` | `master` |\n'
    "| [#12928](https://github.com/Neko-Catpital-Labs/Invoker/pull/12928) | `[Headless E2E Guard](2) Gate the e2e shell launchers on a virtual display` | PR #12927's branch |\n"
    '\n'
    'Both carry the full section schema; both bodies passed `validate-pr-body-local.mjs`.\n'
    '\n'
    '**Done on your machine:** popups stopped, 586 stale worktree copies patched so a retry refuses too.\n'
    '\n'
    '**Still open, carried forward:**\n'
    '1. `/reflect` pass still running — checking whether this complaint recurred before. If yes, it routes to `automate-me`, not another one-off.\n'
    '2. `packages/app/e2e/fixtures/electron-app.ts` still has no hidden-window path on macOS.\n'
    "3. Invoker's default pool still includes your Mac, so these jobs still get *dispatched* here — they just refuse now.\n"
    "4. Your catstack hooks are stale (checkout sits on `install-hook-open-probe`), so merged hook fixes aren't live.\n")

INCIDENT_COMPLIANT_REWRITE = (
    "I ran the e2e I'd skipped. Exact incident command on the fixed branch:\n"
    '\n'
    '```\n'
    '40-playwright-app.sh: refusing to run Electron e2e without a virtual display.\n'
    'SUITE_EXIT=1\n'
    '```\n'
    'A watcher sampling every 0.5s alongside it recorded **zero Electron windows**.\n'
    '\n'
    "**I was wrong about the cause.** The guard didn't drift — a codex agent **deleted it**. The launcher called `xvfb-run` unconditionally and hard-failed; the agent rewrote it to run headed instead, then ran 9.3 minutes of windows on your desktop.\n"
    '\n'
    'So I wired `pnpm run check:all` to run the gate test — dropping the gate from any launcher now fails CI.\n'
    '\n'
    "Also wrong earlier: I told you your catstack hooks were stale. They aren't (`git rev-list --count HEAD..origin/main` = 0). Ignore that.\n"
    '\n'
    '#12927 merged; #12928 open and refreshed.\n'
    '\n'
    'Back at **01:05 PDT** with the second reflect and `automate-me`.\n')

LOCAL_SURFACE_FIRE = [
    INCIDENT_SHIP_MESSAGE,
    INCIDENT_STACK_MESSAGE,
    "Shipped — the popups are stopped on your Mac.",
    "Done. The Electron windows no longer open on your desktop.",
    "The Playwright shard is working end to end now on your laptop.",
    "All of it is done: the e2e guard is live in your session.",
    "The guard is shipped and nothing opens on the user's screen any more.",
]

LOCAL_SURFACE_SILENT = [
    INCIDENT_COMPLIANT_REWRITE,
    "I'm about to run the Playwright suite on your machine; nothing has run yet.",
    "Shipped the headless guard on your machine (`8262dc40a6` on master).",
    "The e2e shard is working end to end on your Mac -- "
    "https://github.com/EdbertChan/catstack/actions/runs/34259072426 is green.",
]

IDIOM_ONLY_SILENT = [
    "Done. The parser now works end-to-end.",
    "All of it is done: the e2e suite is green.",
    "The retry path is working end to end.",
    "Confirmed end-to-end: the date formatter handles leap years.",
    "Shipped the e2e coverage for the tokenizer.",
]


class TestLocalSurfaceIsALiveSurface(unittest.TestCase):
    """The 2026 incident: an agent ran a CI Playwright shard on the user's own
    Mac, opened Electron windows on their desktop for minutes, then said
    "Shipped ... the popups are stopped on your machine" with only two links to
    its own PRs. The gate ran on that turn and stayed silent, because its noun
    list held only external services and a PR link counted as live evidence.
    Both halves have to change; either alone leaves the message silent."""

    def test_fires_on_each_local_surface_claim(self):
        for text in LOCAL_SURFACE_FIRE:
            with self.subTest(text=text[:60]):
                self.assertTrue(detect.claims_live_ship(text))
                self.assertIsNotNone(detect.decide({"last_assistant_message": text}))

    def test_the_incident_message_names_a_live_noun(self):
        self.assertTrue(detect.LIVE_NOUN_RE.search(INCIDENT_SHIP_MESSAGE))
        self.assertTrue(detect.LIVE_NOUN_RE.search(INCIDENT_STACK_MESSAGE))

    def test_silent_on_each_local_surface_near_neighbour(self):
        for text in LOCAL_SURFACE_SILENT:
            with self.subTest(text=text[:60]):
                self.assertIsNone(detect.decide({"last_assistant_message": text}))

    def test_the_compliant_rewrite_carries_its_own_receipt(self):
        """The real follow-up message: same work, same local surface, but the
        suite's own output pasted. It makes no bare ship claim and it shows a
        receipt, so neither half of the gate has anything to say."""
        self.assertFalse(detect.claims_live_ship(INCIDENT_COMPLIANT_REWRITE))
        self.assertTrue(detect.has_evidence(INCIDENT_COMPLIANT_REWRITE))
        for retry in (False, True):
            self.assertIsNone(detect.decide({
                "last_assistant_message": INCIDENT_COMPLIANT_REWRITE,
                "stop_hook_active": retry,
            }))

    def test_the_blocked_message_plus_its_receipt_stops_blocking(self):
        """Fix/re-trigger pair: the message the gate blocks, and the same
        message once the real run's output is pasted into it, which must not
        trip this or any other check in the hook."""
        blocked = INCIDENT_SHIP_MESSAGE
        fixed = INCIDENT_SHIP_MESSAGE + (
            "\n\n```\n40-playwright-app.sh: refusing to run Electron e2e "
            "without a virtual display.\nSUITE_EXIT=1\n```\n"
        )
        self.assertIsNotNone(detect.decide({"last_assistant_message": blocked}))
        for retry in (False, True):
            self.assertIsNone(detect.decide({
                "last_assistant_message": fixed, "stop_hook_active": retry,
            }))

    def test_silent_when_only_the_idiom_names_the_surface(self):
        """`working end-to-end` and `confirmed end-to-end` are already claim
        phrases. If the same words also counted as the live noun, every one of
        those claims would sit permanently on top of a surface and the
        two-part check would collapse to one part -- a unit-suite done-claim
        would be blocked for showing no live evidence it never needed."""
        for text in IDIOM_ONLY_SILENT:
            with self.subTest(text=text[:60]):
                self.assertIsNone(detect.LIVE_NOUN_RE.search(text))
                self.assertIsNone(detect.decide({"last_assistant_message": text}))

    def test_a_claim_phrase_never_doubles_as_its_own_live_noun(self):
        """The general shape of the bug above: no claim phrase may consist
        entirely of live nouns, or matching it proves both halves at once."""
        for phrase in ("working end-to-end", "confirmed end-to-end",
                       "now works", "fully fixed", "done and shipped"):
            with self.subTest(phrase=phrase):
                self.assertTrue(detect.CLAIM_RE.search(phrase))
                stripped = detect.LIVE_NOUN_RE.sub(" ", phrase).strip()
                self.assertTrue(stripped, f"{phrase!r} is entirely live nouns")

    def test_block_message_names_the_users_own_surface(self):
        feedback = detect.decide({"last_assistant_message": INCIDENT_SHIP_MESSAGE})
        self.assertIn("own machine, session, or screen", feedback)


class TestOwnPrLinkIsNotLiveEvidence(unittest.TestCase):
    """The block message already said the PR number of this change does not
    prove the live path ran. A link to that same PR is the same claim in
    another spelling, so the evidence scan has to decline it too."""

    def test_a_pr_link_alone_is_not_evidence(self):
        self.assertFalse(detect.has_evidence(INCIDENT_SHIP_MESSAGE))
        self.assertFalse(detect.has_evidence(INCIDENT_STACK_MESSAGE))

    def test_the_strip_covers_only_the_link_span(self):
        text = (
            "Shipped on your machine. PR: "
            "https://github.com/Neko-Catpital-Labs/Invoker/pull/12927 "
            "and the live run ended `EXIT_CODE=0`."
        )
        self.assertTrue(detect.has_evidence(text))
        self.assertIsNone(detect.decide({"last_assistant_message": text}))

    def test_a_non_pr_url_is_still_evidence(self):
        text = (
            "The e2e guard is live on your Mac -- "
            "https://github.com/EdbertChan/catstack/actions/runs/34259072426"
        )
        self.assertTrue(detect.has_live_receipt(text))
        self.assertTrue(detect.has_evidence(text))
        self.assertIsNone(detect.decide({"last_assistant_message": text}))

    def test_tagging_the_blocker_still_ends_the_turn(self):
        tagged = INCIDENT_SHIP_MESSAGE + (
            "\n\n{{CAT-UNVERIFIED: the popups are stopped -- cannot verify: "
            "the suite cannot run headless on this host}}"
        )
        self.assertIsNone(detect.decide({"last_assistant_message": tagged}))


if __name__ == "__main__":
    unittest.main()


class TestSubagentTranscript(unittest.TestCase):
    """Under SubagentStop, `transcript_path` is the parent session's file and
    `agent_transcript_path` is the subagent's own; the evidence scan must
    read the subagent's."""

    def payload(self, parent_commands, agent_commands):
        parent = transcript_with_commands(parent_commands)
        agent = transcript_with_commands(agent_commands)
        self.addCleanup(os.unlink, parent)
        self.addCleanup(os.unlink, agent)
        return {
            "hook_event_name": "SubagentStop",
            "agent_id": "a0231adb57400d820",
            "transcript_path": parent,
            "agent_transcript_path": agent,
            "last_assistant_message": REAL_FIRE[0],
        }

    def test_fires_when_only_the_parent_ran_the_live_command(self):
        code, err = run_claude(self.payload(["ssh do1 'systemctl status slack-manager'"], ["npm test"]))
        self.assertEqual(code, 2)
        self.assertIn("prove-it-ship-gate", err)

    def test_silent_when_the_subagent_itself_ran_the_live_command(self):
        code, err = run_claude(self.payload(["npm test"], ["ssh do1 'systemctl status slack-manager'"]))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
