#!/usr/bin/env python3
"""The codex runner's model comes from Codex's own catalog, never a fixed slug.

Run: python3 -m unittest discover -s engine/hooks/llm-judge/tests -v

A fixed slug stops answering the day the login stops offering it, and every
judge call then reports "could not judge". These tests stand in a fake
`codex debug models` and a fake config, and pin which `-m` the runner gets.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import judge  # noqa: E402

PY = sys.executable
CATALOG = {"models": [
    {"slug": "big-model", "visibility": "list", "priority": 1},
    {"slug": "hidden-model", "visibility": "hide", "priority": 0},
    {"slug": "fast-model", "visibility": "list", "priority": 8},
]}


def catalog_argv(payload, code=0):
    return (PY, "-c", f"import sys; print({json.dumps(payload)!r}); sys.exit({code})")


class CodexModelTestCase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.work.name, "config.toml")
        self.env = patch.dict(os.environ, {judge.STATE_ENV: self.work.name})
        self.env.start()
        os.environ.pop(judge.RUNNERS_ENV, None)
        self.config_path = patch.object(judge, "codex_config_path", return_value=self.config)
        self.config_path.start()

    def tearDown(self):
        self.config_path.stop()
        self.env.stop()
        self.work.cleanup()

    def configure(self, model):
        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write(f'model = "{model}"\n')

    def codex_argv(self):
        return dict(judge.runners())["codex"]

    def judge_log(self):
        path = os.path.join(self.work.name, "judge.log")
        return open(path, encoding="utf-8").read() if os.path.exists(path) else ""

    def test_listed_configured_model_is_left_to_codex(self):
        self.configure("fast-model")
        with patch.object(judge, "CODEX_CATALOG_ARGV", catalog_argv(CATALOG)):
            argv = self.codex_argv()
        self.assertNotIn("-m", argv)

    def test_no_configured_model_gets_first_listed(self):
        with patch.object(judge, "CODEX_CATALOG_ARGV", catalog_argv(CATALOG)):
            argv = self.codex_argv()
        self.assertEqual(argv[:5], ["codex", "exec", "--skip-git-repo-check", "-m", "big-model"])

    def test_unlisted_configured_model_falls_back_to_first_listed(self):
        self.configure("gpt-5.3-codex-spark")
        with patch.object(judge, "CODEX_CATALOG_ARGV", catalog_argv(CATALOG)):
            argv = self.codex_argv()
        self.assertIn("big-model", argv)
        self.assertNotIn("gpt-5.3-codex-spark", argv)
        self.assertIn("not in the catalog", self.judge_log())

    def test_hidden_models_are_never_picked(self):
        with patch.object(judge, "CODEX_CATALOG_ARGV", catalog_argv(CATALOG)):
            self.assertNotIn("hidden-model", self.codex_argv())

    def test_default_runner_carries_no_fixed_model(self):
        codex = dict(judge.DEFAULT_RUNNERS)["codex"]
        self.assertNotIn("-m", codex)

    def test_unreadable_catalog_omits_model_and_logs_it(self):
        with patch.object(judge, "CODEX_CATALOG_ARGV", catalog_argv({"oops": 1}, code=2)):
            argv = self.codex_argv()
        self.assertNotIn("-m", argv)
        self.assertIn("catalog unreadable", self.judge_log())

    def test_malformed_catalog_json_omits_model_and_logs_it(self):
        with patch.object(judge, "CODEX_CATALOG_ARGV", (PY, "-c", "print('not json')")):
            argv = self.codex_argv()
        self.assertNotIn("-m", argv)
        self.assertIn("catalog unreadable", self.judge_log())

    def test_runner_override_env_is_left_alone(self):
        with patch.dict(os.environ, {judge.RUNNERS_ENV: json.dumps([["codex", ["codex", "{prompt}"]]])}):
            self.assertEqual(self.codex_argv(), ["codex", "{prompt}"])

    def test_investigate_runners_are_left_alone(self):
        with patch.object(judge, "CODEX_CATALOG_ARGV", catalog_argv(CATALOG)):
            codex = dict(judge.runners("investigate"))["codex"]
        self.assertNotIn("-m", codex)


if __name__ == "__main__":
    unittest.main()


class BenchFollowsTheCommandTestCase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {judge.STATE_ENV: self.work.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.work.cleanup()

    def test_bench_for_the_same_command_still_applies(self):
        argv = ["codex", "exec", "-m", "fast-model", "{prompt}"]
        judge.mark_unavailable("codex", "exit 1", argv)
        self.assertGreater(judge.unavailable_until("codex", argv), 0)

    def test_bench_earned_by_an_old_model_does_not_block_a_new_one(self):
        judge.mark_unavailable("codex", "exit 1: model not supported", ["codex", "exec", "-m", "gpt-5.3-codex-spark", "{prompt}"])
        self.assertEqual(judge.unavailable_until("codex", ["codex", "exec", "-m", "fast-model", "{prompt}"]), 0.0)

    def test_marker_with_no_recorded_command_does_not_block(self):
        judge.write_json_atomic(judge.unavailable_path("codex"), {"runner": "codex", "until": 9e12, "reason": "exit 1"})
        self.assertEqual(judge.unavailable_until("codex", ["codex", "{prompt}"]), 0.0)
