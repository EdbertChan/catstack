from pathlib import Path
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]


class ArtifactSweepTests(unittest.TestCase):
    def test_acceptance_contract_rule_has_trigger_fixture(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        fixture = (SKILL_DIR / "tests" / "fires_acceptance_contract.md").read_text(encoding="utf-8")

        self.assertIn("Before mutating a multi-step artifact, write the acceptance contract", skill)
        for required in ("raw schema", "coverage", "aggregation", "chart semantics", "live read-back"):
            self.assertIn(required, fixture)

    def test_correction_surface_rule_has_trigger_fixture(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        fixture = (SKILL_DIR / "tests" / "fires_correction_surface_inventory.md").read_text(encoding="utf-8")

        self.assertIn("A correction expands the inspection surface", skill)
        for required in ("raw data", "aggregate table", "chart source", "live Sheet read-back"):
            self.assertIn(required, fixture)


if __name__ == "__main__":
    unittest.main()
