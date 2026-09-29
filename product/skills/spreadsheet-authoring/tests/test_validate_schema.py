import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from validate_schema import validate_rows


def row(**overrides):
    result = {
        "Original Period Label": "Q4 2023 end",
        "Period Start": "2023-10-01",
        "Period End": "2023-12-31",
        "Observation Point": "End",
        "Geography": "US",
        "Scope": "Unified",
        "Segment": "",
        "Entity": "Uber",
        "Metric": "Weekly active users",
        "Value": "11800000",
        "Source URL": "https://example.com/source",
        "Observation Type": "reported",
        "Derivation Method": "",
        "Derived From": "",
        "Notes": "",
    }
    result.update(overrides)
    return result


class SchemaTests(unittest.TestCase):
    def test_accepts_typed_period_and_distinct_points(self):
        errors = validate_rows([row(), row(**{"Original Period Label": "Q4 2023 peak", "Observation Point": "Peak"})])
        self.assertEqual(errors, [])

    def test_rejects_qualifier_in_period_start(self):
        errors = validate_rows([row(**{"Period Start": "Q4 2023 end"})])
        self.assertEqual(len(errors), 1)
        self.assertIn("qualifier embedded", errors[0])

    def test_rejects_missing_expected_entity_for_same_observation_key(self):
        errors = validate_rows([row()], expected_entities={"Uber", "Lyft"})
        self.assertTrue(any("missing expected entities: Lyft" in error for error in errors))

    def test_rejects_numeric_observation_without_source_url(self):
        errors = validate_rows([row(**{"Source URL": ""})])
        self.assertTrue(any("missing Source URL" in error for error in errors))

    def test_all_expected_entities_can_be_present_for_one_period(self):
        errors = validate_rows(
            [row(), row(**{"Entity": "Lyft", "Original Period Label": "Q4 2023 end"})],
            expected_entities={"Uber", "Lyft"},
        )
        self.assertEqual(errors, [])

    def test_unreported_status_does_not_satisfy_entity_coverage(self):
        errors = validate_rows(
            [row(), row(**{"Entity": "Lyft", "Value": "", "Source URL": "https://example.com/source", "Data Status": "NO OBSERVATION PUBLISHED"})],
            expected_entities={"Uber", "Lyft"},
        )
        self.assertTrue(any("missing expected entities: Lyft" in error for error in errors))

    def test_derived_estimate_requires_derivation_note(self):
        errors = validate_rows([row(**{"Observation Type": "derived estimate", "Notes": ""})])
        self.assertTrue(any("missing derivation method" in error for error in errors))
        self.assertTrue(any("missing Derived From" in error for error in errors))
        self.assertTrue(any("missing derivation note" in error for error in errors))

    def test_derived_estimate_is_not_source_coverage(self):
        errors = validate_rows(
            [
                row(),
                row(
                    **{
                        "Entity": "Lyft",
                        "Observation Type": "derived estimate",
                        "Derivation Method": "midpoint",
                        "Derived From": "Start + End",
                        "Notes": "Midpoint formula: (Start + End) / 2",
                    }
                ),
            ],
            expected_entities={"Uber", "Lyft"},
        )
        self.assertTrue(any("missing expected entities: Lyft" in error for error in errors))

    def test_accepts_provenance_preserving_midpoint(self):
        errors = validate_rows(
            [
                row(
                    **{
                        "Observation Type": "derived estimate",
                        "Derivation Method": "midpoint",
                        "Derived From": "Start + End",
                        "Notes": "Midpoint formula: (Start + End) / 2",
                    }
                )
            ]
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
