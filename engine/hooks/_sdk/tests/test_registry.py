import tempfile
import unittest
from pathlib import Path

from engine.hooks._sdk.registry import HookRecord, Thresholds, load_registry


ROOT = Path(__file__).resolve().parents[3]
HOOKS_DIR = ROOT / "hooks"
REGISTRY_PATH = HOOKS_DIR / "hooks.toml"


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(REGISTRY_PATH)

    def test_every_hook_folder_has_one_entry_and_every_entry_has_folder(self):
        folders = {
            path.name for path in HOOKS_DIR.iterdir()
            if path.is_dir() and not path.name.startswith("_")
        }
        entries = {name for name, record in self.registry.items() if isinstance(record, HookRecord)}
        self.assertEqual(folders, entries)

    def test_mode_and_reason_values_are_allowed(self):
        for record in self._hooks():
            self.assertIn(record.mode, {"off", "warn", "stop"})
            self.assertIn(record.why_mode, {"attention", "outward", "habit"})

    def test_stop_habit_requires_target_mode(self):
        for name, record in self._hook_items():
            if record.mode == "stop" and record.why_mode == "habit":
                self.assertIsNotNone(record.target_mode, name)

    def test_thresholds_are_present(self):
        thresholds = self.registry["thresholds"]
        self.assertIsInstance(thresholds, Thresholds)
        self.assertEqual(thresholds.min_closed_findings, 30)
        self.assertEqual(thresholds.followup_window_checks, 3)

    def test_unreadable_file_raises_with_path(self):
        with tempfile.TemporaryDirectory() as directory:
            unreadable = Path(directory) / "missing-hooks.toml"
            with self.assertRaisesRegex(RuntimeError, str(unreadable)):
                load_registry(unreadable)

    def _hook_items(self):
        return ((name, record) for name, record in self.registry.items() if isinstance(record, HookRecord))

    def _hooks(self):
        return (record for _, record in self._hook_items())


if __name__ == "__main__":
    unittest.main()
