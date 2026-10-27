from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import trace_ci_job as t  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
HOST = "https://gitlab.example"
PROJECT = "group/app"

MAIN = """include:
  - local: ci/app.yml
stages: [build, package]
.common:
  before_script:
    - echo prep
  script:
    - ./tools/common.sh
build_apps:
  stage: build
  script:
    - make apps
build_app (dev):
  extends: .common
  stage: package
  needs:
    - build_apps
  rules:
    - changes:
        - app/**/*
  script:
    - !reference [.common, script]
    - source tools/package.sh && package_image dev
build_app (prod):
  extends: .common
  stage: package
  needs:
    - job: build_apps
      optional: true
  script:
    - source tools/package.sh && package_image prod
"""

APP_CI = """downstream_flash:
  stage: package
  needs: [build_app (dev)]
  script:
    - echo flash
"""

PACKAGER = """#!/bin/bash
helper() {
  true
}
package_image() {
  echo "$1"
}
"""

FILES = {".gitlab-ci.yml": MAIN, "ci/app.yml": APP_CI, "tools/package.sh": PACKAGER}


def read(path: str) -> str:
    if path not in FILES:
        raise OSError(f"{path} missing")
    return FILES[path]


def line_of(text: str, needle: str) -> int:
    return next(i for i, row in enumerate(text.splitlines(), 1) if needle in row)


class Trace(unittest.TestCase):
    def setUp(self):
        self.cfg = t.collect(read)
        self.hops = t.trace(self.cfg, "build_app (dev)")

    def find(self, kind, fragment=""):
        return [h for h in self.hops if h.kind == kind and fragment in h.text]

    def test_job_definition_hop_has_file_line_range_and_blob_url(self):
        job = self.hops[0]
        self.assertEqual((job.kind, job.path, job.line), ("job", ".gitlab-ci.yml", line_of(MAIN, "build_app (dev):")))
        self.assertEqual(job.end, line_of(MAIN, "build_app (prod):") - 1)
        url = t.blob_url(HOST, PROJECT, SHA, job.path, job.line, job.end)
        self.assertEqual(url, f"{HOST}/{PROJECT}/-/blob/{SHA}/.gitlab-ci.yml#L{job.line}-{job.end}")

    def test_extends_hop_cites_the_extends_line_and_the_parent_definition(self):
        ext = self.find("extends")[0]
        self.assertEqual(ext.line, line_of(MAIN, "extends: .common"))
        parent = self.find("extends-def", ".common")[0]
        self.assertEqual(parent.line, line_of(MAIN, ".common:"))

    def test_reference_hop_cites_the_tag_and_the_target(self):
        ref = self.find("reference")[0]
        self.assertEqual(ref.line, line_of(MAIN, "!reference [.common, script]"))
        target = self.find("reference-def")[0]
        self.assertEqual(target.line, line_of(MAIN, "./tools/common.sh") - 1)

    def test_needs_up_and_down_each_cite_the_creating_line(self):
        up = self.find("needs-up", "build_apps")[0]
        self.assertEqual(up.line, line_of(MAIN, "    - build_apps"))
        down = self.find("needs-down", "downstream_flash")[0]
        self.assertEqual((down.path, down.line), ("ci/app.yml", line_of(APP_CI, "needs: [build_app (dev)]")))

    def test_rules_changes_hop(self):
        ch = self.find("rules:changes")[0]
        self.assertEqual((ch.text, ch.line), ("app/**/*", line_of(MAIN, "app/**/*")))

    def test_script_lines_include_expanded_reference_source(self):
        scripts = [(h.text, h.path, h.line) for h in self.hops if h.kind == "script"]
        self.assertIn(("./tools/common.sh", ".gitlab-ci.yml", line_of(MAIN, "./tools/common.sh")), scripts)
        packager = line_of(MAIN, "package_image dev")
        self.assertTrue(any(line == packager for _, _, line in scripts))

    def test_follow_scripts_reads_script_and_function_at_the_same_reader(self):
        more = t.follow_scripts(self.hops, read)
        shell = [h for h in more if h.kind == "shell" and h.path == "tools/package.sh"]
        fn = [h for h in more if h.kind == "shell-fn"]
        self.assertEqual(len(shell), 1)
        self.assertEqual([(h.text, h.line) for h in fn], [("function package_image", line_of(PACKAGER, "package_image()"))])

    def test_follow_scripts_reports_an_unreadable_script(self):
        missing = t.follow_scripts(self.hops, lambda p: (_ for _ in ()).throw(OSError("gone")))
        self.assertTrue(any(h.kind == "shell-missing" for h in missing))

    def test_normalised_name_resolves(self):
        self.assertEqual(t.trace(self.cfg, "Build App (prod)")[0].text, "build_app (prod)")

    def test_diff_shows_needs_and_script_differences_with_locations(self):
        rows = {r[0]: r for r in t.diff_variants(self.cfg, "build_app (dev)", "build_app (prod)")}
        self.assertIn("needs", rows)
        self.assertIn("script", rows)
        self.assertNotIn("stage", rows)
        self.assertTrue(rows["needs"][2].startswith(".gitlab-ci.yml:"))

    def test_blob_url_single_line_and_branch_name_refused(self):
        self.assertTrue(t.blob_url(HOST, PROJECT, SHA, "a b.yml", 7).endswith("/a%20b.yml#L7"))
        with self.assertRaises(ValueError):
            t.blob_url(HOST, PROJECT, "main", "a.yml", 7)

    def test_open_runs_one_chrome_open_per_distinct_url(self):
        calls = []
        urls = t.cited_urls(self.hops, HOST, PROJECT, SHA)
        t.open_in_chrome(urls, lambda cmd, check: calls.append(cmd))
        self.assertEqual(len(calls), len(urls))
        self.assertEqual(calls[0][:3], ["open", "-a", "Google Chrome"])


