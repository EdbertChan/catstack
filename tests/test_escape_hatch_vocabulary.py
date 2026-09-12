#!/usr/bin/env python3
"""No rule or skill tells an author to write the retired bare `UNVERIFIED:`.

Every evidence hook clears on the `{{CAT-UNVERIFIED}}` tag and nothing else,
so prose that still says "write `UNVERIFIED:`" sends an agent into a block.

Run: python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import escape_hatch_vocab as vocab  # noqa: E402


class InstructionalProseUsesTheTag(unittest.TestCase):
    def test_no_instructional_file_names_the_retired_marker(self):
        offenders = []
        for path in vocab.instructional_files():
            with open(path, encoding="utf-8") as handle:
                for line in vocab.instructs_retired_marker(handle.read()):
                    offenders.append(f"{os.path.relpath(path, vocab.REPO_ROOT)}: {line[:100]}")
        self.assertEqual(offenders, [])

    def test_scan_covers_the_always_loaded_rules(self):
        scanned = {os.path.relpath(p, vocab.REPO_ROOT) for p in vocab.instructional_files()}
        for rel in ("engine/CLAUDE.core.md", "corpus/CLAUDE.learned.md", "always-on/evidence-check.md"):
            self.assertIn(rel, scanned)


class DetectorShape(unittest.TestCase):
    def test_bare_marker_instruction_is_flagged(self):
        self.assertEqual(len(vocab.instructs_retired_marker("- Prefix `UNVERIFIED:` until then.")), 1)

    def test_tag_is_not_flagged(self):
        text = "Tag it `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}`."
        self.assertEqual(vocab.instructs_retired_marker(text), [])

    def test_line_calling_the_marker_retired_is_not_flagged(self):
        self.assertEqual(vocab.instructs_retired_marker("Bare `UNVERIFIED:` is retired."), [])

    def test_other_uses_of_the_word_are_not_flagged(self):
        text = "| Codex | UNVERIFIED schema | UNVERIFIED end-to-end |"
        self.assertEqual(vocab.instructs_retired_marker(text), [])


if __name__ == "__main__":
    unittest.main()
