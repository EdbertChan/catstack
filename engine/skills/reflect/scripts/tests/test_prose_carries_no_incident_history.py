from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
SKILL_REL = "engine/skills/reflect/"
sys.path.insert(0, str(REPO / "scripts"))

import check_no_dated_provenance as checker  # noqa: E402


class TestProseCarriesNoIncidentHistory(unittest.TestCase):
    def test_skill_prose_passes_the_provenance_gate(self):
        hits = [h for h in checker.scan_tree(REPO) if h.startswith(SKILL_REL)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
