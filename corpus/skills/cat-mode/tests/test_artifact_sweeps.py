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

    def test_invoker_agent_rule_has_fixtures(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        fires = (SKILL_DIR / "tests" / "fires_invoker_plan_agent_claude.md").read_text(encoding="utf-8")
        silent = (SKILL_DIR / "tests" / "stays_silent_invoker_plan_agent_claude.md").read_text(encoding="utf-8")

        self.assertIn("Every Invoker plan sets `executionAgent: claude` on each prompt task", skill)
        self.assertIn("executionAgent: claude", fires)
        self.assertNotIn("codex", silent.split("Assistant:")[1])
        self.assertIn("executionAgent: claude", silent)


if __name__ == "__main__":
    unittest.main()
