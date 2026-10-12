from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from unittest import mock
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


def _gql(jobs):
    return {"data": {"project": {"pipeline": {"stages": {"nodes": [
        {"groups": {"nodes": [{"jobs": {"nodes": [
            {"name": n, "needs": {"nodes": [{"name": x} for x in needs]}}]}} for n, needs in jobs]}}]}}}}}


def _j(name, start, end, queued=5):
    return {"name": name, "status": "success", "started_at": start, "finished_at": end, "queued_duration": queued}


class Needs(unittest.TestCase):
    def test_parse_needs_reads_stages_groups_jobs(self):
        g = _gql([("a", []), ("pkg", ["a", "b", "a"])])
        self.assertEqual(c.parse_needs(g, "pkg"), ["a", "b"])

    def test_missing_job_is_an_error(self):
        with self.assertRaises(ValueError):
            c.parse_needs(_gql([("a", [])]), "zzz")


class Summarize(unittest.TestCase):
    P = {
        1: [_j("a", "2026-01-01T00:00:00Z", "2026-01-01T00:10:00Z"),
            _j("b", "2026-01-01T00:00:00Z", "2026-01-01T00:20:00Z"),
            _j("pkg", "2026-01-01T00:21:00Z", "2026-01-01T00:30:00Z", 7)],
        2: [_j("a", "2026-01-02T00:00:00Z", "2026-01-02T00:30:00Z"),
            _j("b", "2026-01-02T00:00:00Z", "2026-01-02T00:20:00Z"),
            _j("pkg", "2026-01-02T00:30:10Z", "2026-01-02T00:40:00Z")],
    }

    def test_last_finisher_and_gap(self):
        s = c.summarize("pkg", ["a", "b"], self.P)
        self.assertEqual([r["last_finisher"] for r in s["rows"]], ["b", "a"])
        self.assertEqual([r["gap_s"] for r in s["rows"]], [60.0, 10.0])
        self.assertEqual(s["last_counts"], {"a": 1, "b": 1})
        self.assertEqual(s["median_gap_s"], 35.0)
        self.assertEqual(s["max_gap_s"], 60.0)

    def test_absent_need_is_skipped_not_an_error(self):
        s = c.summarize("pkg", ["a", "b", "optional"], self.P)
        self.assertEqual(s["skipped"], {"optional": 2})
        self.assertEqual(len(s["rows"]), 2)
        self.assertIn("optional needs", c.render_context(s))


class ContextCommand(unittest.TestCase):
    def _run(self, argv, env):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = c.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_missing_token_exits_2_with_no_report(self):
        env = dict(os.environ)
        env.pop("GITLAB_TOKEN", None)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = c.main(["context", "--job", "pkg", "--pipelines", "2"])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("GITLAB_TOKEN", err.getvalue())

    def test_job_ids_resolve_pipelines_without_scanning(self):
        calls = []

        def fake(url, token, body=None):
            calls.append(url)
            if url.endswith("/graphql"):
                return _gql([("pkg", ["a", "b"])])
            if "/jobs/" in url and "/pipelines/" not in url:
                jid = int(url.rsplit("/", 1)[1])
                return {"name": "pkg", "pipeline": {"id": {101: 1, 102: 2}[jid], "iid": {101: 11, 102: 12}[jid]}}
            if "/pipelines/" in url:
                return Summarize.P[int(url.split("/pipelines/")[1].split("/")[0])]
            raise AssertionError(f"unexpected scan call: {url}")

        needs, by_p = c.fetch_context_inputs("https://h", "core/firmware", "pkg", 2, "tok", get=fake, job_ids=[101, 102])
        self.assertEqual(sorted(by_p), [1, 2])
        self.assertEqual(needs, ["a", "b"])
        self.assertFalse(any("order_by" in u for u in calls))

    def test_job_id_with_a_different_name_is_an_error(self):
        def fake(url, token, body=None):
            return {"name": "other", "pipeline": {"id": 1, "iid": 11}}

        with self.assertRaises(ValueError):
            c.fetch_context_inputs("https://h", "core/firmware", "pkg", 1, "tok", get=fake, job_ids=[101])

    def test_token_value_never_appears_in_output(self):
        secret = "glpat-SECRET-VALUE-123"

        def fake(url, token, body=None):
            self.assertEqual(token, secret)
            if url.endswith("/graphql"):
                return _gql([("pkg", ["a", "b"])])
            if "/pipelines/" in url:
                return Summarize.P[int(url.split("/pipelines/")[1].split("/")[0])]
            return [{"id": 1, "iid": 11}, {"id": 2, "iid": 12}]

        needs, by_p = c.fetch_context_inputs("https://h", "core/firmware", "pkg", 2, secret, get=fake)
        text = c.render_context(c.summarize("pkg", needs, by_p))
        self.assertNotIn(secret, text)
        with mock.patch.object(c, "fetch_context_inputs", side_effect=OSError("boom")):
            rc, out, err = self._run(["context", "--job", "pkg"], {"GITLAB_TOKEN": secret})
        self.assertEqual(rc, 2)
        self.assertNotIn(secret, out + err)


if __name__ == "__main__":
    unittest.main()
