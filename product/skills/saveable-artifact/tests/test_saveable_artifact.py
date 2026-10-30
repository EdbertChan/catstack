from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import measure_apply_delay as measure  # noqa: E402
import saveable_artifact as artifact  # noqa: E402

TOY_PAGE = (SKILL / "tests" / "fixtures" / "toy_page.html").read_text(encoding="utf-8")
SAVED = {"changes": [{"job": "saved one"}]}
APPLIED = "state.changes.length === 1 && state.changes[0].job === 'saved one'"


def bridged(mode: str = "standalone") -> str:
    return artifact.add_bridge(TOY_PAGE, mode, "toy/settings", "boot")


class DataBlocks(unittest.TestCase):
    def test_a_block_unpacks_to_what_was_packed(self):
        document = {"views": [{"key": "a", "runs": [1, 2, 3]}], "text": "café"}
        block = artifact.pack_block("first", document)
        encoded = artifact.DATA_BLOCK.search(block).group(2)
        self.assertEqual(artifact.unpack_block(encoded), document)

    def test_packing_twice_keeps_one_region_with_the_newest_data(self):
        once = artifact.add_data_blocks(TOY_PAGE, {"first": {"n": 1}})
        twice = artifact.add_data_blocks(once, {"first": {"n": 2}})
        self.assertEqual(twice.count(artifact.DATA_REGION[0]), 1)
        encoded = artifact.DATA_BLOCK.search(twice).group(2)
        self.assertEqual(artifact.unpack_block(encoded), {"n": 2})

    def test_packing_nothing_is_refused(self):
        with self.assertRaises(SystemExit):
            artifact.add_data_blocks(TOY_PAGE, {})


class Bridge(unittest.TestCase):
    def test_standalone_page_passes_every_check(self):
        self.assertEqual(artifact.problems(bridged("standalone")), [])

    def test_hosted_page_passes_every_check(self):
        self.assertEqual(artifact.problems(bridged("hosted")), [])

    def test_settings_path_and_ready_function_are_filled_in(self):
        page = bridged("standalone")
        self.assertIn('const SETTINGS_PATH = "toy/settings";', page)
        self.assertIn('const READY_FUNCTION = "boot";', page)
        self.assertNotRegex(page, r"__[A-Z_]+__")

    def test_adding_the_bridge_twice_gives_the_same_page(self):
        once = bridged("hosted")
        self.assertEqual(artifact.add_bridge(once, "hosted", "toy/settings", "boot"), once)

    def test_button_sits_at_the_anchor_when_the_page_has_one(self):
        page = bridged("standalone")
        self.assertLess(page.index('id="saveable-button"'), page.index('id="count"'))
        self.assertEqual(page.count('id="saveable-button"'), 1)

    def test_saved_settings_are_published_before_the_page_waits_to_apply_them(self):
        for template in ("standalone_bridge.js", "hosted_bridge.js"):
            text = (artifact.TEMPLATES / template).read_text(encoding="utf-8")
            self.assertLess(text.index("window.savedPageSettings = saved"), text.index("await booted"), template)

    def test_a_template_with_an_unknown_placeholder_is_refused(self):
        with self.assertRaises(SystemExit):
            artifact.template_text("parent_bridge.js", frame_id="board", settings_path="x", extra="y")

    def test_parent_bridge_names_the_frame_and_the_path(self):
        host = (SKILL / "tests" / "fixtures" / "toy_host.html").read_text(encoding="utf-8")
        page = artifact.add_parent_bridge(host, "board", "toy/settings")
        self.assertIn('document.getElementById("board")', page)
        self.assertIn('const SETTINGS_PATH = "toy/settings";', page)


class Problems(unittest.TestCase):
    def test_a_timer_in_the_bridge_is_reported(self):
        page = bridged("standalone").replace(artifact.BRIDGE_REGION[1], "<script>setTimeout(() => {}, 2500);</script>\n" + artifact.BRIDGE_REGION[1])
        self.assertTrue(any("timer" in line for line in artifact.problems(page)))

    def test_missing_default_guard_is_reported_unless_the_page_has_no_defaults(self):
        page = bridged("standalone").replace("if (window.savedPageSettings) return;", "")
        self.assertTrue(any("savedPageSettings" in line for line in artifact.problems(page)))
        self.assertEqual(artifact.problems(page, expect_preset_guard=False), [])

    def test_a_page_over_the_limit_is_reported(self):
        self.assertTrue(any("over the" in line for line in artifact.problems(bridged("standalone"), limit_bytes=100)))

    def test_a_corrupt_data_block_is_reported(self):
        page = artifact.add_data_blocks(bridged("standalone"), {"first": {"n": 1}})
        broken = page.replace(artifact.DATA_BLOCK.search(page).group(2), "AAAA")
        self.assertTrue(any("does not unpack" in line for line in artifact.problems(broken)))

    def test_a_page_without_the_contract_is_reported(self):
        page = bridged("standalone").replace("window.savedPage =", "window.somethingElse =")
        self.assertTrue(any("savedPage" in line for line in artifact.problems(page)))


class MeasureHarness(unittest.TestCase):
    def test_every_placeholder_is_filled(self):
        for template in (measure.HOSTED_PARENT, measure.STANDALONE_STUB, measure.STANDALONE_POLLER):
            self.assertNotRegex(measure.fill(template, SAVED, APPLIED), r"__[A-Z_]+__")

    def test_standalone_page_gets_the_stand_in_database_and_the_poller(self):
        page = measure.standalone_files(bridged("standalone"), SAVED, APPLIED)["page.html"]
        self.assertLess(page.index("window.claude ="), page.index("window.savedPage ="))
        self.assertIn('id="saveable-result"', page)

    def test_a_page_without_a_body_is_refused(self):
        with self.assertRaises(SystemExit):
            measure.standalone_files("<html></html>", SAVED, APPLIED)

    def test_slow_and_never_applied_arrivals_are_named_and_the_none_case_is_skipped(self):
        results = [
            {"arrival": 0, "appliedAfter": 20},
            {"arrival": 300, "appliedAfter": 2500},
            {"arrival": 3000, "appliedAfter": None},
            {"arrival": -1, "appliedAfter": None},
        ]
        self.assertEqual(measure.slow_arrivals(results, 100), [300, 3000])

    def test_a_missing_result_is_an_error_not_a_pass(self):
        with self.assertRaises(SystemExit):
            measure.parse_result("<html>nothing here</html>")


@unittest.skipUnless(os.path.exists(measure.CHROME_MACOS), "Chrome is not installed here")
class RealBrowser(unittest.TestCase):
    def measured(self, mode: str):
        import tempfile

        directory = Path(tempfile.mkdtemp())
        page = directory / "page.html"
        page.write_text(bridged(mode), encoding="utf-8")
        return measure.measure(str(page), mode, SAVED, APPLIED, [0, 300, -1], measure.CHROME_MACOS)

    def test_standalone_toy_page_applies_saved_settings_within_the_limit(self):
        results = self.measured("standalone")
        self.assertEqual(measure.slow_arrivals(results, 100), [])
        self.assertFalse(results[-1]["finalApplied"])

    def test_hosted_toy_page_applies_saved_settings_within_the_limit(self):
        results = self.measured("hosted")
        self.assertEqual(measure.slow_arrivals(results, 100), [])
        self.assertFalse(results[-1]["finalApplied"])


if __name__ == "__main__":
    unittest.main()
