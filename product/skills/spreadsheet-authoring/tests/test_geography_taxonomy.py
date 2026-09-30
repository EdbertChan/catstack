import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from geography_taxonomy import GeographyMapping, GeographyRegistry


class GeographyTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.registry = GeographyRegistry((
            GeographyMapping("source-reported", "v1", "US", "exact", "US"),
            GeographyMapping("report-defined", "v1", "EMEA", "source_defined"),
        ))

    def test_exact_lookup_is_whitespace_and_case_stable(self):
        mapping = self.registry.resolve(" source-reported ", "V1", " us ")
        self.assertEqual(mapping.status, "exact")
        self.assertEqual(mapping.canonical_code, "US")

    def test_taxonomy_and_version_are_part_of_identity(self):
        self.assertEqual(self.registry.resolve("source-reported", "v2", "US").status, "unresolved")
        self.assertEqual(self.registry.resolve("other", "v1", "US").status, "unresolved")

    def test_source_defined_mapping_is_not_promoted_to_canonical_membership(self):
        mapping = self.registry.resolve("report-defined", "v1", "EMEA")
        self.assertEqual(mapping.status, "source_defined")
        self.assertEqual(mapping.included_areas, ())

    def test_unresolved_mapping_has_stable_bucket_id_without_fallback(self):
        first = self.registry.resolve("report-defined", "v1", "EU")
        second = self.registry.resolve("report-defined", "v1", "EU")
        self.assertEqual(first.status, "unresolved")
        self.assertEqual(first.bucket_id, second.bucket_id)
        self.assertNotEqual(first.bucket_id, self.registry.resolve("report-defined", "v2", "EU").bucket_id)

    def test_duplicate_mapping_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            GeographyRegistry((
                GeographyMapping("x", "v1", "US", "exact"),
                GeographyMapping("x", "v1", " us ", "exact"),
            ))


if __name__ == "__main__":
    unittest.main()
