from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
HOOKS_DIR = SDK_DIR.parent
sys.path.insert(0, str(SDK_DIR))

import registry


class HookRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loaded = registry.load_registry()

    def test_every_hook_folder_has_one_entry_and_every_entry_has_folder(self) -> None:
        folders = {
            path.name
            for path in HOOKS_DIR.iterdir()
            if path.is_dir() and not path.name.startswith("_")
        }
        entries = set(self.loaded.hooks)
        self.assertEqual(folders, entries)
        self.assertEqual(len(entries), len(self.loaded.hooks))

    def test_mode_and_why_mode_values_are_allowed(self) -> None:
        modes = {"off", "warn", "stop"}
        why_modes = {"attention", "outward", "habit"}
        for name, record in self.loaded.hooks.items():
            with self.subTest(hook=name):
                self.assertIn(record.mode, modes)
                self.assertIn(record.why_mode, why_modes)

    def test_stop_habit_requires_target_mode(self) -> None:
        offenders = [
            name
            for name, record in self.loaded.hooks.items()
            if record.mode == "stop" and record.why_mode == "habit" and not record.target_mode
        ]
        self.assertEqual([], offenders)

    def test_thresholds_are_present(self) -> None:
        self.assertEqual(30, self.loaded.thresholds.min_closed_findings)
        self.assertEqual(0.02, self.loaded.thresholds.promote_max_ignore_rate)
        self.assertEqual(0.10, self.loaded.thresholds.demote_min_ignore_rate)
        self.assertEqual(0.50, self.loaded.thresholds.review_min_ignore_rate)
        self.assertEqual(0.05, self.loaded.thresholds.review_min_unchecked_rate)
        self.assertEqual(3, self.loaded.thresholds.followup_window_checks)

    def test_unreadable_file_error_names_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(registry.RegistryError, tmp):
                registry.load_registry(tmp)

    def test_loads_registry_without_stdlib_toml_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hooks.toml"
            path.write_text(
                "\n".join(
                    [
                        "[demo-hook]",
                        'mode = "warn"',
                        'why_mode = "habit"',
                        'summary = "Demo summary."',
                        'enabled_by = "CATSTACK_DEMO"',
                        "",
                        "[thresholds]",
                        "min_closed_findings = 30",
                        "promote_max_ignore_rate = 0.02",
                        "demote_min_ignore_rate = 0.10",
                        "review_min_ignore_rate = 0.50",
                        "review_min_unchecked_rate = 0.05",
                        "followup_window_checks = 3",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.object(registry, "tomllib", None):
                loaded = registry.load_registry(path)

        self.assertEqual("demo-hook", loaded["demo-hook"].name)
        self.assertEqual("CATSTACK_DEMO", loaded["demo-hook"].enabled_by)
        self.assertEqual(3, loaded.thresholds.followup_window_checks)


if __name__ == "__main__":
    unittest.main()
