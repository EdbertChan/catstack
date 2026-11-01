from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import counters
import events
import modes
import registry
import runtime
from finding import Finding

HARD_ON_CLAUDE_ONLY = registry.EnforcementPolicy(
    default="hard",
    capability=("claude:Stop",),
    evidence=("command_output",),
)
SOFT_ESCALATING = registry.EnforcementPolicy(
    default="soft",
    capability=("claude:PostToolUse",),
    escalate=registry.EscalateRule(
        counter=counters.SAME_ERROR_COUNT,
        threshold=3,
        to="hard",
        when="same_error_count >= 3",
    ),
)
CLAUDE_STOP = {"hook_event_name": "Stop", "_catstack_harness": "claude"}
CURSOR_STOP = {"hook_event_name": "stop", "_catstack_harness": "cursor"}
FINDING = Finding(
    "hedge-runs-prove-it.hedge",
    "reply:abc",
    "Run the check or drop the hedge.",
    "probably fixed",
)
REGISTRY_TAIL = textwrap.dedent(
    """
    [thresholds]
    min_closed_findings = 30
    promote_max_ignore_rate = 0.02
    demote_min_ignore_rate = 0.10
    review_min_ignore_rate = 0.50
    review_min_unchecked_rate = 0.05
    followup_window_checks = 3
    """
).strip()


class EffectiveLevelTest(unittest.TestCase):
    def test_a_hard_rule_stays_hard_on_a_harness_that_can_check_it(self) -> None:
        level, reason = modes.effective_level(HARD_ON_CLAUDE_ONLY, "claude", CLAUDE_STOP, {})
        self.assertEqual(level, "hard")
        self.assertEqual(reason, "")

    def test_a_hard_rule_the_harness_cannot_check_is_unchecked_not_clean(self) -> None:
        level, reason = modes.effective_level(HARD_ON_CLAUDE_ONLY, "cursor", CURSOR_STOP, {})
        self.assertEqual(level, modes.UNCHECKED_LEVEL)
        self.assertIn("cursor", reason)
        self.assertIn("claude:Stop", reason)
        self.assertIn("hard", reason)

    def test_the_running_harness_comes_from_the_event_when_none_is_named(self) -> None:
        level, _reason = modes.effective_level(HARD_ON_CLAUDE_ONLY, "", CLAUDE_STOP, {})
        self.assertEqual(level, "hard")
        level, _reason = modes.effective_level(HARD_ON_CLAUDE_ONLY, "", CURSOR_STOP, {})
        self.assertEqual(level, modes.UNCHECKED_LEVEL)

    def test_a_soft_rule_needs_no_capability_and_is_never_unchecked(self) -> None:
        soft = registry.EnforcementPolicy(default="soft")
        self.assertEqual(modes.effective_level(soft, "cursor", CURSOR_STOP, {}), ("soft", ""))

    def test_a_counter_below_the_threshold_leaves_the_default_level(self) -> None:
        event = {"hook_event_name": "PostToolUse", "_catstack_harness": "claude"}
        level, reason = modes.effective_level(SOFT_ESCALATING, "claude", event, {counters.SAME_ERROR_COUNT: 2})
        self.assertEqual(level, "soft")
        self.assertEqual(reason, "")

    def test_a_counter_at_the_threshold_escalates(self) -> None:
        event = {"hook_event_name": "PostToolUse", "_catstack_harness": "claude"}
        level, reason = modes.effective_level(SOFT_ESCALATING, "claude", event, {counters.SAME_ERROR_COUNT: 3})
        self.assertEqual(level, "hard")
        self.assertEqual(reason, "")

    def test_an_escalated_level_the_harness_cannot_check_is_unchecked(self) -> None:
        event = {"hook_event_name": "postToolUse", "_catstack_harness": "cursor"}
        level, reason = modes.effective_level(SOFT_ESCALATING, "cursor", event, {counters.SAME_ERROR_COUNT: 5})
        self.assertEqual(level, modes.UNCHECKED_LEVEL)
        self.assertIn("claude:PostToolUse", reason)

    def test_a_missing_counter_reads_as_zero_and_does_not_escalate(self) -> None:
        event = {"hook_event_name": "PostToolUse", "_catstack_harness": "claude"}
        self.assertEqual(modes.effective_level(SOFT_ESCALATING, "claude", event, {}), ("soft", ""))
        self.assertEqual(modes.effective_level(SOFT_ESCALATING, "claude", event, None), ("soft", ""))

    def test_a_hook_with_no_policy_declares_no_level(self) -> None:
        self.assertEqual(modes.effective_level(None, "claude", CLAUDE_STOP, {}), (modes.UNDECLARED_LEVEL, ""))


class CommittedPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hooks, _thresholds = registry.load_registry()

    def test_the_four_policy_hooks_carry_one(self) -> None:
        for name in ("narrow-the-scope", "repeat-error-stop", "hedge-runs-prove-it", "prove-it-ship-gate"):
            with self.subTest(name=name):
                self.assertIsNotNone(self.hooks[name].enforcement)

    def test_every_committed_policy_is_checkable_on_the_harness_it_lists(self) -> None:
        policies = {name: record.enforcement for name, record in self.hooks.items() if record.enforcement}
        self.assertTrue(policies)
        for name, policy in policies.items():
            for entry in policy.capability:
                harness = entry.split(":", 1)[0]
                with self.subTest(name=name, harness=harness):
                    level, reason = modes.effective_level(policy, harness, {"hook_event_name": "Stop"}, {})
                    self.assertNotEqual(level, modes.UNCHECKED_LEVEL)
                    self.assertEqual(reason, "")

    def test_a_stop_hook_not_wired_on_a_harness_reports_unchecked_there(self) -> None:
        policy = self.hooks["hedge-runs-prove-it"].enforcement
        level, reason = modes.effective_level(policy, "codex", {"hook_event_name": "Stop"}, {})
        self.assertEqual(level, modes.UNCHECKED_LEVEL)
        self.assertIn("codex", reason)

    def test_repeat_error_stop_escalates_on_its_own_counter(self) -> None:
        policy = self.hooks["repeat-error-stop"].enforcement
        event = {"hook_event_name": "PostToolUse"}
        self.assertEqual(modes.effective_level(policy, "claude", event, {})[0], "conditional")
        counts = {counters.SAME_ERROR_COUNT: 3}
        self.assertEqual(modes.effective_level(policy, "claude", event, counts)[0], "hard")


class EnforcementPolicyLookupTest(unittest.TestCase):
    def _registry(self, body: str) -> str:
        path = os.path.join(self.tmp, "hooks.toml")
        Path(path).write_text(f"{body.strip()}\n\n{REGISTRY_TAIL}\n", encoding="utf-8")
        return path

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_the_policy_comes_from_the_registry_the_event_names(self) -> None:
        path = self._registry(
            """
            [hooks.hedge-runs-prove-it]
            mode = "stop"
            why_mode = "attention"
            summary = "Test registry entry."

            [hooks.hedge-runs-prove-it.enforcement]
            default = "hard"
            capability = ["claude:Stop"]
            """
        )
        event = {"registry_path": path, "hook_event_name": "Stop", "session_id": "modes-test"}
        policy = modes.enforcement_policy("hedge-runs-prove-it", event)
        self.assertEqual(policy.default, "hard")
        self.assertEqual(policy.capability, ("claude:Stop",))

    def test_a_hook_the_registry_does_not_list_is_named_in_the_error(self) -> None:
        path = self._registry(
            """
            [hooks.diu-stop]
            mode = "stop"
            why_mode = "attention"
            summary = "Test registry entry."
            """
        )
        event = {"registry_path": path, "hook_event_name": "Stop"}
        with self.assertRaisesRegex(registry.RegistryError, "hedge-runs-prove-it"):
            modes.enforcement_policy("hedge-runs-prove-it", event)

    def test_the_session_counters_feed_the_escalate_rule(self) -> None:
        path = self._registry(
            """
            [hooks.narrow-the-scope]
            mode = "warn"
            why_mode = "habit"
            summary = "Test registry entry."

            [hooks.narrow-the-scope.enforcement]
            default = "soft"
            escalate = { when = "same_error_count >= 3", to = "hard" }
            capability = ["claude:PostToolUse"]
            """
        )
        event = {"registry_path": path, "hook_event_name": "PostToolUse", "session_id": "modes-escalate"}
        error_dir = os.path.join(self.tmp, "error")
        state: dict[str, object] = {}
        for _ in range(3):
            counters.count_same_error(state, "deadbeef", "boom")
        counters.save_state(error_dir, event, state)
        with mock.patch.dict(
            os.environ,
            {
                counters.ERROR_STATE_DIR_ENV: error_dir,
                counters.DENY_STATE_DIR_ENV: os.path.join(self.tmp, "deny"),
            },
            clear=False,
        ):
            self.assertEqual(modes.finding_enforcement("narrow-the-scope", "claude", event), ("hard", ""))
            self.assertEqual(
                modes.finding_enforcement("narrow-the-scope", "codex", event)[0],
                modes.UNCHECKED_LEVEL,
            )


class RunnerRecordsTheLevelTest(unittest.TestCase):
    def _run(self, harness: str) -> list[dict[str, object]]:
        event = {
            "hook_event_name": "Stop",
            "session_id": f"modes-runner-{harness}",
            "model": "claude-sonnet-5",
        }
        with tempfile.TemporaryDirectory() as metrics_dir:
            with mock.patch.dict(
                os.environ,
                {"CATSTACK_HOOK_METRICS_DIR": metrics_dir},
                clear=False,
            ), mock.patch.object(events, "publish_rows", lambda rows: None), contextlib.redirect_stdout(
                io.StringIO()
            ), contextlib.redirect_stderr(io.StringIO()):
                with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
                    with self.assertRaises(SystemExit):
                        runtime.run_hook("hedge-runs-prove-it", harness, lambda _event: [FINDING])
            rows = []
            for path in sorted(Path(metrics_dir).glob("events-*.jsonl")):
                rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
        return rows

    def test_the_row_carries_the_level_the_harness_can_check(self) -> None:
        rows = [row for row in self._run("claude") if row["rule_id"] == FINDING.rule_id]
        self.assertEqual([row["effective_level"] for row in rows], ["hard"])
        self.assertEqual([row["downgrade_reason"] for row in rows], [""])

    def test_the_row_records_unchecked_when_the_harness_cannot_check_the_rule(self) -> None:
        rows = [row for row in self._run("cursor") if row["rule_id"] == FINDING.rule_id]
        self.assertEqual([row["effective_level"] for row in rows], [modes.UNCHECKED_LEVEL])
        self.assertEqual(len(rows), 1)
        self.assertIn("claude:Stop", rows[0]["downgrade_reason"])
        self.assertIn("cursor", rows[0]["downgrade_reason"])


if __name__ == "__main__":
    unittest.main()
