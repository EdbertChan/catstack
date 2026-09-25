import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import detect


def payload(command, *, subagent=True, tool="Bash", agent="a4b7b959ce73515c9", session="s-1"):
    data = {"tool_name": tool, "tool_input": {"command": command}}
    if session is not None:
        data["session_id"] = session
    if subagent:
        data["subagent_id"] = agent
    return data


LIVE = lambda: 0
DOWN = lambda: 1
TIMEOUT = lambda: None


class PublishingActs(unittest.TestCase):
    def test_real_session_commands_are_acts(self):
        cases = {
            "git push -q -u origin HEAD": "git push",
            "git push --force-with-lease origin 7fbbd80:refs/heads/experiment/wf-1/repair": "git push",
            "gh pr create -R EdbertChan/catstack --fill": "gh pr create",
            "gh pr merge 439 -R EdbertChan/catstack --squash --match-head-commit 70b29a7": "gh pr merge",
            "mergify stack push": "mergify stack push",
            "node scripts/create-pr.mjs --title x --base master --body-file /tmp/b.md": "create-pr.mjs",
            "node scripts/safe-stack-push.mjs --execute": "safe-stack-push.mjs",
            "gh api -X POST repos/o/r/pulls -f title=x": "gh api pull-request write",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(detect.publishing_act(command), expected)

    def test_near_neighbours_stay_silent(self):
        for command in (
            "git push --dry-run origin HEAD",
            "grep -rn 'git push' scripts/",
            "echo 'remember to gh pr create later'",
            "gh pr view 12143 -R Neko-Catpital-Labs/Invoker --json state",
            "gh pr checks 12143 -R Neko-Catpital-Labs/Invoker",
            "gh api repos/o/r/pulls/12143 --jq .title",
            "git log --oneline origin/master",
            "cat scripts/safe-stack-push.mjs",
        ):
            with self.subTest(command=command):
                self.assertIsNone(detect.publishing_act(command))

    def test_dry_run_push_is_not_an_act(self):
        self.assertIsNone(detect.publishing_act("git push --dry-run origin HEAD"))


class PublisherLedgerCase(unittest.TestCase):
    def setUp(self):
        self.ledger = detect.PUBLISHERS_PATH if hasattr(detect, "PUBLISHERS_PATH") else None
        self.path = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"publish-act-guard-test-{os.getpid()}.json")
        if os.path.exists(self.path):
            os.unlink(self.path)
        detect.PUBLISHERS_PATH = self.path

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        if self.ledger is not None:
            detect.PUBLISHERS_PATH = self.ledger


class Decide(PublisherLedgerCase):
    def test_first_subagent_publish_in_a_session_is_allowed_when_owner_is_live(self):
        self.assertIsNone(detect.decide(payload("git push -u origin HEAD"), runner=LIVE))

    def test_same_subagent_may_publish_again(self):
        self.assertIsNone(detect.decide(payload("git push -u origin HEAD"), runner=LIVE))
        self.assertIsNone(detect.decide(payload("gh api -X PATCH repos/o/r/pulls/1 -f title=x"), runner=LIVE))

    def test_blocks_a_second_subagent_publishing_in_the_same_session(self):
        self.assertIsNone(detect.decide(payload("git push -u origin HEAD", agent="first"), runner=LIVE))
        refusal = detect.decide(payload("mergify stack push", agent="second"), runner=LIVE)
        self.assertIsNotNone(refusal)
        self.assertIn("mergify stack push", refusal)
        self.assertIn("first", refusal)
        self.assertIn("parent session", refusal)

    def test_second_subagent_is_allowed_once_the_window_has_passed(self):
        self.assertIsNone(detect.decide(payload("git push", agent="first"), runner=LIVE, now=1000.0))
        later = 1000.0 + detect.PARALLEL_WINDOW_SECONDS + 1
        self.assertIsNone(detect.decide(payload("git push", agent="second"), runner=LIVE, now=later))

    def test_other_sessions_do_not_count(self):
        self.assertIsNone(detect.decide(payload("git push", agent="first", session="s-1"), runner=LIVE))
        self.assertIsNone(detect.decide(payload("git push", agent="second", session="s-2"), runner=LIVE))

    def test_parallel_publishers_are_allowed_when_no_live_owner(self):
        self.assertIsNone(detect.decide(payload("git push", agent="first"), runner=DOWN))
        self.assertIsNone(detect.decide(payload("git push", agent="second"), runner=DOWN))

    def test_unreadable_ledger_reports_and_allows(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        refusal = detect.decide(payload("git push", agent="second"), runner=LIVE)
        self.assertIsNotNone(refusal)
        self.assertIn("UNCHECKED", refusal)

    def test_missing_session_id_reports_and_allows(self):
        refusal = detect.decide(payload("git push", session=None), runner=LIVE)
        self.assertIsNotNone(refusal)
        self.assertIn("UNCHECKED", refusal)

    def test_allows_when_no_live_owner(self):
        self.assertIsNone(detect.decide(payload("git push -u origin HEAD"), runner=DOWN))

    def test_allows_main_session(self):
        self.assertIsNone(
            detect.decide(payload("git push -u origin HEAD", subagent=False), runner=LIVE)
        )

    def test_allows_non_publishing_command(self):
        self.assertIsNone(detect.decide(payload("pnpm run check:types"), runner=LIVE))

    def test_allows_non_shell_tool(self):
        self.assertIsNone(
            detect.decide(payload("git push -u origin HEAD", tool="Write"), runner=LIVE)
        )

    def test_unreadable_liveness_reports_and_allows(self):
        refusal = detect.decide(payload("mergify stack push"), runner=TIMEOUT)
        self.assertIsNotNone(refusal)
        self.assertIn("UNCHECKED", refusal)
        self.assertIn("mergify stack push", refusal)

    def test_prompt_wording_cannot_trigger_or_clear_the_gate(self):
        self.assertIsNone(detect.decide(payload("git push", agent="first"), runner=LIVE))
        wording = payload("echo 'this subagent is carrying commits and will push a PR'", agent="second")
        self.assertIsNone(detect.decide(wording, runner=LIVE))
        real = payload("git push -u origin HEAD", agent="second")
        self.assertIsNotNone(detect.decide(real, runner=LIVE))


class LivenessStates(unittest.TestCase):
    def setUp(self):
        self.cache = detect.LIVENESS_CACHE_PATH
        detect.LIVENESS_CACHE_PATH = self.cache + ".test"
        if os.path.exists(detect.LIVENESS_CACHE_PATH):
            os.unlink(detect.LIVENESS_CACHE_PATH)

    def tearDown(self):
        if os.path.exists(detect.LIVENESS_CACHE_PATH):
            os.unlink(detect.LIVENESS_CACHE_PATH)
        detect.LIVENESS_CACHE_PATH = self.cache

    def test_three_outcomes(self):
        self.assertEqual(detect.invoker_state(runner=LIVE)[0], detect.LIVE)
        self.assertEqual(detect.invoker_state(runner=DOWN)[0], detect.DOWN)
        state, reason = detect.invoker_state(runner=TIMEOUT, now=0.0)
        self.assertEqual(state, detect.UNCHECKED)
        self.assertTrue(reason)

    def test_injected_probe_never_reads_or_writes_the_cache(self):
        detect.invoker_state(runner=LIVE)
        self.assertFalse(os.path.exists(detect.LIVENESS_CACHE_PATH))

    def test_missing_cli_reads_as_down(self):
        def missing():
            raise FileNotFoundError("invoker-cli")

        self.assertEqual(detect.invoker_state(runner=missing)[0], detect.DOWN)


if __name__ == "__main__":
    unittest.main()
