#!/usr/bin/env python3
"""The learned evidence rules must carry the enumerate-before-you-fix
procedure as an ordered, attributed, citable eight steps -- not as a slogan.

A prose rule that names no method and no source is the shape that already
lost: three always-loaded surfaces told this session to prove the real path
and it shipped four unproven fixes anyway. These assertions pin the parts
that make the rule checkable by a reader: every step present, every step
attributed to the method it came from, and every method resolvable to an
author/title/year/URL that was actually fetched.
"""
import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNED = os.path.join(REPO_ROOT, "corpus", "CLAUDE.learned.md")

STEP_ATTRIBUTIONS = [
    (1, "[IEC 61882:2016 cl. 4.2]"),
    (2, "[IEC 61882:2016 cl. 4.2, Tables 1–2]"),
    (3, "[Google SRE ch. 12]"),
    (4, "[IEC 61882:2016 cl. 4.1]"),
    (5, "[Cook #3; Leveson CAST]"),
    (6, "[Gano — ARMS Reliability 2016]"),
    (7, "[Liblit et al. 2005]"),
    (8, "[IEC 61882 — HAZOP records are reusable]"),
]

CITATION_URLS = [
    "https://webstore.iec.ch/en/publication/24321",
    "https://sre.google/sre-book/effective-troubleshooting/",
    "https://www.adaptivecapacitylabs.com/HowComplexSystemsFail.pdf",
    "https://blog.armsreliability.com/blog/actions-or-conditions-what-is-the-difference-and-why-does-it-matter",
    "https://theory.stanford.edu/~aiken/publications/papers/pldi05.pdf",
    "https://psas.scripts.mit.edu/home/get_file4.php?name=CAST_Handbook.pdf",
]

GUIDE_WORDS = [
    "NO/NOT", "MORE", "LESS", "AS WELL AS", "PART OF", "REVERSE",
    "OTHER THAN", "EARLY", "LATE", "BEFORE", "AFTER",
]


def read_learned():
    with open(LEARNED, encoding="utf-8") as handle:
        return handle.read()


class TestHazopProcedure(unittest.TestCase):
    def setUp(self):
        self.text = read_learned()

    def test_eight_numbered_steps_each_carry_their_method_attribution(self):
        for number, attribution in STEP_ATTRIBUTIONS:
            with self.subTest(step=number):
                pattern = re.compile(
                    rf"^\s*{number}\.\s+\*\*.+?\*\*\s+{re.escape(attribution)}",
                    re.MULTILINE,
                )
                self.assertRegex(self.text, pattern)

    def test_every_cited_method_resolves_to_a_fetched_source_url(self):
        for url in CITATION_URLS:
            with self.subTest(url=url):
                self.assertIn(url, self.text)

    def test_guide_word_matrix_lists_every_iec_61882_guide_word(self):
        for word in GUIDE_WORDS:
            with self.subTest(word=word):
                self.assertIn(word, self.text)

    def test_defect_count_is_published_before_the_first_fix_commit(self):
        self.assertIn("rca/defect_count", self.text)
        self.assertIn("before the first fix commit", self.text)

    def test_leveson_whack_a_mole_passage_is_quoted_verbatim(self):
        self.assertIn(
            "we play a sophisticated 'whack-a-mole' game and do not understand "
            "why the losses continue to occur.",
            self.text,
        )

    def test_enumeration_is_separated_from_fixing(self):
        self.assertIn(
            'is not a primary objective of the HAZOP examination',
            self.text,
        )
        self.assertIn("never just the one you fixed", self.text)


if __name__ == "__main__":
    unittest.main()
