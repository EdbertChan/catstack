"""Pin the proposal-ranking rule in reflect's cost-audit reference."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

COST_AUDIT = Path(__file__).resolve().parents[2] / "references" / "cost-audit.md"


def _text() -> str:
    return COST_AUDIT.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return match.group(1) if match else ""


class ProposalRankingTest(unittest.TestCase):
    def test_waste_removal_ranks_before_fidelity_cuts(self) -> None:
        body = _section(_text(), "Model-tier backtest")
        self.assertTrue(body, "Model-tier backtest section is missing")
        self.assertIn("removing waste comes before reducing what the reader sees", body)
        for waste in ("re-read", "retry", "extra turn", "duplicate pass"):
            self.assertIn(waste, body)
        for fidelity_cut in ("Fewer lenses", "cheaper model", "digest"):
            self.assertIn(fidelity_cut, body)
        self.assertLess(body.index("removing waste"), body.index("Fewer lenses"))

    def test_declined_recommendations_are_a_finding(self) -> None:
        body = _section(_text(), "Model-tier backtest")
        self.assertIn("declines a run of recommendations, that run is itself a finding", body)

    def test_missing_rule_is_detected(self) -> None:
        stripped = _text().replace("removing waste comes before", "")
        self.assertNotIn("removing waste comes before", _section(stripped, "Model-tier backtest"))


if __name__ == "__main__":
    unittest.main()