class Negative(unittest.TestCase):
    def _run(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=False), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = t.main(argv + ["--project", PROJECT])
        return rc, out.getvalue(), err.getvalue()

    def test_unknown_job_raises_with_close_matches(self):
        cfg = t.collect(read)
        with self.assertRaises(t.JobNotFound) as ctx:
            t.trace(cfg, "build_app (staging)")
        self.assertIn("build_app (dev)", ctx.exception.close)
        self.assertIn("build_app (prod)", str(ctx.exception))

    def test_cli_unknown_job_exits_nonzero_and_prints_no_chain(self):
        with mock.patch.object(t, "git_reader", return_value=read):
            rc, out, err = self._run(["trace", "--job", "build_app (staging)", "--sha", SHA, "--repo", "/x"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("close matches", err)
        self.assertIn("build_app (dev)", err)

    def test_branch_name_instead_of_sha_is_refused(self):
        rc, out, err = self._run(["trace", "--job", "build_apps", "--sha", "main", "--repo", "/x"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("sha", err)

    def test_api_mode_without_token_exits_nonzero(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            rc, out, err = self._run(["trace", "--job", "build_apps", "--sha", SHA])
        self.assertEqual(rc, 2)
        self.assertIn("GITLAB_TOKEN", err)

    def test_unreadable_root_is_an_error_not_an_empty_chain(self):
        with self.assertRaises(ValueError):
            t.collect(lambda p: (_ for _ in ()).throw(OSError("nope")))

    def test_extends_unknown_parent_is_an_error(self):
        cfg = t.collect(lambda p: "a:\n  extends: .missing\n  script: [x]\n")
        with self.assertRaises(ValueError):
            t.trace(cfg, "a")

    def test_token_never_appears_in_output(self):
        secret = "glpat-SECRET-VALUE-123"
        with mock.patch.object(t, "api_reader", side_effect=OSError("boom")):
            rc, out, err = self._run(["trace", "--job", "x", "--sha", SHA], {"GITLAB_TOKEN": secret})
        self.assertEqual(rc, 2)
        self.assertNotIn(secret, out + err)


class Proof(unittest.TestCase):
    def test_proof_returns_url_and_duration_of_a_successful_run(self):
        def fake(url, token, body=None):
            if "/jobs/9" in url and "pipelines" not in url:
                return {"name": "pkg", "pipeline": {"id": 1, "iid": 11}}
            if url.endswith("/graphql"):
                return {"data": {"project": {"pipeline": {"stages": {"nodes": [{"groups": {"nodes": [
                    {"jobs": {"nodes": [{"name": "pkg", "needs": {"nodes": []}}]}}]}}]}}}}}
            return [{"id": 9, "name": "pkg", "status": "success", "web_url": "https://h/-/jobs/9", "duration": 42.5}]

        r = t.job_proof("https://h", PROJECT, "pkg", [9], "tok", get=fake)
        self.assertEqual(r, {"id": 9, "web_url": "https://h/-/jobs/9", "duration_s": 42.5})


if __name__ == "__main__":
    unittest.main()
