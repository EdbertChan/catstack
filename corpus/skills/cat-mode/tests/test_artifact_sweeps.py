from pathlib import Path
import re
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


def normalized(path):
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


class HandoffDefaultTests(unittest.TestCase):
    def test_autonomy_handoff_rules_are_in_skill_and_reference(self):
        skill = normalized(SKILL_DIR / "SKILL.md")
        autonomy = normalized(SKILL_DIR / "references" / "autonomy.md")
        for lead in (
            "A blocker only the user can clear is the first line of the next reply",
            "A launch or restart of a local server ends the reply with its URL and the commit it serves",
            "A review round that lands ends with the rebuilt review page link and its version number",
            "A hand rewrite of a deliverable is the spec",
            "A new deliverable with its own artifact gets the fresh-session suggestion",
        ):
            with self.subTest(rule=lead):
                self.assertIn(lead, skill)
                self.assertIn(lead, autonomy)
        self.assertIn("An ask skipped in two consecutive turns becomes", skill)
        self.assertIn("An ask skipped in two consecutive turns becomes a stated default", autonomy)
        self.assertIn("I'll do X unless you say otherwise", skill)
        self.assertIn("[[reflect]] / [[automate-me]]", autonomy)

    def test_prose_subagent_rule_names_the_skill_tests_not_the_root_suite(self):
        skill = normalized(SKILL_DIR / "SKILL.md")
        subagents = normalized(SKILL_DIR / "references" / "subagents.md")
        self.assertIn("A prose-only subagent runs the touched skill's own tests, never the whole repo suite", skill)
        self.assertIn("A prose-only subagent runs the skill's own tests", subagents)
        self.assertIn("scripts/ci/check_skill_test_coverage.py", subagents)

    def test_rehearsal_rule_has_fixtures(self):
        skill = normalized(SKILL_DIR / "SKILL.md")
        verify = normalized(SKILL_DIR / "references" / "verify.md")
        fires = (SKILL_DIR / "tests" / "fires_health_check_as_rehearsal.md").read_text(encoding="utf-8")
        silent = (SKILL_DIR / "tests" / "stays_silent_first_screen_timed.md").read_text(encoding="utf-8")

        self.assertIn("A hand-off rehearsal ends on the user's first screen, with its load time measured and pasted", skill)
        self.assertIn("A rehearsal ends on the user's first screen", verify)
        self.assertIn("engine/CLAUDE.core.md", verify)
        self.assertIn("health check", fires)
        self.assertNotRegex(fires.split("Assistant:")[1], r"\d+(\.\d+)? s\b")
        self.assertRegex(silent.split("Assistant:")[1], r"\d+(\.\d+)? s\b")

    def test_page_copy_rule_is_in_skill_and_prose_reference(self):
        skill = normalized(SKILL_DIR / "SKILL.md")
        prose = normalized(SKILL_DIR / "references" / "prose-and-scope.md")
        for text in (skill, prose):
            self.assertIn('No "how to read this" prose on a page or in a UI', text)
        self.assertIn("never a word invented for the page", prose)

    def test_design_doc_shape_is_linked_and_lists_every_section(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        shape = (SKILL_DIR / "references" / "design-doc-shape.md").read_text(encoding="utf-8")
        self.assertIn("references/design-doc-shape.md", skill)
        for section in ("Summary", "Vocabulary", "Architecture", "User functionality", "Fields table", "Decisions", "Run it", "Known limits"):
            with self.subTest(section=section):
                self.assertIn(f"**{section}.**", shape)
        self.assertIn("product/skills/technical-writing/SKILL.md", shape)
        self.assertIn("We do the Nth", shape)
        self.assertIn("No placeholders", shape)


if __name__ == "__main__":
    unittest.main()
