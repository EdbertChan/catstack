from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_install_effective.py"
SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

from events import write_events


def load_checker():
    spec = importlib.util.spec_from_file_location("check_install_effective_identity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class IdentityEmitCanaryTest(unittest.TestCase):
    def test_install_effective_identity_probe_requires_nonblank_model(self) -> None:
        module = load_checker()
        problems = module.check_identity_emit()
        self.assertEqual([], problems)

    def test_post_install_probe_event_carries_nonblank_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": tmp, "CATSTACK_HOOK_TEST_MODEL": ""},
            clear=False,
        ):
            rows = write_events(
                "identity-canary",
                "claude",
                {"session_id": "canary-session", "model": "claude-sonnet-5"},
                [],
                "warn",
                "canary",
                0,
            )
            blank = write_events(
                "identity-canary",
                "claude",
                {"session_id": "canary-blank"},
                [],
                "warn",
                "canary",
                0,
            )

        self.assertEqual(1, len(rows))
        self.assertTrue(str(rows[0]["model"]).strip())
        self.assertNotEqual("<synthetic>", rows[0]["model"])
        self.assertEqual([], blank)


if __name__ == "__main__":
    unittest.main()
