from __future__ import annotations

import glob
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402


VALIDATOR_FAILS = (
    'console.error("- Missing required section: ## Test Plan");\n'
    "process.exit(1);\n"
)


def _repo() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    os.makedirs(os.path.join(tmp.name, "scripts"))
    os.makedirs(os.path.join(tmp.name, ".git"))
    with open(os.path.join(tmp.name, "scripts", "validate-pr-body.mjs"), "w") as f:
        f.write(VALIDATOR_FAILS)
    return tmp


def _body_file(directory: str, name: str = "pr-body.md") -> str:
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write("## Summary\n\nhi\n")
    return path


class _stdin:
    def __init__(self, text: str):
        self._text = text
        self._old = None

    def __enter__(self):
        self._old = sys.stdin
        sys.stdin = io.StringIO(self._text)

    def __exit__(self, *exc):
        sys.stdin = self._old


class EnvIsolated(unittest.TestCase):
    def setUp(self):
        self._metrics = tempfile.TemporaryDirectory()
        self._state = tempfile.TemporaryDirectory()
        self.addCleanup(self._metrics.cleanup)
        self.addCleanup(self._state.cleanup)
        self._previous = {
            "CATSTACK_HOOK_METRICS_DIR": os.environ.get("CATSTACK_HOOK_METRICS_DIR"),
            "CATSTACK_HOOK_MODE_PR_SCHEMA_GATE": os.environ.get("CATSTACK_HOOK_MODE_PR_SCHEMA_GATE"),
            detect.STATE_DIR_ENV: os.environ.get(detect.STATE_DIR_ENV),
        }
        os.environ["CATSTACK_HOOK_METRICS_DIR"] = self._metrics.name
        os.environ[detect.STATE_DIR_ENV] = self._state.name
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _run(self, command: str, cwd: str) -> tuple[int, str, str]:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
        err, out = io.StringIO(), io.StringIO()
        code = 0
        try:
            with redirect_stderr(err), redirect_stdout(out), _stdin(payload):
                claude_pretooluse.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return code, err.getvalue(), out.getvalue()

    def _event_rows(self) -> list[dict[str, object]]:
        rows = []
        for path in glob.glob(os.path.join(self._metrics.name, "events-*.jsonl")):
            with open(path, encoding="utf-8") as f:
                rows.extend(json.loads(line) for line in f if line.strip())
        return rows


@unittest.skipUnless(shutil.which("node"), "node is required to run the repo validator stub")
class TestSdkModeAndEvents(EnvIsolated):
    def test_mode_override_can_turn_warn_finding_into_stop(self):
        os.environ["CATSTACK_HOOK_MODE_PR_SCHEMA_GATE"] = "stop"
        with _repo() as repo:
            body = _body_file(repo)
            code, err, out = self._run("gh pr edit 7 --body-file " + body, repo)
        self.assertEqual(code, 2)
        self.assertIn("does not follow this repo's PR style", err)
        self.assertEqual(out, "")

    def test_each_finding_writes_one_event_row_with_rule_id(self):
        with _repo() as repo:
            one = _body_file(repo, "one.md")
            two = _body_file(repo, "two.md")
            code, _err, out = self._run(
                f"gh pr edit 7 --body-file {one} && gh pr edit 8 --body-file {two}",
                repo,
            )
        self.assertEqual(code, 0)
        self.assertIn("additionalContext", out)
        rows = [
            row for row in self._event_rows()
            if row.get("hook") == "pr-schema-gate" and row.get("action") == "warned"
        ]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.get("rule_id") for row in rows}, {"pr-schema-gate.style-failed"})


if __name__ == "__main__":
    unittest.main()
