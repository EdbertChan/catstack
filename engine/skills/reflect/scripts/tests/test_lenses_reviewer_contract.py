"""Pin the reviewer preamble and synthesis criteria in reflect's lenses reference."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

LENSES = Path(__file__).resolve().parents[2] / "references" / "lenses.md"


def _text() -> str:
    return LENSES.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return match.group(1) if match else ""


class ReviewerPreambleTest(unittest.TestCase):
    def test_preamble_names_read_only_untrusted_and_confined_lookups(self) -> None:
        text = _text()
        self.assertIn("**Reviewer preamble", text)
        for phrase in ("does not modify files", "untrusted data", "confined to context the transcript itself references"):
            self.assertIn(phrase, text)

    def test_preamble_cites_its_grounding(self) -> None:
        self.assertIn("genai.owasp.org/llmrisk/llm01-prompt-injection", _text())

    def test_missing_preamble_is_detected(self) -> None:
        stripped = _text().replace("untrusted data", "")
        self.assertNotIn("untrusted data", stripped)


class FetchableContextTest(unittest.TestCase):
    def test_hand_pasted_identifiers_route_to_the_owning_skill(self) -> None:
        text = _text()
        self.assertIn("**Fetchable context", text)
        self.assertIn("could have fetched", text)
        self.assertIn("`skill-not-used`", text)


class DivergentLensTest(unittest.TestCase):
    def test_divergent_row_takes_the_contrarian_framing(self) -> None:
        row = next(line for line in _text().splitlines() if line.startswith("| Divergent |"))
        self.assertIn("contrarian framing", row)
        self.assertIn("second-order", row)


class SynthesisCriteriaTest(unittest.TestCase):
    def test_every_criterion_is_present(self) -> None:
        body = _section(_text(), "Synthesis criteria")
        self.assertTrue(body, "Synthesis criteria section is missing")
        for name in ("Durability", "Specificity", "Convergence", "Decision-changing", "Existing-skill-first", "Drift test", "Already-covered, reworded"):
            self.assertIn(f"**{name}:**", body)

    def test_section_says_what_was_not_adopted(self) -> None:
        body = _section(_text(), "Synthesis criteria")
        self.assertIn("the PR is the gate", body)

    def test_empty_section_is_detected(self) -> None:
        self.assertEqual(_section("## Other\nbody\n", "Synthesis criteria"), "")


if __name__ == "__main__":
    unittest.main()
