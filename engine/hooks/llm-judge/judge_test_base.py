from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import judge


class JudgeTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.state = tempfile.TemporaryDirectory()
        self.judge_env = patch.dict(os.environ, {
            judge.STATE_ENV: self.state.name,
            judge.RUNNERS_ENV: json.dumps([
                ["stub", [sys.executable, "-c", "print('{\"match\": false}')", judge.PROMPT_SLOT]],
            ]),
            "CATSTACK_HOOK_METRICS_DIR": os.path.join(self.state.name, "metrics"),
        })
        self.judge_env.start()
        os.environ.pop(judge.CHILD_ENV, None)
        # Never ask this machine's codex for its models or read its config:
        # a fixed catalog, and a config naming its first entry.
        self.codex_catalog = ["catalog-first", "catalog-second"]
        codex_home = tempfile.TemporaryDirectory()
        self.addCleanup(codex_home.cleanup)
        self.codex_config = os.path.join(codex_home.name, "config.toml")
        with open(self.codex_config, "w", encoding="utf-8") as handle:
            handle.write('model = "catalog-first"\n')
        for name, stub in (
            ("codex_listed_models", lambda: list(self.codex_catalog)),
            ("codex_config_path", lambda: self.codex_config),
        ):
            patcher = patch.object(judge, name, stub)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.judge_env.stop()
        self.state.cleanup()
        super().tearDown()

    def use_runners(self, *entries):
        os.environ[judge.RUNNERS_ENV] = json.dumps(list(entries))
