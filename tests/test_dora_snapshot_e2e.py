#!/usr/bin/env python3
"""Hermetic e2e for DORA snapshot pipeline (no real sessions, no gh)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "skills", "reflect", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import dora_history  # noqa: E402
import publish_dora_snapshot as publish  # noqa: E402


def _measurement(
    *,
    captured_at: str,
    rework_7d: float,
    rework_30d: float,
    deploy_7d: float = 2.0,
    lead: float = 10.0,
    mttr: float = 100.0,
) -> dict:
    def win(rework: float, deploy: float) -> dict:
        return {
            "window_days": 7.0,
            "hours_scanned": 168.0,
            "lead_pickup": {
                "median_seconds": lead,
                "sample_count": 2,
                "elite": True,
                "threshold_seconds": 900,
            },
            "deploy_frequency": {
                "per_day": deploy,
                "merged": 10,
                "auto": 0,
                "human_asked": 10,
                "human_only": 0,
                "elite": True,
                "threshold_per_day": 2.0,
            },
            "mttr": {
                "median_seconds": mttr,
                "sample_count": 2,
                "elite": True,
                "threshold_seconds": 3600,
            },
            "rework_rate": {
                "rate": rework,
                "started": 10,
                "failed": int(round(rework * 10)),
                "elite": rework < 0.15,
                "threshold": 0.15,
            },
            "post_merge_fail_rate": {
                "rate": 0.0,
                "merged": 10,
                "failed": 0,
                "elite": True,
                "threshold": 0.15,
            },
        }

    return {
        "version": 2,
        "captured_at": captured_at,
        "notes": "fixture",
        "improvement_direction": {
            "lead_pickup.median_seconds": "lower",
            "mttr.median_seconds": "lower",
            "rework_rate.rate": "lower",
            "deploy_frequency.per_day": "higher",
        },
        "windows": {
            "7d": win(rework_7d, deploy_7d),
            "30d": win(rework_30d, deploy_7d / 2),
        },
    }


class TestDoraHistory(unittest.TestCase):
    def test_same_week_dedupe_replace(self):
        hist = {"version": 1, "points": []}
        t0 = "2026-08-25T03:00:00Z"
        t1 = "2026-08-26T12:00:00Z"  # same ISO week
        p0 = dora_history.snapshot_from_measurement(_measurement(captured_at=t0, rework_7d=0.5, rework_30d=0.6))
        p1 = dora_history.snapshot_from_measurement(_measurement(captured_at=t1, rework_7d=0.4, rework_30d=0.5))
        hist, ch = dora_history.append_point(hist, p0)
        self.assertTrue(ch)
        hist, ch = dora_history.append_point(hist, p1, replace_same_week=True)
        self.assertTrue(ch)
        self.assertEqual(len(hist["points"]), 1)
        self.assertEqual(hist["points"][0]["windows"]["7d"]["rework_rate"]["rate"], 0.4)


class TestDoraSnapshotE2E(unittest.TestCase):
    def test_fixture_pipeline_better_updates_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            bdir = os.path.join(repo, "skills", "reflect", "baselines")
            os.makedirs(bdir)
            base = _measurement(
                captured_at="2026-08-11T00:00:00Z",
                rework_7d=0.50,
                rework_30d=0.70,
                deploy_7d=2.0,
            )
            with open(os.path.join(bdir, "dora-ai.json"), "w", encoding="utf-8") as handle:
                json.dump(base, handle)
            # Seed two older weeks
            hist = {"version": 1, "points": []}
            for i, (rework, day) in enumerate(
                ((0.55, 28), (0.52, 21), (0.50, 14))
            ):
                ts = (datetime(2026, 8, 25, tzinfo=timezone.utc) - timedelta(days=day)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                p = dora_history.snapshot_from_measurement(
                    _measurement(captured_at=ts, rework_7d=rework, rework_30d=rework + 0.1)
                )
                hist, _ = dora_history.append_point(hist, p)
            dora_history.save_history(os.path.join(bdir, "dora-ai-history.json"), hist)

            better = _measurement(
                captured_at="2026-08-25T12:00:00Z",
                rework_7d=0.40,
                rework_30d=0.60,
                deploy_7d=3.0,
                lead=5.0,
                mttr=50.0,
            )
            fixture = os.path.join(tmp, "better.json")
            with open(fixture, "w", encoding="utf-8") as handle:
                json.dump(better, handle)

            # apply via publish helper
            result = publish.apply_snapshot(repo, better)
            self.assertTrue(result["baseline_updated"])
            with open(os.path.join(bdir, "dora-ai.json"), encoding="utf-8") as handle:
                updated = json.load(handle)
            self.assertEqual(updated["windows"]["7d"]["rework_rate"]["rate"], 0.40)

            spark = os.path.join(bdir, "charts", "rework-7d.svg")
            self.assertTrue(os.path.isfile(spark))
            with open(spark, encoding="utf-8") as handle:
                svg = handle.read()
            self.assertIn("polyline", svg)
            self.assertIn("elite 15%", svg)

            report = os.path.join(bdir, "dora-ai-report.md")
            with open(report, encoding="utf-8") as handle:
                md = handle.read()
            self.assertIn("40.0%", md)
            self.assertIn("charts/rework-7d.svg", md)

            # dry-run CLI must not invoke gh
            proc = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SCRIPTS, "publish_dora_snapshot.py"),
                    "--repo",
                    repo,
                    "--dry-run",
                    "--fixture-measurement",
                    fixture,
                    "--no-allow-gh",
                ],
                capture_output=True,
                text=True,
                cwd=REPO,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("dry-run", proc.stderr)
            self.assertNotIn("gh pr create", proc.stderr.replace("dry-run skip: gh", ""))

    def test_worse_measurement_keeps_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            bdir = os.path.join(repo, "skills", "reflect", "baselines")
            os.makedirs(bdir)
            base = _measurement(
                captured_at="2026-08-18T00:00:00Z",
                rework_7d=0.30,
                rework_30d=0.40,
                deploy_7d=3.0,
            )
            with open(os.path.join(bdir, "dora-ai.json"), "w", encoding="utf-8") as handle:
                json.dump(base, handle)
            dora_history.save_history(
                os.path.join(bdir, "dora-ai-history.json"), {"version": 1, "points": []}
            )
            worse = _measurement(
                captured_at="2026-08-25T00:00:00Z",
                rework_7d=0.50,
                rework_30d=0.60,
                deploy_7d=3.0,
            )
            result = publish.apply_snapshot(repo, worse)
            self.assertFalse(result["baseline_updated"])
            with open(os.path.join(bdir, "dora-ai.json"), encoding="utf-8") as handle:
                still = json.load(handle)
            self.assertEqual(still["windows"]["7d"]["rework_rate"]["rate"], 0.30)
            hist = dora_history.load_history(os.path.join(bdir, "dora-ai-history.json"))
            self.assertGreaterEqual(len(hist["points"]), 1)


class TestPlistTemplate(unittest.TestCase):
    def test_plist_placeholders_and_lint(self):
        src = os.path.join(SCRIPTS, "com.catstack.dora-snapshot.plist.template")
        self.assertTrue(os.path.isfile(src))
        with open(src, encoding="utf-8") as handle:
            text = handle.read()
        for token in ("__PYTHON3__", "__PUBLISH__", "__HOME__", "__REPO__"):
            self.assertIn(token, text)
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, "com.catstack.dora-snapshot.plist")
            filled = (
                text.replace("__PYTHON3__", "/usr/bin/python3")
                .replace("__PUBLISH__", "/tmp/publish.py")
                .replace("__HOME__", tmp)
                .replace("__REPO__", tmp)
            )
            with open(dst, "w", encoding="utf-8") as handle:
                handle.write(filled)
            if shutil.which("plutil"):
                proc = subprocess.run(
                    ["plutil", "-lint", dst], capture_output=True, text=True
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
