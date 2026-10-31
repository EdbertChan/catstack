from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import counters

SESSION = {"session_id": "counters-session", "hook_event_name": "PostToolUse"}
OTHER_SESSION = {"session_id": "counters-other-session"}
DIGEST = "abc123def456"
OTHER_DIGEST = "ffffffffffff"


class SameErrorCountTest(unittest.TestCase):
    def test_counting_one_signature_three_times_reaches_three(self) -> None:
        state: dict[str, object] = {}
        for expected in (1, 2, 3):
            counters.count_same_error(state, DIGEST, "boom", "pnpm test")
            self.assertEqual(counters.same_error_count(state, DIGEST), expected)

    def test_a_second_signature_counts_on_its_own(self) -> None:
        state: dict[str, object] = {}
        counters.count_same_error(state, DIGEST, "boom", "pnpm test")
        counters.count_same_error(state, DIGEST, "boom", "pnpm test")
        counters.count_same_error(state, OTHER_DIGEST, "other", "node x.mjs")
        self.assertEqual(counters.same_error_count(state, DIGEST), 2)
        self.assertEqual(counters.same_error_count(state, OTHER_DIGEST), 1)

    def test_no_signature_named_reports_the_highest_count(self) -> None:
        state: dict[str, object] = {}
        counters.count_same_error(state, DIGEST, "boom")
        counters.count_same_error(state, DIGEST, "boom")
        counters.count_same_error(state, OTHER_DIGEST, "other")
        self.assertEqual(counters.same_error_count(state), 2)

    def test_an_edit_between_failures_restarts_the_count(self) -> None:
        state: dict[str, object] = {}
        counters.count_same_error(state, DIGEST, "boom", "pnpm test")
        counters.count_same_error(state, DIGEST, "boom", "pnpm test")
        state["edit_epoch"] = 1
        counters.count_same_error(state, DIGEST, "boom", "pnpm test")
        self.assertEqual(counters.same_error_count(state, DIGEST), 1)

    def test_an_edit_does_not_restart_the_count_when_reset_is_off(self) -> None:
        state: dict[str, object] = {}
        counters.count_same_error(state, DIGEST, "boom", reset_on_edit=False)
        state["edit_epoch"] = 1
        counters.count_same_error(state, DIGEST, "boom", reset_on_edit=False)
        self.assertEqual(counters.same_error_count(state, DIGEST), 2)

    def test_commands_are_kept_once_each_and_bounded(self) -> None:
        state: dict[str, object] = {}
        for index in range(counters.MAX_COMMANDS + 5):
            counters.count_same_error(state, DIGEST, "boom", f"run {index}")
        counters.count_same_error(state, DIGEST, "boom", "run 0")
        entry = state["errors"][DIGEST]
        self.assertEqual(len(entry["commands"]), counters.MAX_COMMANDS)
        self.assertEqual(len(set(entry["commands"])), counters.MAX_COMMANDS)

    def test_no_state_reads_as_zero(self) -> None:
        self.assertEqual(counters.same_error_count({}, DIGEST), 0)
        self.assertEqual(counters.same_error_count({"errors": "not a table"}, DIGEST), 0)


class RepeatDenyCountTest(unittest.TestCase):
    def test_the_same_reason_twice_in_a_row_reaches_two(self) -> None:
        state: dict[str, object] = {}
        self.assertEqual(counters.count_repeat_deny(state, "permission denied"), 1)
        self.assertEqual(counters.count_repeat_deny(state, "permission denied"), 2)
        self.assertEqual(counters.repeat_deny_count(state), 2)

    def test_a_different_reason_restarts_the_run(self) -> None:
        state: dict[str, object] = {}
        counters.count_repeat_deny(state, "first")
        counters.count_repeat_deny(state, "first")
        self.assertEqual(counters.count_repeat_deny(state, "second"), 1)

    def test_a_call_that_was_not_denied_ends_the_run(self) -> None:
        state: dict[str, object] = {}
        counters.count_repeat_deny(state, "first")
        counters.clear_repeat_deny(state)
        self.assertEqual(counters.repeat_deny_count(state), 0)
        self.assertEqual(counters.count_repeat_deny(state, "first"), 1)

    def test_naming_a_reason_outside_the_current_run_reads_as_zero(self) -> None:
        state: dict[str, object] = {}
        counters.count_repeat_deny(state, "first")
        self.assertEqual(counters.repeat_deny_count(state, "second"), 0)
        self.assertEqual(counters.repeat_deny_count(state, "first"), 1)

    def test_no_state_reads_as_zero(self) -> None:
        self.assertEqual(counters.repeat_deny_count({}), 0)


