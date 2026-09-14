from pathlib import Path
import tempfile
import unittest

from engine.hooks._sdk.registry import HookRecord, Thresholds, load_registry


ROOT = Path(__file__).resolve().parents[4]
HOOKS_DIR = ROOT / "engine" / "hooks"


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry()
        self.hooks = {name: record for name, record in self.registry.items() if name != "thresholds"}

    def test_every_hook_folder_has_one_entry_and_every_entry_has_folder(self):
        folders = {path.name for path in HOOKS_DIR.iterdir() if path.is_dir() and not path.name.startswith("_")}
        self.assertEqual(folders, set(self.hooks))

    def test_a_folder_without_an_entry_fails_the_inventory_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing").mkdir()
            (root / "missing").mkdir()
            entries = {"existing": self.hooks["agent-relay-attribution"]}
            with self.assertRaises(AssertionError):
                self.assertEqual(
                    {path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith("_")},
                    set(entries),
                )

    def test_modes_and_reasons_are_allowed(self):
        for record in self.hooks.values():
            self.assertIn(record.mode, {"off", "warn", "stop"})
            self.assertIn(record.why_mode, {"attention", "outward", "habit"})

    def test_stop_habit_requires_target_mode(self):
        for name, record in self.hooks.items():
            if record.mode == "stop" and record.why_mode == "habit":
                self.assertIsNotNone(record.target_mode, name)

    def test_thresholds_are_present(self):
        thresholds = self.registry["thresholds"]
        self.assertIsInstance(thresholds, Thresholds)
        self.assertEqual(thresholds.min_closed_findings, 30)
        self.assertEqual(thresholds.followup_window_checks, 3)

    def test_unreadable_file_error_names_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-hooks.toml"
            with self.assertRaises(OSError) as context:
                load_registry(path)
            self.assertIn(str(path), str(context.exception))


if __name__ == "__main__":
    unittest.main()
