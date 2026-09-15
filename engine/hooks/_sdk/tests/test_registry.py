from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SDK_DIR = Path(__file__).resolve().parents[1]
HOOKS_DIR = SDK_DIR.parent
sys.path.insert(0, str(SDK_DIR))

import registry  # noqa: E402


ALLOWED_MODES = {"off", "warn", "stop"}
ALLOWED_WHY_MODES = {"attention", "outward", "habit"}
REQUIRED_THRESHOLDS = {
    "min_closed_findings",
    "promote_max_ignore_rate",
    "demote_min_ignore_rate",
    "review_min_ignore_rate",
    "review_min_unchecked_rate",
    "followup_window_checks",
}


def hook_folders(root: Path = HOOKS_DIR) -> set[str]:
    return {
        path.name
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    }


def assert_registry_matches_folders(testcase: unittest.TestCase, hooks: dict[str, registry.HookRecord], folders: set[str]) -> None:
    testcase.assertEqual(folders, set(hooks))


class RegistryTests(unittest.TestCase):
    def test_hook_folders_match_registry_entries(self):
        hooks, _thresholds = registry.load_registry()
        assert_registry_matches_folders(self, hooks, hook_folders())

    def test_extra_folder_without_registry_entry_is_rejected(self):
        hooks, _thresholds = registry.load_registry()
        folders = set(hook_folders())
        folders.add("unregistered-test-hook")
        with self.assertRaises(AssertionError):
            assert_registry_matches_folders(self, hooks, folders)

    def test_mode_and_why_mode_values_are_allowed(self):
        hooks, _thresholds = registry.load_registry()
        for hook in hooks.values():
            with self.subTest(hook=hook.name):
                self.assertIn(hook.mode, ALLOWED_MODES)
                self.assertIn(hook.why_mode, ALLOWED_WHY_MODES)

    def test_stop_habit_requires_target_mode(self):
        hooks, _thresholds = registry.load_registry()
        for hook in hooks.values():
            with self.subTest(hook=hook.name):
                if hook.mode == "stop" and hook.why_mode == "habit":
                    self.assertIsNotNone(hook.target_mode)

    def test_thresholds_are_present(self):
        _hooks, thresholds = registry.load_registry()
        self.assertEqual(REQUIRED_THRESHOLDS, set(thresholds))

    def test_unreadable_file_error_names_path(self):
        with tempfile.NamedTemporaryFile() as handle:
            path = Path(handle.name)
            with mock.patch.object(Path, "open", side_effect=PermissionError("denied")):
                with self.assertRaises(registry.RegistryError) as ctx:
                    registry.load_registry(path)
        self.assertIn(str(path), str(ctx.exception))

    def test_missing_file_error_names_path(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "missing-hooks.toml"
            with self.assertRaises(registry.RegistryError) as ctx:
                registry.load_registry(path)
        self.assertIn(str(path), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