class SessionStateTest(unittest.TestCase):
    def test_counters_are_scoped_to_one_session(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            state = counters.load_state(state_dir, SESSION)
            counters.count_same_error(state, DIGEST, "boom", "pnpm test")
            counters.save_state(state_dir, SESSION, state)
            self.assertEqual(counters.same_error_count(counters.load_state(state_dir, SESSION), DIGEST), 1)
            self.assertEqual(counters.same_error_count(counters.load_state(state_dir, OTHER_SESSION), DIGEST), 0)

    def test_a_subagent_gets_its_own_counters(self) -> None:
        with_agent = {**SESSION, "agent_id": "agent-7"}
        self.assertNotEqual(counters.session_key(SESSION), counters.session_key(with_agent))

    def test_reset_drops_the_counters(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            counters.save_state(state_dir, SESSION, {"errors": {DIGEST: {"count": 2}}})
            counters.reset_state(state_dir, SESSION)
            self.assertEqual(counters.load_state(state_dir, SESSION), {})

    def test_state_older_than_the_window_reads_as_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            path = counters.state_path(state_dir, SESSION)
            stale = {"errors": {DIGEST: {"count": 9}}, "updated_at": time.time() - counters.TTL_SECONDS - 60}
            Path(path).write_text(json.dumps(stale), encoding="utf-8")
            self.assertEqual(counters.load_state(state_dir, SESSION), {})

    def test_unreadable_state_reads_as_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            Path(counters.state_path(state_dir, SESSION)).write_text("{not json", encoding="utf-8")
            self.assertEqual(counters.load_state(state_dir, SESSION), {})

    def test_deny_state_needs_a_named_session(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            self.assertEqual(counters.deny_state_path(state_dir, {"cwd": "/tmp"}), "")
            self.assertTrue(counters.deny_state_path(state_dir, SESSION).endswith(".json"))


class SessionCountersTest(unittest.TestCase):
    def test_both_counters_are_reported_by_policy_name(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            error_dir = os.path.join(root, "error")
            deny_dir = os.path.join(root, "deny")
            os.makedirs(deny_dir, exist_ok=True)
            error_state: dict[str, object] = {}
            counters.count_same_error(error_state, DIGEST, "boom")
            counters.count_same_error(error_state, DIGEST, "boom")
            counters.count_same_error(error_state, DIGEST, "boom")
            counters.save_state(error_dir, SESSION, error_state)
            deny_state: dict[str, object] = {"updated_at": time.time()}
            counters.count_repeat_deny(deny_state, "permission denied")
            counters.count_repeat_deny(deny_state, "permission denied")
            Path(counters.deny_state_path(deny_dir, SESSION)).write_text(json.dumps(deny_state), encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    counters.ERROR_STATE_DIR_ENV: error_dir,
                    counters.DENY_STATE_DIR_ENV: deny_dir,
                },
                clear=False,
            ):
                self.assertEqual(
                    counters.session_counters(SESSION),
                    {counters.SAME_ERROR_COUNT: 3, counters.REPEAT_DENY_COUNT: 2},
                )

    def test_a_session_with_no_state_reports_zero_for_every_counter(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(
                os.environ,
                {
                    counters.ERROR_STATE_DIR_ENV: os.path.join(root, "error"),
                    counters.DENY_STATE_DIR_ENV: os.path.join(root, "deny"),
                },
                clear=False,
            ):
                self.assertEqual(
                    counters.session_counters(SESSION),
                    {counters.SAME_ERROR_COUNT: 0, counters.REPEAT_DENY_COUNT: 0},
                )
            self.assertFalse(os.path.isdir(os.path.join(root, "error")))

    def test_every_counter_name_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(
                os.environ,
                {
                    counters.ERROR_STATE_DIR_ENV: os.path.join(root, "error"),
                    counters.DENY_STATE_DIR_ENV: os.path.join(root, "deny"),
                },
                clear=False,
            ):
                self.assertEqual(sorted(counters.session_counters(SESSION)), sorted(counters.COUNTER_NAMES))


def _load_hook_detector(hook: str):
    """One hook's detect module, loaded under its own name so two hooks can be loaded at once."""
    path = SDK_DIR.parent / hook / "detect.py"
    spec = importlib.util.spec_from_file_location(f"{hook}-detect", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepeatHooksUseTheSharedCountersTest(unittest.TestCase):
    def test_repeat_error_stop_counts_through_this_module(self) -> None:
        detector = _load_hook_detector("repeat-error-stop")
        self.assertIs(detector.counters, counters)
        state: dict[str, object] = {}
        counters.count_same_error(state, DIGEST, "boom")
        self.assertEqual(detector.state_int(counters.same_error_count(state, DIGEST)), 1)

    def test_repeat_deny_stop_counts_through_this_module(self) -> None:
        detector = _load_hook_detector("repeat-deny-stop")
        self.assertIs(detector.counters, counters)
        self.assertEqual(detector.REPEAT_DENY_THRESHOLD, 2)


if __name__ == "__main__":
    unittest.main()
