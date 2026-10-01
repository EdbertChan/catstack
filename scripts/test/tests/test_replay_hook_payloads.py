from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "replay_hook_payloads.py"
SPEC = importlib.util.spec_from_file_location("replay_hook_payloads", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReplayHookPayloads(unittest.TestCase):
    def test_replay_reports_match_and_mismatch_per_detector(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payloads = root / "payloads"
            payloads.mkdir()
            (payloads / "0123456789ab-alpha.json").write_bytes(b"alpha")
            (payloads / "0123456789ab-beta.json").write_bytes(b"beta")
            same = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
            different = [sys.executable, "-c", "print('different')"]
            report = MODULE.replay(payloads, {"alpha": same, "beta": same}, {"alpha": same, "beta": different})
            self.assertEqual((report["matched"], report["total"]), (1, 2))
            self.assertEqual([row["match"] for row in report["rows"]], [True, False])
            self.assertIn("stderr", report["rows"][0]["fleet"])

    def test_block_and_findings_are_part_of_equivalence(self):
        with tempfile.TemporaryDirectory() as temp:
            payloads = Path(temp) / "payloads"
            payloads.mkdir()
            (payloads / "0123456789ab-demo.json").write_bytes(b"payload")
            command = [
                sys.executable,
                "-c",
                "import json,os,sys; json.dump(['demo.rule'], open(os.environ['CATSTACK_HOOK_FINDINGS_FILE'], 'w')); print('{\"decision\":\"block\"}'); sys.exit(2)",
            ]
            report = MODULE.replay(payloads, {"demo": command}, {"demo": command})
            row = report["rows"][0]
            self.assertTrue(row["match"])
            self.assertTrue(row["fleet"]["blocked"])
            self.assertEqual(row["fleet"]["findings"], ["demo.rule"])


if __name__ == "__main__":
    unittest.main()
