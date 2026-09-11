"""A `gh api repos/<owner>/<repo>/...` write is checked against that repo, not the session's.

The payload is the real command that drew a wrong advisory: run from an Invoker
checkout, it edited a catstack PR, and Invoker's validator was applied to it.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import claude_pretooluse  # noqa: E402
import detect  # noqa: E402
from shell_model import Command  # noqa: E402

GH = "g" + "h"
REAL_COMMAND = (
    GH + ' api -X PATCH repos/EdbertChan/catstack/pulls/393 -f base=main '
    '-f "title=[Error messages](1) explicit-failures runs by default" '
    "-F body=@/tmp/scratch/restack-pr2.md --jq '\"#\\(.number) base=\\(.base.ref) \\(.title)\"'"
)


def _repo(path: str, with_tool: bool) -> None:
    os.makedirs(os.path.join(path, ".git"))
    if with_tool:
        os.makedirs(os.path.join(path, "scripts"))
        open(os.path.join(path, "scripts", "create-pr.mjs"), "w").close()


def _run(command: str, cwd: str) -> str:
    err = io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}))
    try:
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            claude_pretooluse.main()
    finally:
        sys.stdin = old
    return err.getvalue()


class TestApiRepoSpec(unittest.TestCase):
    def test_repo_spec_comes_from_the_endpoint_path(self):
        for endpoint in ("repos/EdbertChan/catstack/pulls/393", "/repos/EdbertChan/catstack/pulls/393"):
            with self.subTest(endpoint=endpoint):
                write = detect.classify_pr_text_write(
                    Command((GH, "api", "-X", "PATCH", endpoint, "-F", "body=@b.md"), "/s")
                )
                self.assertEqual(write.repo_spec, "EdbertChan/catstack")

    def test_placeholder_endpoint_means_the_current_repo(self):
        write = detect.classify_pr_text_write(
            Command((GH, "api", "-X", "PATCH", "repos/{owner}/{repo}/pulls/7", "-F", "body=@b.md"), "/s")
        )
        self.assertIsNone(write.repo_spec)


class TestApiRepoScope(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        os.environ[detect.GITHUB_CHECKOUTS_ROOT_ENV] = self.root.name
        self.addCleanup(os.environ.pop, detect.GITHUB_CHECKOUTS_ROOT_ENV, None)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        os.environ[detect.STATE_DIR_ENV] = state.name
        self.addCleanup(os.environ.pop, detect.STATE_DIR_ENV, None)
        self.session = os.path.join(self.root.name, "Invoker")
        _repo(self.session, with_tool=True)

    def test_real_catstack_edit_from_an_invoker_checkout_is_out_of_scope(self):
        _repo(os.path.join(self.root.name, "catstack"), with_tool=False)
        self.assertEqual(_run(REAL_COMMAND, self.session), "")

    def test_edit_of_a_repo_with_no_local_checkout_is_out_of_scope(self):
        self.assertEqual(_run(REAL_COMMAND, self.session), "")

    def test_edit_of_a_sibling_repo_that_has_the_tool_is_checked_there(self):
        _repo(os.path.join(self.root.name, "catstack"), with_tool=True)
        err = _run(REAL_COMMAND, self.session)
        self.assertIn("could not check", err)
        self.assertIn("body file not found", err)
        self.assertIn("restack-pr2.md", err)


if __name__ == "__main__":
    unittest.main()
