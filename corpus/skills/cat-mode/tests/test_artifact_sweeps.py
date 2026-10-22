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

    def test_local_only_rule_has_fixtures(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        fires = (SKILL_DIR / "tests" / "fires_local_only_no_github.md").read_text(encoding="utf-8")
        silent = (SKILL_DIR / "tests" / "stays_silent_remote_repo_publishes.md").read_text(encoding="utf-8")

        self.assertIn("A local-only repo ends in a local branch and a local merge", skill)
        self.assertIn("local merge", fires)
        self.assertNotIn("git push", fires.split("Assistant:")[1])
        self.assertIn("git push", silent)

    def test_open_for_me_rule_has_fixtures(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        fires = (SKILL_DIR / "tests" / "fires_open_for_me_hands_back_links.md").read_text(encoding="utf-8")
        silent = (SKILL_DIR / "tests" / "stays_silent_open_for_me_opens_in_editor.md").read_text(encoding="utf-8")

        self.assertIn("\"Open X for me\" means open it in the user's local editor now", skill)
        self.assertIn("Cmd+click", fires.split("Assistant:")[1].split("\n")[0])
        self.assertIn("code -g", silent)
        self.assertIn("Opened all three", silent.split("Assistant:")[1])

    def test_place_the_term_rule_has_fixtures(self):
        reference = (SKILL_DIR / "references" / "prose-and-scope.md").read_text(encoding="utf-8")
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        fires = (SKILL_DIR / "tests" / "fires_term_in_proposal_defined_before_placed.md").read_text(encoding="utf-8")
        silent = (SKILL_DIR / "tests" / "stays_silent_term_in_proposal_placed_first.md").read_text(encoding="utf-8")

        self.assertIn("**Place the term before defining it.**", reference)
        self.assertIn("already exists or is being added before defining it", skill)
        self.assertNotIn("already exists", fires.split("Assistant:")[1].split("\n")[0])
        self.assertTrue(silent.split("Assistant:")[1].strip().startswith("Yes, it already exists"))


if __name__ == "__main__":
    unittest.main()
