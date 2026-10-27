import json
from pathlib import Path
import tempfile
import textwrap
import unittest

from engine.hooks._sdk.counters import COUNTER_NAMES
from engine.hooks._sdk.registry import (
    HookRecord,
    LEVELS_NEEDING_CAPABILITY,
    VALID_LEVELS,
    VALID_OVERRIDES,
    RegistryError,
    load_registry,
)


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_MODES = {"off", "warn", "stop"}
ALLOWED_REASONS = {"attention", "outward", "habit"}
POLICY_HOOKS = ("narrow-the-scope", "repeat-error-stop", "hedge-runs-prove-it", "prove-it-ship-gate")
THRESHOLDS_TABLE = textwrap.dedent(
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


def _wired_events(hook: str, harness: str) -> set[str]:
    """The harness events this hook's checked-in fragments wire, which is what the installer reads."""
    events: set[str] = set()
    for path in sorted((ROOT / hook).glob(f"{harness}*.hook.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        events.update((data.get("hooks") or {}).keys())
    return events


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hooks, cls.thresholds = load_registry()
        cls.folders = {
            path.name for path in ROOT.iterdir()
            if path.is_dir() and not path.name.startswith("_")
        }

    def test_every_hook_folder_and_registry_entry_match(self):
        self.assertEqual(set(self.hooks), self.folders)

    def test_modes_and_reasons_are_allowed(self):
        for name, record in self.hooks.items():
            with self.subTest(name=name):
                self.assertIsInstance(record, HookRecord)
                self.assertIn(record.mode, ALLOWED_MODES)
                self.assertIn(record.why_mode, ALLOWED_REASONS)
                self.assertTrue(record.summary)
                for rule_id, mode in (record.rule_modes or {}).items():
                    self.assertTrue(rule_id.startswith(f"{name}."))
                    self.assertIn(mode, ALLOWED_MODES)

    def test_stop_habit_requires_target_mode(self):
        for name, record in self.hooks.items():
            if record.mode == "stop" and record.why_mode == "habit":
                with self.subTest(name=name):
                    self.assertIsNotNone(record.target_mode)

    def test_worker_hooks_are_exactly_the_two_registered(self):
        worker_hooks = sorted(name for name, record in self.hooks.items() if record.worker)
        self.assertEqual(worker_hooks, ["cat-mode-default", "wait-needs-wakeup"])

    def test_thresholds_are_present(self):
        self.assertEqual(self.thresholds.min_closed_findings, 30)
        self.assertEqual(self.thresholds.promote_max_ignore_rate, 0.02)
        self.assertEqual(self.thresholds.demote_min_ignore_rate, 0.10)
        self.assertEqual(self.thresholds.review_min_ignore_rate, 0.50)
        self.assertEqual(self.thresholds.review_min_unchecked_rate, 0.05)
        self.assertEqual(self.thresholds.followup_window_checks, 3)

    def test_enforcement_is_optional_and_valid_where_it_is_declared(self):
        for name, record in self.hooks.items():
            policy = record.enforcement
            with self.subTest(name=name):
                if policy is None:
                    self.assertNotIn(name, POLICY_HOOKS)
                    continue
                self.assertIn(policy.default, VALID_LEVELS)
                self.assertIn(policy.override, VALID_OVERRIDES)
                for level in policy.declared_levels():
                    if level in LEVELS_NEEDING_CAPABILITY:
                        self.assertTrue(policy.capability)
                if policy.escalate is not None:
                    self.assertIn(policy.escalate.counter, COUNTER_NAMES)
                    self.assertGreater(policy.escalate.threshold, 0)

    def test_the_four_policy_hooks_declare_enforcement(self):
        for name in POLICY_HOOKS:
            with self.subTest(name=name):
                self.assertIsNotNone(self.hooks[name].enforcement)

    def test_every_listed_capability_is_an_event_the_hook_really_wires(self):
        for name, record in self.hooks.items():
            if record.enforcement is None:
                continue
            for entry in record.enforcement.capability:
                harness, _, event = entry.partition(":")
                with self.subTest(name=name, entry=entry):
                    self.assertIn(event, _wired_events(name, harness))

    def test_unreadable_file_names_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.toml"
            with self.assertRaisesRegex(Exception, str(path)):
                load_registry(path)


class EnforcementSchemaTests(unittest.TestCase):
    def _load(self, enforcement: str):
        body = textwrap.dedent(
            f"""
            [hooks.diu-stop]
            mode = "stop"
            why_mode = "attention"
            summary = "Test registry entry."

            [hooks.diu-stop.enforcement]
            {textwrap.dedent(enforcement).strip()}
            """
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hooks.toml"
            path.write_text(f"{body}\n\n{THRESHOLDS_TABLE}\n", encoding="utf-8")
            return load_registry(path)

    def test_a_hard_default_with_no_capability_list_fails(self):
        with self.assertRaisesRegex(RegistryError, "capability"):
            self._load('default = "hard"')

    def test_a_conditional_default_with_no_capability_list_fails(self):
        with self.assertRaisesRegex(RegistryError, "capability"):
            self._load('default = "conditional"')

    def test_escalating_to_hard_with_no_capability_list_fails(self):
        with self.assertRaisesRegex(RegistryError, "capability"):
            self._load(
                """
                default = "soft"
                escalate = { when = "same_error_count >= 3", to = "hard" }
                """
            )

    def test_a_soft_default_needs_no_capability_list(self):
        hooks, _thresholds = self._load('default = "soft"')
        self.assertEqual(hooks["diu-stop"].enforcement.default, "soft")
        self.assertEqual(hooks["diu-stop"].enforcement.capability, ())

    def test_a_hard_default_with_a_capability_list_loads(self):
        hooks, _thresholds = self._load(
            """
            default = "hard"
            capability = ["claude:Stop"]
            evidence = ["command_output"]
            override = "never"
            """
        )
        policy = hooks["diu-stop"].enforcement
        self.assertEqual(policy.default, "hard")
        self.assertEqual(policy.capability, ("claude:Stop",))
        self.assertEqual(policy.evidence, ("command_output",))
        self.assertEqual(policy.override, "never")

    def test_an_unknown_level_fails(self):
        with self.assertRaisesRegex(RegistryError, "default"):
            self._load('default = "blocking"')

    def test_an_unknown_override_fails(self):
        with self.assertRaisesRegex(RegistryError, "override"):
            self._load('default = "soft"\noverride = "whenever"')

    def test_an_escalate_rule_naming_an_unknown_counter_fails(self):
        with self.assertRaisesRegex(RegistryError, "unknown counter"):
            self._load(
                """
                default = "soft"
                capability = ["claude:Stop"]
                escalate = { when = "vibes_count >= 3", to = "hard" }
                """
            )

    def test_an_escalate_rule_that_is_not_a_counter_comparison_fails(self):
        with self.assertRaisesRegex(RegistryError, "when"):
            self._load(
                """
                default = "soft"
                capability = ["claude:Stop"]
                escalate = { when = "the agent looks stuck", to = "hard" }
                """
            )

    def test_an_escalate_rule_reads_its_counter_and_threshold(self):
        hooks, _thresholds = self._load(
            """
            default = "soft"
            capability = ["claude:Stop"]
            escalate = { when = "repeat_deny_count >= 2", to = "hard" }
            """
        )
        escalate = hooks["diu-stop"].enforcement.escalate
        self.assertEqual(escalate.counter, "repeat_deny_count")
        self.assertEqual(escalate.threshold, 2)
        self.assertEqual(escalate.to, "hard")

    def test_a_capability_entry_naming_no_harness_fails(self):
        with self.assertRaisesRegex(RegistryError, "capability"):
            self._load('default = "hard"\ncapability = ["Stop"]')

    def test_an_unknown_enforcement_key_fails(self):
        with self.assertRaisesRegex(RegistryError, "unknown keys"):
            self._load('default = "soft"\nstrictness = "high"')


if __name__ == "__main__":
    unittest.main()
