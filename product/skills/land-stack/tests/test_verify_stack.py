#!/usr/bin/env python3
"""Tests for verify_stack.py against a real `gh pr list` payload.

fixtures/invoker_open_prs_2026-09-01.json is the verbatim output of
`gh pr list -R Neko-Catpital-Labs/Invoker --state open --json ...` captured
2026-09-01. It contains a real 6-PR stack (#7006 -> #7007 -> #7010 -> #7011
-> #7028 -> #7029) and a real 5-PR stack (#11557..#11561).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import verify_stack as vs  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "invoker_open_prs_2026-09-01.json")
SLACK_STACK = [7006, 7007, 7010, 7011, 7028, 7029]
LOCAL_INVOKER = os.path.expanduser("~/Documents/GitHub/Invoker")


def load():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


ALWAYS = lambda sha: True  # noqa: E731
NEVER = lambda sha: False  # noqa: E731


class TestVerifyPasses(unittest.TestCase):
    def test_real_slack_stack_passes_in_order(self):
        self.assertEqual(vs.verify(load(), SLACK_STACK, trunk="master", branch_prefix="stack/", sha_exists=ALWAYS), [])

    def test_real_typed_task_freshness_stack_passes(self):
        self.assertEqual(vs.verify(load(), [11557, 11558, 11559, 11560, 11561], trunk="master",
                                   branch_prefix="stack/", sha_exists=ALWAYS), [])

    @unittest.skipUnless(os.path.isdir(LOCAL_INVOKER), "local Invoker clone not present")
    def test_real_head_shas_exist_in_local_clone(self):
        prs = {p["number"]: p for p in load()}
        for n in SLACK_STACK:
            with self.subTest(pr=n):
                self.assertTrue(vs.sha_exists_locally(prs[n]["headRefOid"], LOCAL_INVOKER))


class TestVerifyBlocks(unittest.TestCase):
    def test_blocks_wrong_order(self):
        fails = vs.verify(load(), [7007, 7006], trunk="master", branch_prefix="stack/", sha_exists=ALWAYS)
        self.assertTrue(any("#7007: base is" in f and "(trunk)" in f for f in fails), fails)
        self.assertTrue(any("#7006: base is" in f for f in fails), fails)

    def test_blocks_sha_missing_locally(self):
        fails = vs.verify(load(), [7006], trunk="master", branch_prefix="stack/", sha_exists=NEVER)
        self.assertEqual(len(fails), 1)
        self.assertIn("not in the local clone", fails[0])

    def test_blocks_non_stack_branch(self):
        prs = load() + [{"number": 1, "baseRefName": "master", "headRefName": "codex/auto-fix",
                         "headRefOid": "deadbeef" * 5, "title": "x", "state": "OPEN"}]
        fails = vs.verify(prs, [1], trunk="master", branch_prefix="stack/", sha_exists=ALWAYS)
        self.assertTrue(any("does not match stack convention" in f for f in fails), fails)

    def test_blocks_closed_or_unknown_pr(self):
        fails = vs.verify(load(), [7006, 99999], trunk="master", branch_prefix="stack/", sha_exists=ALWAYS)
        self.assertTrue(any("#99999: not in the open PR list" in f for f in fails), fails)

    def test_blocks_skipped_middle_pr(self):
        fails = vs.verify(load(), [7006, 7010], trunk="master", branch_prefix="stack/", sha_exists=ALWAYS)
        self.assertTrue(any("#7010: base is" in f for f in fails), fails)


class TestDiscover(unittest.TestCase):
    def test_discovers_the_real_slack_stack(self):
        result = vs.discover(load(), trunk="master", branch_prefix="stack/", sha_exists=ALWAYS)
        self.assertIn(SLACK_STACK, result["stacks"])
        self.assertIn([11557, 11558, 11559, 11560, 11561], result["stacks"])
        self.assertEqual(result["duplicates"], {})

    def test_flags_duplicate_head_branches_for_confirmation(self):
        prs = load()
        dup = dict(prs[0]); dup["number"] = 424242
        result = vs.discover(prs + [dup], trunk="master", branch_prefix="stack/", sha_exists=ALWAYS)
        self.assertEqual(list(result["duplicates"].values()), [[prs[0]["number"], 424242]])

    def test_cli_exit_codes(self):
        script = os.path.join(os.path.dirname(HERE), "scripts", "verify_stack.py")
        ok = subprocess.run([sys.executable, script, "--prs-json", FIXTURE, "--git-dir", LOCAL_INVOKER if os.path.isdir(LOCAL_INVOKER) else HERE]
                            + [str(n) for n in SLACK_STACK], capture_output=True, text=True)
        bad = subprocess.run([sys.executable, script, "--prs-json", FIXTURE, "7007", "7006"], capture_output=True, text=True)
        if os.path.isdir(LOCAL_INVOKER):
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("ok      stack verified", ok.stdout)
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn("fail", bad.stdout)


if __name__ == "__main__":
    unittest.main()
