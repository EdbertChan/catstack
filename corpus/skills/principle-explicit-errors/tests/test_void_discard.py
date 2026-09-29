"""The skill's discard rule is the same check the failure hook runs."""
from __future__ import annotations

import os
import sys
import unittest

HOOK_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "engine", "hooks", "explicit-failures")
)
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402


class VoidDiscardTest(unittest.TestCase):
    def test_void_only_catch_is_reported(self):
        text = "try { a() } catch (err) {\n  void err;\n}\n"
        hits = detect.scan_js(text)
        self.assertEqual(hits, [(1, "catch block that only discards the error with `void`")])

    def test_logged_catch_is_quiet(self):
        text = "try { a() } catch (err) {\n  console.error('failed', err);\n}\n"
        self.assertEqual(detect.scan_js(text), [])


if __name__ == "__main__":
    unittest.main()
