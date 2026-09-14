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
        })
        self.judge_env.start()
        os.environ.pop(judge.CHILD_ENV, None)

    def tearDown(self):
        self.judge_env.stop()
        self.state.cleanup()
        super().tearDown()

    def use_runners(self, *entries):
        os.environ[judge.RUNNERS_ENV] = json.dumps(list(entries))
