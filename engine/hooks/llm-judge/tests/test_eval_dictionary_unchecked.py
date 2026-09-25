#!/usr/bin/env python3
"""A live phrase-dictionary eval reports a case the judge did not answer as unchecked.

Run: python3 -m unittest discover -s engine/hooks/llm-judge/tests -p test_eval_dictionary_unchecked.py -v
"""
import glob
import importlib.util
import inspect
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import judge  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

HOOKS_DIR = os.path.dirname(LIB_DIR)
EVAL_FILES = sorted(glob.glob(os.path.join(HOOKS_DIR, "*", "eval_dictionary.py")))


def load(path):
    name = "eval_dictionary_" + os.path.basename(os.path.dirname(path)).replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CASES = tuple(case for case in module.CASES if case[-1] is False)
    return module


def run_main(module):
    out = io.StringIO()
    args = [[]] if inspect.signature(module.main).parameters else []
    with redirect_stdout(out):
        code = module.main(*args)
    return code, out.getvalue()


class EvalDictionaryUncheckedTestCase(JudgeTestCase):
    def test_glob_finds_every_eval_dictionary(self):
        self.assertGreaterEqual(len(EVAL_FILES), 4, EVAL_FILES)

    def test_every_eval_dictionary_fails_when_no_judge_answers_a_negative_case(self):
        self.assertGreaterEqual(len(EVAL_FILES), 4, EVAL_FILES)
        self.use_runners(["down", [sys.executable, "-c", "import sys; sys.exit(1)", judge.PROMPT_SLOT]])
        for path in EVAL_FILES:
            with self.subTest(path=path):
                code, output = run_main(load(path))
                self.assertEqual(code, 2, output)
                self.assertIn("unchecked", output)

    def test_every_eval_dictionary_passes_when_the_judge_answers_no_match_on_negative_cases(self):
        self.assertGreaterEqual(len(EVAL_FILES), 4, EVAL_FILES)
        for path in EVAL_FILES:
            with self.subTest(path=path):
                code, output = run_main(load(path))
                self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()
