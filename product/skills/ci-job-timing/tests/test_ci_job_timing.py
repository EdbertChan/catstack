from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ci_job_timing as c  # noqa: E402

TSV = """<METADATA><total_rows>2</total_rows></METADATA>
<TSV_DATA>
step\truns\tavg_s\tmin_s\tmax_s
Build LAGVM System\t4\t1563.0\t1500\t1600
Build LAGVM Kernel\t16\t295.0\t250\t446
</TSV_DATA>"""


class StepsSql(unittest.TestCase):
    def test_job_and_days_are_in_the_query(self):
        sql = c.steps_sql("Build LAGVM (dev)", 3)
        self.assertIn('"[job=Build LAGVM (dev)]"', sql)
        self.assertIn("INTERVAL '3 day'", sql)

    def test_same_template_works_for_another_job(self):
        sql = c.steps_sql("xmm-image-packager (dev)", 7)
        self.assertIn("[job=xmm-image-packager (dev)]", sql)

    def test_quote_in_job_name_is_refused(self):
        with self.assertRaises(ValueError):
            c.steps_sql("x' OR 1=1 --", 3)

    def test_days_out_of_range_is_refused(self):
        with self.assertRaises(ValueError):
            c.steps_sql("Build LAGVM (dev)", 0)


class Report(unittest.TestCase):
    def test_parses_and_renders(self):
        rows = c.parse_tsv(TSV)
        out = c.report("Build LAGVM (dev)", 3, rows, "https://example/x")
        self.assertIn("| Build LAGVM System | 4 | 1563 | 26.1 | 1500 | 1600 |", out)

    def test_empty_result_is_an_error_not_an_empty_table(self):
        with self.assertRaises(ValueError):
            c.parse_tsv("<TSV_DATA>\n</TSV_DATA>")

    def test_wrong_columns_is_an_error(self):
        with self.assertRaises(ValueError):
            c.parse_tsv("<TSV_DATA>\nfoo\tbar\n1\t2\n</TSV_DATA>")

    def test_timeline_uses_job_id(self):
        self.assertIn("[job_id=253261575]", c.timeline_sql("Build LAGVM (dev)", 253261575, 3))


if __name__ == "__main__":
    unittest.main()
