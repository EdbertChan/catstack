import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


def _read(*parts):
    return (SKILL_DIR.joinpath(*parts)).read_text(encoding="utf-8")


def _skill():
    return _read("SKILL.md")


def _reference(name):
    return " ".join(_read("references", name).split())


def _fixture(name):
    return _read("tests", name)


class ArtifactSweepTests(unittest.TestCase):
    def test_done_list_rule_has_trigger_fixture(self):
        fixture = _fixture("fires_acceptance_contract.md")

        self.assertIn("Before changing a deliverable with several parts", _skill())
        for required in ("raw schema", "coverage", "aggregation", "chart semantics", "live read-back"):
            self.assertIn(required, fixture)

    def test_correction_everywhere_rule_has_trigger_fixture(self):
        fixture = _fixture("fires_correction_surface_inventory.md")

        self.assertIn("look for the same mistake everywhere the work shows up", _skill())
        for required in ("raw data", "aggregate table", "chart source", "live Sheet read-back"):
            self.assertIn(required, fixture)

    def test_local_only_rule_has_fixtures(self):
        fires = _fixture("fires_local_only_no_github.md")
        silent = _fixture("stays_silent_remote_repo_publishes.md")

        self.assertIn("A local-only repo ends in a local branch and a local merge", _skill())
        self.assertIn("local merge", fires)
        self.assertNotIn("git push", fires.split("Assistant:")[1])
        self.assertIn("git push", silent)


