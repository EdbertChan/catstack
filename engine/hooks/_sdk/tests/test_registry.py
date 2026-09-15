from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import tempfile
import unittest


SDK_DIR = Path(__file__).resolve().parents[1]
HOOKS_DIR = SDK_DIR.parent
sys.path.insert(0, str(SDK_DIR))

import registry  # noqa: E402


ALLOWED_MODES = {"off", "warn", "stop"}
ALLOWED_WHY_MODES = {"attention", "outward", "habit"}
THRESHOLD_KEYS = {
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


class RegistryTest(unittest.TestCase):
    def test_every_hook_folder_has_exactly_one_entry_and_every_entry_has_folder(self) -> None:
        loaded = registry.load_registry()
        self.assertEqual(hook_folders(), set(loaded.hooks))

    def test_modes_and_reasons_are_allowed_values(self) -> None:
        loaded = registry.load_registry()
        bad_modes = {
            name: record.mode
            for name, record in loaded.hooks.items()
            if record.mode not in ALLOWED_MODES
        }
        bad_reasons = {
            name: record.why_mode
            for name, record in loaded.hooks.items()
            if record.why_mode not in ALLOWED_WHY_MODES
        }
        self.assertEqual({}, bad_modes)
        self.assertEqual({}, bad_reasons)

    def test_stop_habit_records_target_mode(self) -> None:
        loaded = registry.load_registry()
        missing_targets = sorted(
            name
            for name, record in loaded.hooks.items()
            if record.mode == "stop" and record.why_mode == "habit" and not record.target_mode
        )
        self.assertEqual([], missing_targets)

    def test_thresholds_are_present(self) -> None:
        loaded = registry.load_registry()
        self.assertEqual(THRESHOLD_KEYS, set(asdict(loaded.thresholds)))

    def test_unreadable_registry_error_names_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry-directory"
            path.mkdir()
            with self.assertRaises(registry.RegistryLoadError) as caught:
                registry.load_registry(path)
            self.assertIn(str(path), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
