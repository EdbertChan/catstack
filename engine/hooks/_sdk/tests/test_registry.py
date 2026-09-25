from pathlib import Path
import tempfile
import unittest

from engine.hooks._sdk.registry import HookRecord, load_registry


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_MODES = {"off", "warn", "stop"}
ALLOWED_REASONS = {"attention", "outward", "habit"}


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

    def test_thresholds_are_present(self):
        self.assertEqual(self.thresholds.min_closed_findings, 30)
        self.assertEqual(self.thresholds.promote_max_ignore_rate, 0.02)
        self.assertEqual(self.thresholds.demote_min_ignore_rate, 0.10)
        self.assertEqual(self.thresholds.review_min_ignore_rate, 0.50)
        self.assertEqual(self.thresholds.review_min_unchecked_rate, 0.05)
        self.assertEqual(self.thresholds.followup_window_checks, 3)

    def test_unreadable_file_names_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.toml"
            with self.assertRaisesRegex(Exception, str(path)):
                load_registry(path)


if __name__ == "__main__":
    unittest.main()