class PagesAndArchitectureTests(unittest.TestCase):
    def test_architecture_shape_first_drawn_as_one_thing(self):
        self.assertIn("An architecture question gets the system's shape first, drawn as one thing", _skill())
        self.assertIn("Explain an unfamiliar system one concept at a time", _skill())
        prose = _reference("prose-and-scope.md")
        self.assertIn("one line per stage from source to sink", prose)
        self.assertIn("never several images", prose)
        self.assertIn("https://c4model.com/", prose)
        self.assertIn("https://doi.org/10.1109/VL.1996.545307", prose)
        self.assertIn("no diagram", _fixture("fires_fix_before_architecture_shape.md"))
        self.assertIn("Shape first", _fixture("stays_silent_shape_first_one_diagram.md"))

    def test_tool_cannot_claim_needs_search_receipt(self):
        self.assertIn('"This tool cannot do X" needs a search receipt', _skill())
        verify = _reference("verify.md")
        self.assertIn("cite the hit or the empty search in the same message", verify)
        self.assertIn("https://doi.org/10.1136/bmj.311.7003.485", verify)
        self.assertIn("no receipt", _fixture("fires_says_tool_lacks_feature_unsearched.md"))
        self.assertIn("I searched your saved views", _fixture("stays_silent_tool_lacks_feature_with_search_receipt.md"))

    def test_page_labels_use_the_users_nouns(self):
        self.assertIn("Page labels, tabs, legends, and box labels use the user's nouns or the source's field names", _skill())
        prose = _reference("prose-and-scope.md")
        self.assertIn("The same rule binds the page itself", prose)
        self.assertIn("https://www.nngroup.com/articles/ten-usability-heuristics/", prose)
        self.assertIn("words that appear nowhere in the data fields", _fixture("fires_invented_page_labels.md"))
        self.assertIn("nothing coined for the page", _fixture("stays_silent_page_labels_in_users_nouns.md"))

    def test_page_with_numbers_is_rendered_by_a_script(self):
        self.assertIn("A page with numbers is rendered by a script from a data file", _skill())
        self.assertIn("The repo (or its README) is the one place the result lives", _skill())
        verify = _reference("verify.md")
        self.assertIn("which script, which commit or MR, and which data window made it", verify)
        self.assertIn("https://doi.org/10.1007/978-1-4612-2544-7_5", verify)
        self.assertIn("https://doi.org/10.1371/journal.pbio.1001745", verify)
        self.assertIn("hand-computed", _fixture("fires_hand_edited_page_numbers.md"))
        self.assertIn("names the script, the commit, and the data window", _fixture("stays_silent_page_rendered_by_script.md"))

    def test_mock_first_and_a_mock_is_cheap(self):
        skill = _skill()
        self.assertIn("show a one-screen mock and name the one guess", skill)
        self.assertIn("takes minutes, not a build", skill)
        autonomy = _reference("autonomy.md")
        self.assertIn("Mock first, and a mock is cheap", autonomy)
        self.assertIn("invented numbers labelled as invented", autonomy)
        self.assertIn("for an addition, the guess is where it goes", autonomy)
        self.assertIn("Sketching User Experiences", autonomy)
        self.assertIn("without showing a one-screen mock", _fixture("fires_builds_design_without_mock.md"))
        self.assertIn("one-screen mock with invented numbers", _fixture("stays_silent_mock_first_then_wait.md"))

    def test_metrics_view_is_built_in_the_dashboard_tool(self):
        self.assertIn("A metrics view the user already keeps in a dashboard tool is built there", _skill())
        self.assertIn("## Pages, dashboards, and diagrams", _read("references", "prose-and-scope.md"))
        self.assertIn("without searching the dashboard tool", _fixture("fires_html_page_for_dashboard_tool_metrics.md"))
        self.assertIn("built the view there", _fixture("stays_silent_metrics_built_in_dashboard_tool.md"))

    def test_shareable_means_self_contained_page(self):
        self.assertIn("means a self-contained page", _skill())
        self.assertIn("regenerable from a script named on the page", _skill())

    def test_page_request_ends_with_one_url(self):
        self.assertIn("A page request ends with one URL or path", _skill())
        self.assertIn("no URL or path to the page", _fixture("fires_page_delivered_as_gif.md"))
        self.assertIn("one URL", _fixture("stays_silent_page_request_ends_with_url.md"))

    def test_show_me_on_a_dashboard_gets_a_baked_link(self):
        self.assertIn("A request to see a live view is answered with the view itself", _skill())
        self.assertIn("Change the branch filter", _fixture("fires_dashboard_show_me_as_filter_instruction.md"))
        self.assertIn("baked in", _fixture("stays_silent_dashboard_link_with_values.md"))

    def test_hand_edit_names_the_place_and_proposal_restates_the_ask(self):
        skill = _skill()
        self.assertIn("for an addition, it also names the place", skill)
        self.assertIn("A proposal restates the user's question in one line before its output shape", skill)
        autonomy = _reference("autonomy.md")
        self.assertIn("name the target region back to the user", autonomy)
        self.assertIn("point at the line where they asked for each part of the output", autonomy)

    def test_question_is_for_a_gap_not_a_re_ask(self):
        self.assertIn("A question is for a gap the transcript does not fill", _skill())
        self.assertIn('"just do it the way I said it" is already an answer', _reference("autonomy.md"))
        self.assertIn("re-asking a question the transcript already answers", _fixture("fires_reasks_answered_question.md"))
        self.assertIn("the one gap the transcript does not fill", _fixture("stays_silent_asks_only_the_gap.md"))

    def test_plain_words_replace_the_old_terms(self):
        skill = _skill()
        for gone in ("acceptance contract", "artifact-of-record", "L1 explain", "Schema before UI", "mandated mid thrash", "multi-step artifact"):
            self.assertNotIn(gone, skill, gone)
        self.assertIn("Visual proof", skill)
        self.assertIn("For a cost or audit report:", skill)
        self.assertIn("Plain story before any names", _reference("prose-and-scope.md"))
        self.assertIn("use their word from the next message on", _reference("prose-and-scope.md"))
        self.assertIn("the Review Claim is the one sentence in the PR body saying what the change does", _reference("verify.md"))


if __name__ == "__main__":
    unittest.main()
