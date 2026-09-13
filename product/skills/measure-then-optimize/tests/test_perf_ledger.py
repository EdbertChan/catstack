import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "product/skills/measure-then-optimize/scripts/perf_ledger.py"
CASES = pathlib.Path(__file__).with_name("cases.json")


class PerfLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASES.read_text())

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def judge_case(self, case):
        with tempfile.TemporaryDirectory() as directory:
            ledger = pathlib.Path(directory) / "ledger.json"
            ledger.write_text(json.dumps(case["ledger"]))
            result = self.run_cli("judge", str(ledger))
        self.assertEqual(result.returncode, {"pass": 0, "fail": 1, "unchecked": 2}[case["expected"]["verdict"]])
        self.assertEqual(json.loads(result.stdout), {"verdict": case["expected"]["verdict"], "reasons": sorted(case["expected"]["reasons"])})

    def test_record_wall_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = pathlib.Path(directory) / "ledger.json"
            result = self.run_cli("record", "--ledger", str(ledger), "--phase", "baseline", "--metric", "boot_seconds", "--runs", "3", "--setting", "host=local", "--", sys.executable, "-c", "pass")
            self.assertEqual(result.returncode, 0)
            data = json.loads(ledger.read_text())
            self.assertEqual(data["baseline"]["metric"], "boot_seconds")
            self.assertEqual(data["baseline"]["settings"], {"host": "local"})
            self.assertEqual(len(data["baseline"]["runs"]), 3)
            self.assertTrue(all(isinstance(value, (int, float)) for value in data["baseline"]["runs"]))

    def test_record_from_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = pathlib.Path(directory) / "ledger.json"
            result = self.run_cli("record", "--ledger", str(ledger), "--phase", "after", "--metric", "boot_seconds", "--runs", "2", "--from-stdout", "--symptom-metric", "boot_seconds", "--lever-path", "bench.py", "--", sys.executable, "-c", "print('ignored'); print(12.5)")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(ledger.read_text())["after"]["runs"], [12.5, 12.5])

    def test_record_failure_leaves_ledger_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = pathlib.Path(directory) / "ledger.json"
            original = '{"sentinel": true}\n'
            ledger.write_text(original)
            result = self.run_cli("record", "--ledger", str(ledger), "--phase", "after", "--metric", "boot_seconds", "--runs", "2", "--", sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(3)")
            self.assertEqual(result.returncode, 2)
            self.assertIn("bad", result.stderr)
            self.assertEqual(ledger.read_text(), original)


def make_case_test(case):
    return lambda self: self.judge_case(case)


for case in json.loads(CASES.read_text()):
    setattr(PerfLedgerTests, "test_case_" + case["id"], make_case_test(case))


if __name__ == "__main__":
    unittest.main()
