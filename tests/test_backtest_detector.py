#!/usr/bin/env python3
"""Tests for scripts/backtest_detector.py. Transcripts here are synthetic and built inline."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import backtest_detector as bd  # noqa: E402
from git_test_repo import init_repo  # noqa: E402

STOP_CHECK = str(REPO / "engine" / "hooks" / "diu-stop" / "claude_stop_check.py") + ":find_unverified_claim"


def human(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def said(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def calls(tool_id, name, tool_input):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}]}}


def result(tool_id, text):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def transcript(self, rows, name="s.jsonl", folder=None):
        directory = os.path.join(self.tmp, folder) if folder else self.tmp
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
        return path

    def module(self, name, source):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        return path

    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = bd.main(list(argv))
        return code, out.getvalue()


class TestSingleDetector(Case):
    def test_hits_unverified_claim_in_assistant_text_and_reports_rate(self):
        path = self.transcript([
            human("why is the cache stale"),
            said("Confirmed, the cache is stale."),
            said("Here is the output:\n\n```\nok\n```"),
        ])
        code, out = self.run_main("--detector", STOP_CHECK, path)
        self.assertEqual(code, 0)
        self.assertIn("hits=1/2 kinds=confirmed:1", out)
        self.assertIn("scanned=2 hits=1 hit_rate=50.00%", out)
        self.assertIn("[confirmed]  Confirmed, the cache is stale.", out)

    def test_clean_transcript_reports_zero_hits(self):
        path = self.transcript([human("hi"), said("Here is `ls` output.")])
        code, out = self.run_main("--detector", STOP_CHECK, path)
        self.assertEqual(code, 0)
        self.assertIn("scanned=1 hits=0 hit_rate=0.00%", out)

    def test_paragraph_that_fires_alone_is_a_near_miss_not_a_hit(self):
        path = self.transcript([said("Confirmed, the deploy is `live`.\n\n```\nexit 0\n```")])
        code, out = self.run_main("--detector", STOP_CHECK, path)
        self.assertIn("hits=0 hit_rate=0.00% near_misses=1", out)
        self.assertIn("[confirmed]", out.split("near-misses")[1])

    def test_explicit_near_callable_replaces_the_paragraph_probe(self):
        det = self.module("det.py", "def hit(text):\n    return 'alpha' in text\n\ndef near(text):\n    return 'alp' in text\n")
        path = self.transcript([said("alpha"), said("alp"), said("zzz")])
        code, out = self.run_main("--detector", det + ":hit", "--near", det + ":near", path)
        self.assertIn("scanned=3 hits=1 hit_rate=33.33% near_misses=1", out)

    def test_final_unit_does_not_count_text_followed_by_a_tool_call(self):
        det = self.module("det.py", "def hit(text):\n    return text\n")
        path = self.transcript([
            human("go"),
            said("Checking."),
            calls("t1", "Bash", {"command": "ls"}),
            result("t1", "a"),
            said("Done."),
            human("thanks"),
            said("Done."),
            said("Anything else?"),
        ])
        code, out = self.run_main("--detector", det + ":hit", "--unit", "final", "--verbose", path)
        self.assertIn("hits=2/2", out)
        self.assertIn("[4] Done.", out)
        self.assertIn("[7] Anything else?", out)
        self.assertNotIn("Checking.", out.split("detector:")[0])

    def test_user_unit_skips_tool_results_and_injected_text(self):
        det = self.module("det.py", "def hit(text):\n    return text\n")
        path = self.transcript([
            human("real ask"),
            human("<task-notification>done</task-notification>"),
            result("t1", "tool output"),
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta"}},
            human("[Request interrupted by user]"),
        ])
        code, out = self.run_main("--detector", det + ":hit", "--unit", "user", "--verbose", path)
        self.assertIn("hits=1/1", out)
        self.assertIn("[0] real ask", out)

    def test_tool_unit_passes_hook_payload_and_filters_by_tool(self):
        det = self.module("det.py", "def hit(payload):\n    return 'sleep' in payload['tool_input'].get('command', '') and payload['tool_name']\n")
        path = self.transcript([
            calls("t1", "Bash", {"command": "sleep 90"}),
            calls("t2", "Bash", {"command": "ls"}),
            calls("t3", "Monitor", {"command": "sleep 90"}),
        ])
        code, out = self.run_main("--detector", det + ":hit", "--unit", "tool", "--tool", "Bash", path)
        self.assertIn("hits=1/2 kinds=Bash:1", out)

    def test_rows_unit_takes_verdict_amounts_and_near_flag_from_the_detector(self):
        det = self.module("det.py", (
            "def replay(rows):\n"
            "    for index, row in rows:\n"
            "        text = row.get('text', '')\n"
            "        verdict = {'next_try': 'ok', 'saved': 2} if text == 'hit' else None\n"
            "        yield index, text, verdict, text == 'close'\n"
        ))
        path = self.transcript([{"type": "user", "text": "hit"}, {"type": "user", "text": "close"}, {"type": "user", "text": "far"}])
        code, out = self.run_main("--detector", det + ":replay", "--unit", "rows", path)
        self.assertIn("hits=1/3 kinds=next_try=ok:1 saved=2", out)
        self.assertIn("near_misses=1", out)

    def test_json_report_lists_each_hit(self):
        path = self.transcript([said("Confirmed, it shipped.")])
        out_path = os.path.join(self.tmp, "report.json")
        self.run_main("--detector", STOP_CHECK, "--json", out_path, path)
        with open(out_path, encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["totals"]["hits"], 1)
        self.assertEqual(report["sessions"][0]["hit_units"][0]["verdict"], "confirmed")


class TestUncheckedIsNotClean(Case):
    def test_unrecognized_file_is_skipped_counted_unchecked_and_fails_when_nothing_ran(self):
        path = self.transcript(["not json", json.dumps({"type": "other"})])
        code, out = self.run_main("--detector", STOP_CHECK, path)
        self.assertEqual(code, 1)
        self.assertIn("SKIP (unrecognized format)", out)
        self.assertIn("sessions=1 unchecked=1 scanned=0", out)

    def test_detector_exception_is_reported_unchecked_and_fails_the_run(self):
        det = self.module("det.py", "def boom(text):\n    raise RuntimeError('bad regex')\n")
        good = self.transcript([said("hello")], name="a.jsonl")
        code, out = self.run_main("--detector", det + ":boom", good)
        self.assertEqual(code, 1)
        self.assertIn("ERROR a.jsonl: RuntimeError: bad regex", out)
        self.assertIn("unchecked=1", out)

    def test_spec_without_callable_is_refused(self):
        with self.assertRaises(SystemExit) as caught, redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            bd.main(["--detector", "engine/hooks/diu-stop/claude_stop_check.py"])
        self.assertEqual(caught.exception.code, 2)

    def test_missing_callable_is_refused(self):
        with self.assertRaises(SystemExit) as caught, patch("sys.stderr", io.StringIO()):
            bd.main(["--detector", STOP_CHECK.rsplit(":", 1)[0] + ":no_such_fn", self.tmp])
        self.assertEqual(caught.exception.code, 2)


class TestTranscriptSelection(Case):
    def test_discovery_takes_newest_limit_sessions(self):
        home = os.path.join(self.tmp, "home")
        paths = []
        for i, name in enumerate(("old.jsonl", "mid.jsonl", "new.jsonl")):
            paths.append(self.transcript([said("x")], name=name, folder=os.path.join("home", ".claude", "projects", "p")))
            os.utime(paths[-1], (1000 + i, 1000 + i))
        det = self.module("det.py", "def hit(text):\n    return False\n")
        with patch.dict(os.environ, {"HOME": home, "TMPDIR": self.tmp}):
            code, out = self.run_main("--detector", det + ":hit", "--limit", "2")
        self.assertIn("new.jsonl", out)
        self.assertIn("mid.jsonl", out)
        self.assertNotIn("old.jsonl", out)
        self.assertIn("sessions=2", out)

    def test_explicit_paths_override_discovery_and_directories_expand(self):
        folder = os.path.dirname(self.transcript([said("x")], name="a.jsonl", folder="d"))
        self.transcript([said("y")], name="b.jsonl", folder="d")
        self.transcript([said("z")], name="c.jsonl")
        det = self.module("det.py", "def hit(text):\n    return False\n")
        with patch.object(bd, "discover", side_effect=AssertionError("discovery ran")):
            code, out = self.run_main("--detector", det + ":hit", folder)
        self.assertIn("sessions=2", out)
        self.assertNotIn("c.jsonl", out)

    def test_rows_are_streamed_not_loaded_whole(self):
        fifo = os.path.join(self.tmp, "live.jsonl")
        os.mkfifo(fifo)
        first_seen = threading.Event()
        rest_written_after_first = []

        def writer():
            with open(fifo, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(said("one")) + "\n")
                handle.flush()
                rest_written_after_first.append(first_seen.wait(5))
                handle.write(json.dumps(said("two")) + "\n")

        thread = threading.Thread(target=writer)
        thread.start()
        rows = bd.iter_rows(fifo)
        started = time.monotonic()
        index, row = next(rows)
        first_seen.set()
        self.assertEqual((index, bd.shape(row, "claude")[1]), (0, "one"))
        self.assertEqual(next(rows)[0], 1)
        thread.join()
        self.assertEqual(rest_written_after_first, [True])
        self.assertLess(time.monotonic() - started, 4)


class TestCompare(Case):
    def test_compare_two_paths_reports_caught_missed_and_unchanged(self):
        old = self.module("old.py", "def hit(text):\n    return 'alpha' in text or 'beta' in text\n")
        new = self.module("new.py", "def hit(text):\n    return 'alpha' in text or 'gamma' in text\n")
        path = self.transcript([said("alpha"), said("beta"), said("gamma"), said("delta")])
        code, out = self.run_main("--detector", new + ":hit", "--compare", old + ":hit", path)
        self.assertEqual(code, 0)
        self.assertIn("hits=2/4 was=2/4 caught=1 missed=1", out)
        self.assertIn("newly_caught=1 newly_missed=1 unchanged=1", out)
        self.assertIn("gamma", out.split("newly caught (")[1].split("newly missed")[0])
        self.assertIn("beta", out.split("newly missed (")[1])

    def test_compare_against_git_ref_loads_that_revision_and_its_siblings(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "hook"))
        init_repo(repo)
        with open(os.path.join(repo, "hook", "words.py"), "w", encoding="utf-8") as handle:
            handle.write("WORDS = ('alpha',)\n")
        with open(os.path.join(repo, "hook", "detect.py"), "w", encoding="utf-8") as handle:
            handle.write("from words import WORDS\n\ndef hit(text):\n    return next((w for w in WORDS if w in text), None)\n")
        git = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git + ["add", "."], check=True, capture_output=True)
        subprocess.run(git + ["commit", "-qm", "v1"], check=True, capture_output=True)
        with open(os.path.join(repo, "hook", "words.py"), "w", encoding="utf-8") as handle:
            handle.write("WORDS = ('alpha', 'gamma')\n")
        path = self.transcript([said("alpha"), said("gamma"), said("delta")])
        det = os.path.join(repo, "hook", "detect.py") + ":hit"
        code, out = self.run_main("--detector", det, "--compare", "HEAD", path)
        self.assertEqual(code, 0, out)
        self.assertIn("detect.py@HEAD:hit", out)
        self.assertIn("newly_caught=1 newly_missed=0 unchanged=1", out)
        self.assertIn("[gamma]", out)

    def test_loading_uses_the_detectors_own_sibling_and_restores_the_callers(self):
        folder = os.path.join(self.tmp, "hook")
        os.makedirs(folder)
        with open(os.path.join(folder, "words.py"), "w", encoding="utf-8") as handle:
            handle.write("WORDS = ('alpha',)\n")
        path = self.module(os.path.join("hook", "detect.py"), "from words import WORDS\n\ndef hit(text):\n    return text in WORDS\n")
        callers = types.ModuleType("words")
        callers.WORDS = ("zzz",)
        with patch.dict(sys.modules, {"words": callers}):
            detector = bd.load_callable(path, "hit")
            self.assertIs(sys.modules["words"], callers)
        self.assertTrue(detector.fn("alpha"))
        self.assertFalse(detector.fn("zzz"))

    def test_compare_with_unknown_revision_is_refused(self):
        with self.assertRaises(SystemExit) as caught, patch("sys.stderr", io.StringIO()):
            bd.main(["--detector", STOP_CHECK, "--compare", "no-such-ref-xyz", self.tmp])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
