import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from validate_chart_spec import validate_chart_spec


def chart(**overrides):
    result = {
        "legendPosition": "BOTTOM_LEGEND",
        "headerCount": 1,
        "externalKey": False,
        "series": [
            {"header": "Average / median"},
            {"header": "Lower bound"},
            {"header": "Upper bound"},
        ],
    }
    result.update(overrides)
    return result


class ChartSpecTests(unittest.TestCase):
    def test_accepts_native_semantic_legend(self):
        self.assertEqual(validate_chart_spec(chart()), [])

    def test_rejects_external_key_and_ambiguous_series(self):
        errors = validate_chart_spec(
            chart(
                legendPosition="NO_LEGEND",
                headerCount=0,
                externalKey=True,
                series=[{"header": "Lyft"}, {"header": "Lyft"}],
            )
        )
        self.assertIn("native in-graph legend is required", errors)
        self.assertIn("chart source must declare at least one header row", errors)
        self.assertTrue(any("sheet-side key cannot substitute" in error for error in errors))
        self.assertTrue(any("series source headers must identify distinct" in error for error in errors))

    def test_rejects_generic_series_header(self):
        errors = validate_chart_spec(chart(series=[{"header": ""}]))
        self.assertIn("semantic source header is required", errors[0])


if __name__ == "__main__":
    unittest.main()
