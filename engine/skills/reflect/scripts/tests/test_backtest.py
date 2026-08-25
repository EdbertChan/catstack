#!/usr/bin/env python3
"""Unit tests for backtest.py (frustration-signal backtest runner).

Run: python3 -m unittest discover -s skills/reflect/scripts/tests -v
Synthetic fixtures only — real transcripts never enter the repo.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import backtest  # noqa: E402


def write_jsonl(lines):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for d in lines:
        f.write(json.dumps(d) + "\n")
    f.close()
    return f.name


CLAUDE_LINES = [
    {"type": "user", "timestamp": "2026-08-18T02:30:00Z",
     "message": {"role": "user", "content": "WHERE IS MY DIGITAL TWIN? WHAT THE FUCK IS GOING ON"}},
    {"type": "assistant",
     "message": {"id": "m1", "model": "claude-sonnet-5",
                 "usage": {"input_tokens": 1, "output_tokens": 1},
                 "content": [{"type": "text", "text": "ok"}]}},
]

OMP_LINES = [
    {"type": "message", "timestamp": "2026-08-18T02:30:00Z",
     "message": {"role": "user", "content": [{"type": "text", "text": "calm question about the code"}]}},
    {"type": "message",
     "message": {"role": "assistant", "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0},
                 "content": [{"type": "text", "text": "ok"}]}},
]


class TestSniffMode(unittest.TestCase):
    def test_sniffs_claude(self):
        path = write_jsonl(CLAUDE_LINES)
        try:
            self.assertEqual(backtest.sniff_mode(path), "claude")
        finally:
            os.unlink(path)

    def test_sniffs_omp(self):
        path = write_jsonl(OMP_LINES)
        try:
            self.assertEqual(backtest.sniff_mode(path), "omp")
        finally:
            os.unlink(path)

    def test_garbage_is_unrecognized(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write("not json at all\n{\"type\": \"other\"}\n")
        f.close()
        try:
            self.assertIsNone(backtest.sniff_mode(f.name))
        finally:
            os.unlink(f.name)

    def test_missing_file_is_none(self):
        self.assertIsNone(backtest.sniff_mode("/nonexistent.jsonl"))


class TestSummarize(unittest.TestCase):
    def test_claude_summary_counts_flagged(self):
        path = write_jsonl(CLAUDE_LINES)
        try:
            line = backtest.summarize(path)
            self.assertIn("claude", line)
            self.assertIn("flagged=1/1", line)
            self.assertIn("allcaps", line)
        finally:
            os.unlink(path)

    def test_omp_summary_zero_flagged(self):
        path = write_jsonl(OMP_LINES)
        try:
            line = backtest.summarize(path)
            self.assertIn("omp", line)
            self.assertIn("flagged=0/1", line)
        finally:
            os.unlink(path)

    def test_verbose_includes_excerpts(self):
        path = write_jsonl(CLAUDE_LINES)
        try:
            line = backtest.summarize(path, verbose=True)
            self.assertIn("WHERE IS MY DIGITAL TWIN", line)
        finally:
            os.unlink(path)

    def test_unrecognized_file_is_skipped_not_fatal(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write("garbage\n")
        f.close()
        try:
            self.assertTrue(backtest.summarize(f.name).startswith("SKIP"))
        finally:
            os.unlink(f.name)


class TestMain(unittest.TestCase):
    def test_explicit_paths_print_one_line_each(self):
        p1 = write_jsonl(CLAUDE_LINES)
        p2 = write_jsonl(OMP_LINES)
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                code = backtest.main(["backtest.py", p1, p2])
            self.assertEqual(code, 0)
            out = buf.getvalue().strip().splitlines()
            self.assertEqual(len(out), 2)
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_bad_limit_errors(self):
        code = backtest.main(["backtest.py", "--limit", "nope"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
