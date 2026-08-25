#!/usr/bin/env python3
"""Tests for check_dora_baseline.py."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "check_dora_baseline.py")


def _blob(lead: float, deploy: float, mttr: float, rework: float) -> dict:
    return {
        "version": 2,
        "improvement_direction": {
            "lead_pickup.median_seconds": "lower",
            "mttr.median_seconds": "lower",
            "rework_rate.rate": "lower",
            "deploy_frequency.per_day": "higher",
        },
        "windows": {
            "7d": {
                "lead_pickup": {"median_seconds": lead},
                "deploy_frequency": {"per_day": deploy},
                "mttr": {"median_seconds": mttr},
                "rework_rate": {"rate": rework},
            }
        },
    }


class TestDoraBaselineGate(unittest.TestCase):
    def test_regression_when_rework_goes_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "base.json")
            cur = os.path.join(tmp, "cur.json")
            with open(base, "w", encoding="utf-8") as handle:
                json.dump(_blob(100, 2.0, 200, 0.2), handle)
            with open(cur, "w", encoding="utf-8") as handle:
                json.dump(_blob(90, 2.5, 180, 0.3), handle)  # rework up
            result = subprocess.run(
                ["python3", SCRIPT, "--baseline", base, "--current", cur],
                capture_output=True,
                text=True,
                cwd=REPO,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("rework_rate", result.stdout)

    def test_passes_when_all_improve(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "base.json")
            cur = os.path.join(tmp, "cur.json")
            with open(base, "w", encoding="utf-8") as handle:
                json.dump(_blob(100, 2.0, 200, 0.2), handle)
            with open(cur, "w", encoding="utf-8") as handle:
                json.dump(_blob(80, 3.0, 150, 0.1), handle)
            result = subprocess.run(
                ["python3", SCRIPT, "--baseline", base, "--current", cur],
                capture_output=True,
                text=True,
                cwd=REPO,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_post_merge_not_gated(self):
        """Fix-forward: post_merge_fail_rate must not block even if present and worse."""
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "base.json")
            cur = os.path.join(tmp, "cur.json")
            base_blob = _blob(100, 2.0, 200, 0.2)
            base_blob["windows"]["7d"]["post_merge_fail_rate"] = {"rate": 0.0}
            cur_blob = _blob(90, 2.5, 180, 0.15)
            cur_blob["windows"]["7d"]["post_merge_fail_rate"] = {"rate": 0.9}
            with open(base, "w", encoding="utf-8") as handle:
                json.dump(base_blob, handle)
            with open(cur, "w", encoding="utf-8") as handle:
                json.dump(cur_blob, handle)
            result = subprocess.run(
                ["python3", SCRIPT, "--baseline", base, "--current", cur],
                capture_output=True,
                text=True,
                cwd=REPO,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
