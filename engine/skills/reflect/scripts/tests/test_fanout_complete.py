#!/usr/bin/env python3
"""A reflect fan-out is complete only when every launched lens reported.

The failure this exists to stop: a lens dies, the survivors return findings,
and step 5 applies them as though the pass were whole. Unreturned reviewers are
not reviewers that passed.

The `unchecked` outcome is pinned as a non-pass on purpose. A fan-out whose
expected set nobody recorded cannot be called complete, and a check that could
not run must not read as clean.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import fanout_complete as fc  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "fanout_complete.py")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class TestVerdict(unittest.TestCase):
    def test_every_lens_returned_is_complete(self):
        self.assertEqual(fc.verdict(["a", "b"], ["b", "a"])[0], fc.COMPLETE)

    def test_a_missing_lens_is_incomplete_and_named(self):
        outcome, missing, _ = fc.verdict(["a", "b", "c"], ["a"])
        self.assertEqual(outcome, fc.INCOMPLETE)
        self.assertEqual(missing, ["b", "c"])

    def test_no_expected_set_is_unchecked_not_complete(self):
        """The whole point: nothing recorded cannot mean nothing missing."""
        self.assertEqual(fc.verdict([], ["a", "b"])[0], fc.UNCHECKED)
        self.assertNotEqual(fc.verdict([], ["a", "b"])[0], fc.COMPLETE)

    def test_a_lens_nobody_expected_does_not_fill_a_gap(self):
        outcome, missing, unexpected = fc.verdict(["a", "b"], ["a", "zzz"])
        self.assertEqual(outcome, fc.INCOMPLETE)
        self.assertEqual(missing, ["b"])
        self.assertEqual(unexpected, ["zzz"])

    def test_duplicate_returns_do_not_count_twice(self):
        self.assertEqual(fc.verdict(["a", "b"], ["a", "a"])[0], fc.INCOMPLETE)


class TestExitCodes(unittest.TestCase):
    """Exit codes are the contract a caller gates on, so they are pinned."""

    def test_complete_exits_zero(self):
        self.assertEqual(run("--expected", "a", "--returned", "a").returncode, 0)

    def test_incomplete_exits_nonzero_and_names_the_lens(self):
        res = run("--expected", "a", "b", "--returned", "a")
        self.assertEqual(res.returncode, 1)
        self.assertIn("b", res.stdout)

    def test_unchecked_exits_nonzero(self):
        """`unchecked` must not be usable as a pass by a caller reading $?."""
        self.assertEqual(run("--returned", "a").returncode, 2)

    def test_json_carries_the_outcome_and_the_missing_lenses(self):
        res = run("--expected", "a", "b", "--returned", "a", "--json")
        payload = json.loads(res.stdout)
        self.assertEqual(payload["outcome"], "incomplete")
        self.assertEqual(payload["missing"], ["b"])


class TestManifest(unittest.TestCase):
    def test_manifest_drives_the_same_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"expected": ["a", "b"], "returned": ["a"]}, handle)
            res = run("--manifest", path)
            self.assertEqual(res.returncode, 1)
            self.assertIn("b", res.stdout)

    def test_manifest_without_an_expected_list_is_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"returned": ["a"]}, handle)
            self.assertEqual(run("--manifest", path).returncode, 2)


if __name__ == "__main__":
    unittest.main()
