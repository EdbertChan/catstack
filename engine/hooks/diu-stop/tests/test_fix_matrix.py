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
        "fixed": "Confirmed via `pytest -k retry`, which printed `1 failed` -- the bug is in the retry loop.",
    },
    {
        "name": "causal_closer_because",
        "broken": "The UI is empty because send never executed.",
        "fixed": "The UI is empty because `planning-chat-send` never executed: the app log says `planning-chat-send: not found`.",
    },
    {
        "name": "hedge_i_think_happened",
        "broken": "I think the deploy happened around 2am, so that's why the build is stale.",
        "fixed": "I think the deploy happened, confirmed via `deploy status` printing `SUCCESS`.",
    },
    {
        "name": "legacy_marker_resolved_by_verifying",
        "broken": "UNVERIFIED: the deploy caused the outage.",
        "fixed": "Confirmed via the deploy log line `PoolTimeoutError: connection pool exhausted` -- the deploy caused the outage.",
    },
    {
        "name": "legacy_marker_resolved_by_naming_the_blocker",
        "broken": "UNVERIFIED: the deploy caused the outage.",
        "fixed": (
            "The deploy caused the outage. "
            "{{CAT-UNVERIFIED: the deploy caused it -- cannot verify: the log host is offline}}"
        ),
    },
]

KNOWN_DOUBLE_BLOCKS = [
    {
        "name": "hedge_tagged_without_a_blocker_still_needs_a_second_look",
        "broken": "I think the deploy happened around 2am, so that's why the build is stale.",
        "hedged": (
            "I think the deploy happened around 2am, so that's why the build is stale. "
            "{{CAT-UNVERIFIED: the 2am deploy}}"
        ),
        "resolved": (
            "I think the deploy happened around 2am, so that's why the build is stale. "
            "{{CAT-UNVERIFIED: the 2am deploy -- cannot verify: the deploy log is rotated out}}"
        ),
        "reason": (
            "A tag that names no blocker does not excuse its paragraph, so the "
            "hedge check still fires and the malformed-tag check fires beside "
            "it. Two complaints about the same sentence is correct here: the "
            "rewrite that fixes both is to name the blocker or go check."
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


class TestKnownDoubleBlocksResolveByNamingTheBlocker(unittest.TestCase):
    """Some fixes deliberately still trip a second check (see
    KNOWN_DOUBLE_BLOCKS). `stop_hook_active` no longer releases those -- it
    only stops the word-count check, so a rewrite cannot smuggle a new
    unchecked claim through on the strength of the first block. What has to
    exist instead is a move that ends the turn: naming the blocker in the
    tag. Without one of these passing, the evidence checks would be an
    unbounded loop."""

    def test_hedged_message_still_blocks_once(self):
        for case in KNOWN_DOUBLE_BLOCKS:
            with self.subTest(case=case["name"]):
                blocked, err = run_claude_check({"last_assistant_message": case["hedged"]})
                self.assertTrue(blocked, f"{case['name']}: expected the documented double-block to fire")
                self.assertIn("CAT-UNVERIFIED", err)

    def test_hedged_message_still_blocks_on_retry(self):
        for case in KNOWN_DOUBLE_BLOCKS:
            with self.subTest(case=case["name"]):
                blocked, _ = run_claude_check({
                    "last_assistant_message": case["hedged"],
                    "stop_hook_active": True,
                })
                self.assertTrue(blocked, f"{case['name']}: retry must not excuse an unchecked claim")

    def test_naming_the_blocker_ends_the_turn(self):
        for case in KNOWN_DOUBLE_BLOCKS:
            with self.subTest(case=case["name"]):
                for retry in (False, True):
                    blocked, err = run_claude_check({
                        "last_assistant_message": case["resolved"],
                        "stop_hook_active": retry,
                    })
                    self.assertFalse(blocked, f"{case['name']}: no legal move ends the turn: {err}")
                    self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
