from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = HOOKS_ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine.hooks._sdk.registry import (  # noqa: E402
    ALLOWED_MODES,
    ALLOWED_WHY_MODES,
    THRESHOLD_KEYS,
    HookRecord,
    Registry,
    RegistryLoadError,
    Thresholds,
    load_registry,
)


def hook_folders(root: Path = HOOKS_ROOT) -> set[str]:
    return {
        path.name
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    }


def assert_registry_matches_folders(
    case: unittest.TestCase,
    *,
    registry: Registry,
    hooks_root: Path = HOOKS_ROOT,
) -> None:
    folders = hook_folders(hooks_root)
    entries = set(registry.hooks)
    case.assertEqual(folders - entries, set(), "hook folders missing registry entries")
    case.assertEqual(entries - folders, set(), "registry entries missing hook folders")


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry()

    def test_every_hook_folder_has_one_entry_and_every_entry_has_a_folder(self) -> None:
        assert_registry_matches_folders(self, registry=self.registry)

    def test_mode_and_why_mode_values_are_allowed(self) -> None:
        for name, record in self.registry.hooks.items():
            with self.subTest(hook=name):
                self.assertIn(record.mode, ALLOWED_MODES)
                self.assertIn(record.why_mode, ALLOWED_WHY_MODES)

    def test_stop_habit_requires_target_mode(self) -> None:
        for name, record in self.registry.hooks.items():
            with self.subTest(hook=name):
                if record.mode == "stop" and record.why_mode == "habit":
                    self.assertTrue(record.target_mode)

    def test_thresholds_are_present(self) -> None:
        thresholds = self.registry.thresholds
        for key in THRESHOLD_KEYS:
            with self.subTest(threshold=key):
                self.assertTrue(hasattr(thresholds, key))

    def test_unreadable_file_error_names_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-a-readable-toml-directory"
            path.mkdir()
            with self.assertRaisesRegex(RegistryLoadError, str(path)):
                load_registry(path)


class RegistryInvariantTest(unittest.TestCase):
    def test_missing_folder_entry_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "known-hook").mkdir()
            (root / "new-hook").mkdir()
            registry = Registry(
                hooks={
                    "known-hook": HookRecord(
                        name="known-hook",
                        mode="warn",
                        why_mode="habit",
                        summary="Fixture hook.",
                    )
                },
                thresholds=Thresholds(
                    min_closed_findings=30,
                    promote_max_ignore_rate=0.02,
                    demote_min_ignore_rate=0.10,
                    review_min_ignore_rate=0.50,
                    review_min_unchecked_rate=0.05,
                    followup_window_checks=3,
                ),
            )
            with self.assertRaises(AssertionError):
                assert_registry_matches_folders(self, registry=registry, hooks_root=root)


if __name__ == "__main__":
    unittest.main()
