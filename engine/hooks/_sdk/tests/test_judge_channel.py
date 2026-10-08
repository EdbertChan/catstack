from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import judge_channel as jc
from judge_channel import CLEAN, HIT, UNCHECKED

CONFIG = jc.ChannelConfig(hook="demo-hook", id_prefix="dh", state_env="DEMO_HOOK_STATE_DIR", cache_dirname="demo-hook-cache")


class JudgeChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ[CONFIG.state_env] = self.tmp.name
        self.addCleanup(os.environ.pop, CONFIG.state_env, None)

    def test_job_id_keeps_the_fanout_routing_guard_format(self):
        config = jc.ChannelConfig("fanout-routing-guard", "frg", "X", "y")
        expected_checker = hashlib.sha256(b"checker").hexdigest()[:16]
        expected_text = hashlib.sha256(b"/t\x00text").hexdigest()[:16]
        self.assertEqual(jc.job_id(config, "checker", "/t", "text"), f"frg-{expected_checker}-{expected_text}")

    def test_channel_is_private_to_the_hook(self):
        self.assertEqual(jc.channel(CONFIG, "/t.jsonl"), "/t.jsonl#demo-hook")

    def test_cache_round_trips_and_expires_unchecked_sooner(self):
        now = time.time()
        cache = {
            "a": {"outcome": HIT, "at": now - 100},
            "b": {"outcome": UNCHECKED, "at": now - jc.UNCHECKED_TTL_SECONDS - 1},
            "c": {"outcome": CLEAN, "at": now - jc.UNCHECKED_TTL_SECONDS - 1},
        }
        jc.save_cache(CONFIG, "/t", cache)
        self.assertEqual(sorted(jc.load_cache(CONFIG, "/t", now)), ["a", "c"])

    def test_cache_drops_future_dated_and_wrong_typed_entries(self):
        now = time.time()
        jc.save_cache(CONFIG, "/t", {
            "future": {"outcome": HIT, "at": now + 500},
            "bool": {"outcome": HIT, "at": True},
            "bad": {"outcome": "maybe", "at": now},
            "plain": "x",
        })
        self.assertEqual(jc.load_cache(CONFIG, "/t", now), {})

    def test_malformed_cache_is_treated_empty_and_logged(self):
        path = jc.state_path(CONFIG, "/t")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text("{not json", encoding="utf-8")
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(jc.load_cache(CONFIG, "/t", time.time()), {})
        self.assertIn("demo-hook: unreadable verdict cache", err.getvalue())

    def test_missing_cache_is_empty_without_noise(self):
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(jc.load_cache(CONFIG, "/never-written", time.time()), {})
        self.assertEqual(err.getvalue(), "")

    def test_await_verdicts_marks_missing_verdicts_unchecked_at_the_deadline(self):
        verdicts = jc.Verdicts.__new__(jc.Verdicts)
        verdicts.config, verdicts.transcript, verdicts.cache, verdicts.reasons = CONFIG, "/t", {}, {}
        verdicts.collect = lambda: None
        result = jc.await_verdicts(verdicts, ["j1"], lambda: verdicts.outcome("j1"), 0)
        self.assertEqual(result, UNCHECKED)
        self.assertIn("no verdict within", verdicts.reasons["j1"])

    def test_wait_seconds_reads_the_env_and_logs_a_bad_value(self):
        os.environ["DEMO_WAIT"] = "2.5"
        self.addCleanup(os.environ.pop, "DEMO_WAIT", None)
        self.assertEqual(jc.wait_seconds("DEMO_WAIT", 9.0), 2.5)
        os.environ["DEMO_WAIT"] = "soon"
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(jc.wait_seconds("DEMO_WAIT", 9.0), 9.0)
        self.assertIn("DEMO_WAIT", err.getvalue())


if __name__ == "__main__":
    unittest.main()
