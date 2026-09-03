import os
import sys
import unittest

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claude_stop_check  # noqa: E402
from test_hooks import run_claude_check  # noqa: E402

LONG_FILLER = " ".join(["word"] * (claude_stop_check.WORD_LIMIT + 20))

FIX_FIXTURES = [
    {
        "name": "over_word_limit",
        "broken": LONG_FILLER,
        "fixed": "Short compliant reply under the word limit.",
    },
    {
        "name": "bare_opener_confirmed",
        "broken": "Confirmed -- the bug is in the retry loop.",
        "fixed": "Confirmed via `git log -1 abc123` -- the bug is in the retry loop.",
    },
    {
        "name": "causal_closer_because",
        "broken": "The UI is empty because send never executed.",
        "fixed": "The UI is empty because `planning-chat-send` never executed.",
    },
    {
        "name": "hedge_i_think_happened",
        "broken": "I think the deploy happened around 2am, so that's why the build is stale.",
        "fixed": "I think the deploy happened, confirmed via `git log -1 --format=%ai`.",
    },
    {
        "name": "unverified_marker_resolved_by_verifying",
        "broken": "UNVERIFIED: the deploy caused the outage.",
        "fixed": "Confirmed via `git log -1` -- the deploy caused the outage.",
    },
]

KNOWN_DOUBLE_BLOCKS = [
    {
        "name": "hedge_hedged_into_unverified_still_needs_a_second_look",
        "broken": "I think the deploy happened around 2am, so that's why the build is stale.",
        "hedged": "UNVERIFIED: I think the deploy happened around 2am, so that's why the build is stale.",
        "reason": (
            "Prefixing UNVERIFIED: silences the hedge/causal/opener checks, "
            "but the unverified-marker check still fires -- a claim that was "
            "hedged into 'I don't know' should still prompt one more nudge "
            "to go verify, not become a silent free pass."
        ),
    },
]


class TestFixDoesNotTripAnotherCheck(unittest.TestCase):
    """For each known trigger, the message a compliant rewrite would
    produce must not itself get blocked by any check -- otherwise fixing
    one finding just bounces you into another before the same-turn retry
    escape (`stop_hook_active`) even applies."""

    def test_broken_fixtures_are_actually_blocked(self):
        for fixture in FIX_FIXTURES:
            with self.subTest(fixture=fixture["name"]):
                blocked, _ = run_claude_check({"last_assistant_message": fixture["broken"]})
                self.assertTrue(blocked, f"fixture {fixture['name']!r} 'broken' message was not blocked")

    def test_fixed_fixtures_are_not_blocked_by_any_check(self):
        for fixture in FIX_FIXTURES:
            with self.subTest(fixture=fixture["name"]):
                blocked, err = run_claude_check({"last_assistant_message": fixture["fixed"]})
                self.assertFalse(
                    blocked,
                    f"fixture {fixture['name']!r} 'fixed' message still blocked: {err}",
                )


class TestKnownDoubleBlocksResolveOnRetry(unittest.TestCase):
    """Some fixes deliberately still trip a second check (see
    KNOWN_DOUBLE_BLOCKS). That's fine as long as the shared
    `stop_hook_active` escape still releases it on the very next attempt --
    otherwise it's a real two-hook cycle, not a documented double-block."""

    def test_hedged_message_still_blocks_once(self):
        for case in KNOWN_DOUBLE_BLOCKS:
            with self.subTest(case=case["name"]):
                blocked, err = run_claude_check({"last_assistant_message": case["hedged"]})
                self.assertTrue(blocked, f"{case['name']}: expected the documented double-block to fire")
                self.assertIn("UNVERIFIED", err)

    def test_hedged_message_passes_on_stop_hook_active_retry(self):
        for case in KNOWN_DOUBLE_BLOCKS:
            with self.subTest(case=case["name"]):
                blocked, err = run_claude_check({
                    "last_assistant_message": case["hedged"],
                    "stop_hook_active": True,
                })
                self.assertFalse(blocked, f"{case['name']}: retry did not escape via stop_hook_active")
                self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
