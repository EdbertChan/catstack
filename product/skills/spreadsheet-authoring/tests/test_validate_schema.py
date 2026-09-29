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


if __name__ == "__main__":
    unittest.main()
