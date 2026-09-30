import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from geography import GeographyTaxonomy, MappingStatus, stable_bucket_id


class GeographyTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy = GeographyTaxonomy(
            "sales",
            "2026-01",
            exact={"United States": "us"},
            source_defined={
                "Northern markets": ["us", "ca"],
                "Report cluster": ["us"],
            },
        )

    def test_exact_lookup_preserves_label_and_returns_stable_bucket(self):
        result = self.taxonomy.lookup("United States")
        self.assertEqual(result.status, MappingStatus.EXACT)
        self.assertEqual(result.source_label, "United States")
        self.assertEqual(result.bucket_ids, (stable_bucket_id("sales", "2026-01", "us"),))

    def test_source_defined_mapping_is_explicit(self):
        result = self.taxonomy.lookup("Report cluster")
        self.assertEqual(result.status, MappingStatus.SOURCE_DEFINED)
        self.assertEqual(len(result.bucket_ids), 1)

    def test_ambiguous_source_defined_mapping_is_not_resolved(self):
        result = self.taxonomy.lookup("Northern markets")
        self.assertEqual(result.status, MappingStatus.AMBIGUOUS)
        self.assertEqual(len(result.bucket_ids), 2)

    def test_unresolved_label_does_not_fuzzy_match(self):
        result = self.taxonomy.lookup("United States ")
        self.assertEqual(result.status, MappingStatus.UNRESOLVED)
        self.assertEqual(result.bucket_ids, ())

    def test_taxonomy_and_version_scope_lookup(self):
        other = GeographyTaxonomy("finance", "2026-01", exact={"United States": "us"})
        newer = GeographyTaxonomy("sales", "2026-02", exact={"United States": "us"})
        self.assertEqual(other.lookup("US").status, MappingStatus.UNRESOLVED)
        self.assertNotEqual(
            self.taxonomy.lookup("United States").bucket_ids,
            newer.lookup("United States").bucket_ids,
        )


if __name__ == "__main__":
    unittest.main()
