#!/usr/bin/env python3
"""Tests for the text-match-decision-warn PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/text-match-decision-warn/tests -v
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOKS_ROOT = HOOK_DIR.parent
FIXTURES = HOOK_DIR / "tests" / "fixtures"
sys.path.insert(0, str(HOOK_DIR))

import detect  # noqa: E402
import pretooluse  # noqa: E402

HOOK = "text-match-decision-warn"
PY_INCIDENT = "if any(signature in error for signature in _STARTUP_INFRA_SIGNATURES):"
TS_INCIDENT = "if (errorText.includes('No space left on device')) {"
ERROR = detect.SCOPE_ERROR
OUTPUT = detect.SCOPE_OUTPUT
PROSE = detect.SCOPE_PROSE


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def write_payload(path: str, content: str, **extra: object) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-1",
        "tool_name": "Write",
        "tool_input": {"file_path": path, "content": content},
        **extra,
    }


def edit_payload(path: str, new: str, old: str = "") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-1",
        "tool_name": "Edit",
        "tool_input": {"file_path": path, "old_string": old, "new_string": new},
    }


def hits_for(payload: dict) -> list[detect.Hit]:
    return detect.evaluate(payload).hits


def shapes(payload: dict) -> list[tuple[str, str]]:
    return [(hit.rule, hit.scope) for hit in hits_for(payload)]


def run_main(harness: str, stdin_text: str, metrics_dir: str) -> tuple[str, str]:
    out, err = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": metrics_dir}):
        with patch.object(sys, "stdin", io.StringIO(stdin_text)), redirect_stdout(out), redirect_stderr(err):
            pretooluse.main(harness)
    return out.getvalue(), err.getvalue()


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.metrics = self.root / "metrics"

    def warning_rows(self) -> list[dict]:
        path = self.metrics / f"{HOOK}-warnings.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestFires(TempDirCase):
    def test_fires_on_real_python_repair_outcome_line(self):
        hits = hits_for(write_payload("/repo/worker/repair.py", fixture("repair_outcome_fires.py")))
        self.assertEqual(
            [(h.line_no, h.line, h.rule, h.scope, h.baseline) for h in hits],
            [(9, PY_INCIDENT, "py-membership", ERROR, "absent")],
        )

    def test_fires_on_real_ts_failure_classifier_line(self):
        hits = hits_for(write_payload("/repo/src/failure-classifier.ts", fixture("failure_classifier_fires.ts")))
        self.assertEqual([(h.line_no, h.line, h.rule, h.scope) for h in hits], [(2, TS_INCIDENT, "js-substring", ERROR)])

    def test_fires_on_python_near_miss_shapes(self):
        cases = [
            ('if "No space left" not in stderr:', "py-membership", ERROR),
            ('if result.stderr.startswith("fatal:"):', "py-prefix", ERROR),
            ('if re.search(r"permission denied", proc.stdout, re.I):', "py-regex", OUTPUT),
            ('if "timeout" in str(exc):', "py-membership", ERROR),
            ('if "rate limit hit" in payload["error"]:', "py-membership", ERROR),
            ('if "approve" in task.get("description", "").lower():', "py-membership", PROSE),
            ('return "LGTM" in reply.strip()', "py-membership", OUTPUT),
            ('is_disk_full = "No space left on device" in error_text', "py-membership", ERROR),
            ("elif SIGNATURE_RE.search(comment_body):", "py-regex", OUTPUT),
            ('if prompt.lower().startswith("/plan"):', "py-prefix", PROSE),
        ]
        for line, rule, scope in cases:
            with self.subTest(line=line):
                self.assertEqual(shapes(edit_payload("/repo/src/worker.py", line)), [(rule, scope)])

    def test_fires_on_js_near_miss_shapes(self):
        cases = [
            ("if (message.includes('rate limit')) {", "js-substring", ERROR),
            ('if (result.stderr?.includes("fatal")) return;', "js-substring", ERROR),
            ("if (/timed out/i.test(output)) {", "js-regex-test", OUTPUT),
            ("const infra = String(err).startsWith('ECONNRESET');", "js-substring", ERROR),
            ("if (plan.description.endsWith('[skip]')) {", "js-substring", PROSE),
            ("if (stdout.match(/ready/)) {", "js-match", OUTPUT),
            ("return reply.indexOf('approved') !== -1;", "js-match", OUTPUT),
            ("if (FAILURE_PATTERN.test(logText)) {", "js-regex-test", ERROR),
        ]
        for line, rule, scope in cases:
            with self.subTest(line=line):
                self.assertEqual(shapes(edit_payload("/repo/src/worker.ts", line)), [(rule, scope)])

    def test_fires_on_shell_shapes(self):
        cases = [
            ('if grep -q "No space left" <<< "$output"; then', "sh-grep-herestring", OUTPUT),
            ('if echo "$out" | grep -q denied; then', "sh-echo-grep", OUTPUT),
            ('printf "%s" "$stderr" | grep -qi fatal && exit 1', "sh-echo-grep", ERROR),
            ('if [[ "$output" == *"ready"* ]]; then', "sh-glob-match", OUTPUT),
            ("[[ $message =~ fail ]] && retry", "sh-glob-match", ERROR),
        ]
        for line, rule, scope in cases:
            with self.subTest(line=line):
                self.assertEqual(shapes(edit_payload("/repo/scripts/check.sh", line)), [(rule, scope)])

    def test_fires_on_two_rules_in_one_edit_reports_both(self):
        new = "    " + PY_INCIDENT + '\n    if result.stderr.startswith("fatal:"):\n'
        self.assertEqual(
            shapes(edit_payload("/repo/src/worker.py", new)),
            [("py-membership", ERROR), ("py-prefix", ERROR)],
        )

    def test_fires_on_codex_apply_patch_added_lines_only(self):
        patch_text = (
            "*** Begin Patch\n*** Update File: /repo/src/classify.ts\n@@\n"
            " const fromContext = errorText.includes('x');\n"
            "-if (status === 'failed') {\n"
            "+" + TS_INCIDENT + "\n"
            "*** End Patch\n"
        )
        hits = hits_for({"tool_name": "apply_patch", "tool_input": {"command": ["apply_patch", patch_text]}})
        self.assertEqual([(h.file_path, h.line, h.rule) for h in hits], [("/repo/src/classify.ts", TS_INCIDENT, "js-substring")])

    def test_fires_on_codex_exec_wrapped_patch(self):
        wrapped = 'const patch = "*** Begin Patch\\n*** Add File: /repo/a.py\\n+if \\"No space\\" in stderr:\\n*** End Patch";'
        self.assertEqual(shapes({"tool_name": "exec", "tool_input": {"input": wrapped}}), [("py-membership", ERROR)])

    def test_fires_on_cursor_payload_aliases(self):
        cases = [
            {"tool_name": "edit_file", "tool_input": {"target_file": "/repo/a.ts", "code_edit": TS_INCIDENT}},
            {"toolName": "StrReplace", "toolInput": {"path": "/repo/a.py", "old_string": "", "new_string": 'if "x y" in stderr:'}},
            {"tool_name": "MultiEdit", "tool_input": {"file_path": "/repo/a.py", "edits": [{"old_string": "a", "new_string": "b = 1"}, {"old_string": "c", "new_string": 'if "x y" in stderr:'}]}},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(len(hits_for(payload)), 1)

    def test_hook_fires_claude_additional_context_with_guidance(self):
        out, err = run_main("claude", json.dumps(write_payload("/repo/worker/repair.py", fixture("repair_outcome_fires.py"))), str(self.metrics))
        self.assertEqual(err, "")
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"/repo/worker/repair.py:9 [py-membership; {ERROR}] `{PY_INCIDENT}`", context)
        for phrase in ("a status or phase field", "a typed failure class", "a gate state file", "`--output json`", "an exit code",
                       'decide from recorded state, not text', "~/.claude/skills/cat-mode/references/named-constraints.md"):
            self.assertIn(phrase, context)

    def test_hook_fires_cursor_agent_message_and_allows(self):
        out, _ = run_main("cursor", json.dumps(edit_payload("/repo/a.ts", TS_INCIDENT)), str(self.metrics))
        parsed = json.loads(out)
        self.assertEqual(parsed["permission"], "allow")
        self.assertIn("js-substring", parsed["agent_message"])

    def test_hook_fires_codex_context_and_stderr_copy(self):
        out, err = run_main("codex", json.dumps(edit_payload("/repo/a.ts", TS_INCIDENT)), str(self.metrics))
        self.assertIn("js-substring", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertIn("js-substring", err)

    def test_warning_log_row_written_when_hook_fires(self):
        run_main("claude", json.dumps(write_payload("/repo/worker/repair.py", fixture("repair_outcome_fires.py"))), str(self.metrics))
        rows = self.warning_rows()
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(
            {k: row[k] for k in ("hook", "harness", "session_id", "tool", "file_path", "line_no", "line", "rule", "scope", "baseline")},
            {"hook": HOOK, "harness": "claude", "session_id": "sess-1", "tool": "Write", "file_path": "/repo/worker/repair.py",
             "line_no": 9, "line": PY_INCIDENT, "rule": "py-membership", "scope": ERROR, "baseline": "absent"},
        )
        self.assertRegex(row["ts"], r"^\d{4}-\d{2}-\d{2}T")

    def test_warning_log_write_failure_is_reported_on_stderr_and_warning_still_fires(self):
        blocker = self.root / "a-file"
        blocker.write_text("x", encoding="utf-8")
        out, err = run_main("claude", json.dumps(edit_payload("/repo/a.ts", TS_INCIDENT)), str(blocker / "sub"))
        self.assertTrue(err.startswith(f"catstack-hook-error {HOOK}: could not write warning log to {blocker / 'sub'}"), err)
        self.assertIn("js-substring", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_reported_hits_are_capped_with_a_trailer(self):
        text = "\n".join(f'if "x y" in stderr_{i}:' for i in range(detect.MAX_REPORTED + 3))
        message = detect.format_message(hits_for(edit_payload("/repo/a.py", text)))
        self.assertIn("(+3 more in this edit)", message)


class TestSilent(TempDirCase):
    def assert_silent(self, payload: dict) -> None:
        self.assertEqual(hits_for(payload), [])
        out, err = run_main("claude", json.dumps(payload), str(self.metrics))
        self.assertEqual((out, err), ("", ""))
        self.assertEqual(self.warning_rows(), [])

    def test_silent_on_recorded_state_phase_check(self):
        self.assert_silent(write_payload("/repo/src/launch.py", fixture("launch_state_silent.py")))

    def test_silent_on_markdown_that_says_in_error(self):
        self.assert_silent(write_payload("/repo/docs/notes.md", fixture("notes_silent.md")))

    def test_silent_on_test_file_asserting_error_message(self):
        self.assert_silent(write_payload("/repo/tests/test_worker.py", fixture("error_message_assert_silent.py")))
        for path, text in (
            ("/repo/src/__tests__/classify.test.ts", TS_INCIDENT),
            ("/repo/pkg/worker_test.py", 'if "boom" in str(exc):'),
            ("/repo/e2e/flow.spec.ts", TS_INCIDENT),
            ("/repo/scripts/test-create-pr-stack-workflow.mjs", TS_INCIDENT),
            ("/repo/scripts/repro/repro-disk-full.sh", 'if grep -q "No space left" <<< "$output"; then'),
            ("/repo/src/worker-test.ts", TS_INCIDENT),
        ):
            with self.subTest(path=path):
                self.assert_silent(edit_payload(path, text))

    def test_fires_when_test_assertion_shape_lands_in_production_path(self):
        self.assertEqual(
            shapes(write_payload("/repo/src/worker.py", fixture("error_message_assert_silent.py"))),
            [("py-membership", ERROR)],
        )

    def test_silent_on_near_neighbours(self):
        cases = [
            ("/repo/a.py", "for line in output.splitlines():"),
            ("/repo/a.py", 'if error_code.startswith("E1"):'),
            ("/repo/a.py", 'if status == "failed":'),
            ("/repo/a.py", 'match = re.search(r"exit code (\\d+)", stderr)'),
            ("/repo/a.py", 'if "boom" in errors:'),
            ("/repo/a.py", "if key in message:"),
            ("/repo/a.py", 'if "error" in response:'),
            ("/repo/a.py", "if proc.returncode != 0:"),
            ("/repo/a.py", '# if "No space left" in error:'),
            ("/repo/a.py", "print('\"No space left\" in error')"),
            ("/repo/a.py", 'if execution.get("phase") == "failed":'),
            ("/repo/a.ts", "if (errors.includes(id)) {"),
            ("/repo/a.ts", "if (response.ok) {"),
            ("/repo/a.ts", 'if (url.startsWith("https://x")) {'),
            ("/repo/a.ts", '// if (errorText.includes("x")) {'),
            ("/repo/a.ts", "const m = stdout.match(/v(\\d+)/);"),
            ("/repo/a.sh", 'grep -q "ready" status.txt'),
            ("/repo/a.sh", 'n=$(echo "$out" | grep -c x)'),
            ("/repo/a.sh", 'if [[ "$status" == *"fail"* ]]; then'),
            ("/repo/a.py", "if from_transcript is None or tool_id not in from_transcript:"),
            ("/repo/scripts/check.mjs", "assert(result.stderr.includes('empty slice'), 'should list the commit');"),
            ("/repo/a.py", 'assert "boom" in str(exc)'),
            ("/repo/a.ts", "expect(errorText.includes('No space')).toBe(true);"),
        ]
        for path, line in cases:
            with self.subTest(line=line):
                self.assert_silent(edit_payload(path, line))

    def test_silent_on_lines_already_present_in_old_string(self):
        old = "    " + PY_INCIDENT + '\n        return "infra"\n'
        new = "    " + PY_INCIDENT + '\n        return "infra-disk"\n'
        self.assert_silent(edit_payload("/repo/src/worker.py", new, old))

    def test_silent_on_write_that_keeps_existing_text_match_line(self):
        target = self.root / "worker.py"
        target.write_text("def f(error):\n    " + PY_INCIDENT + "\n        return 1\n", encoding="utf-8")
        content = "def f(error):\n    " + PY_INCIDENT + "\n        return 2\n"
        self.assert_silent(write_payload(str(target), content))

    def test_silent_on_allow_marker(self):
        self.assert_silent(edit_payload("/repo/a.py", 'if "No space left" in stderr:  # text-match-decision-warn: allow'))

    def test_silent_on_non_edit_tools(self):
        self.assert_silent({"tool_name": "Bash", "tool_input": {"command": 'if grep -q x <<< "$output"; then echo; fi'}})
        self.assert_silent({"tool_name": "Read", "tool_input": {"file_path": "/repo/a.py"}})

    def test_silent_on_data_and_extensionless_files(self):
        for path in ("/repo/config.yaml", "/repo/data.json", "/repo/bin/run", "/repo/notes.txt"):
            with self.subTest(path=path):
                self.assert_silent(edit_payload(path, 'if "No space left" in stderr:'))


class TestUnchecked(TempDirCase):
    def test_unreadable_baseline_scans_every_added_line(self):
        directory_named_like_code = self.root / "existing.py"
        directory_named_like_code.mkdir()
        hits = hits_for(write_payload(str(directory_named_like_code), PY_INCIDENT))
        self.assertEqual([(h.rule, h.baseline) for h in hits], [("py-membership", "unreadable")])

    def test_too_large_baseline_scans_every_added_line(self):
        target = self.root / "worker.py"
        target.write_text(PY_INCIDENT + "\n", encoding="utf-8")
        with patch.object(detect, "MAX_BASELINE_BYTES", 10):
            hits = hits_for(write_payload(str(target), PY_INCIDENT + "\n"))
        self.assertEqual([(h.rule, h.baseline) for h in hits], [("py-membership", "unreadable")])

    def test_too_large_content_is_unchecked_not_clean(self):
        payload = write_payload("/repo/a.py", PY_INCIDENT)
        with patch.object(detect, "MAX_CONTENT_BYTES", 10):
            scan = detect.evaluate(payload)
            _, err = run_main("claude", json.dumps(payload), str(self.metrics))
        self.assertEqual(scan.hits, [])
        self.assertEqual(len(scan.unchecked), 1, scan.unchecked)
        self.assertIn(f"{HOOK}: unchecked: /repo/a.py: added content is", err)

    def test_malformed_stdin_reports_caught_error_not_silent(self):
        out, err = run_main("claude", "nope", str(self.metrics))
        self.assertEqual(out, "")
        self.assertTrue(err.startswith(f"catstack-hook-error {HOOK}: unreadable hook payload, nothing checked"), err)

    def test_non_object_payload_reports_caught_error_not_silent(self):
        _, err = run_main("claude", "[1, 2]", str(self.metrics))
        self.assertTrue(err.startswith(f"catstack-hook-error {HOOK}: hook payload is not a JSON object"), err)

    def test_scanner_crash_reports_caught_error_not_silent(self):
        with patch.object(pretooluse, "evaluate", side_effect=RuntimeError("kaboom")):
            out, err = run_main("claude", json.dumps(edit_payload("/repo/a.ts", TS_INCIDENT)), str(self.metrics))
        self.assertEqual(out, "")
        self.assertIn(f"catstack-hook-error {HOOK}: scanner error, nothing checked: RuntimeError: kaboom", err)


class TestRunnerMetrics(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.root / "home"
        hooks = self.home / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "_runner").symlink_to(HOOKS_ROOT / "_runner")
        (hooks / HOOK).symlink_to(HOOK_DIR)
        self.runner = hooks / "_runner" / "run.py"

    def env(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.home), "CATSTACK_HOOK_METRICS_DIR": str(self.metrics)}

    def run_via_runner(self, payload: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.runner), "--timeout", "10", f"{HOOK}/claude_pretooluse.py"],
            input=json.dumps(payload), capture_output=True, text=True, env=self.env(), timeout=30,
        )

    def run_rows(self) -> list[dict]:
        return [json.loads(line) for line in (self.metrics / "runs.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_runner_metrics_row_spoke_when_hook_fires(self):
        result = self.run_via_runner(edit_payload("/repo/src/failure-classifier.ts", TS_INCIDENT))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.run_rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(
            {k: rows[0][k] for k in ("harness", "hook", "script", "event", "session_id", "outcome", "exit_code")},
            {"harness": "claude", "hook": HOOK, "script": "claude_pretooluse.py", "event": "PreToolUse",
             "session_id": "sess-1", "outcome": "spoke", "exit_code": 0},
        )
        self.assertEqual(len(self.warning_rows()), 1)

    def test_runner_metrics_row_silent_on_clean_edit(self):
        result = self.run_via_runner(write_payload("/repo/src/launch.py", fixture("launch_state_silent.py")))
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        rows = self.run_rows()
        self.assertEqual([(r["hook"], r["outcome"]) for r in rows], [(HOOK, "silent")])
        self.assertEqual(self.warning_rows(), [])

    def test_report_shows_hook_counts_when_it_fires(self):
        self.run_via_runner(edit_payload("/repo/src/failure-classifier.ts", TS_INCIDENT))
        self.run_via_runner(write_payload("/repo/src/launch.py", fixture("launch_state_silent.py")))
        settings = {"hooks": {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{
            "type": "command",
            "command": f"python3 $HOME/.claude/hooks/_runner/run.py --timeout 4.5 {HOOK}/claude_pretooluse.py",
            "timeout": 5,
        }]}]}}
        (self.home / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        report = subprocess.run(
            [sys.executable, str(HOOKS_ROOT / "_runner" / "report.py"), "--since", "1d"],
            capture_output=True, text=True, env=self.env(), timeout=30,
        )
        self.assertEqual(report.returncode, 0, report.stdout + report.stderr)
        self.assertRegex(report.stdout, re.compile(rf"^claude {HOOK}/claude_pretooluse\.py 2 1 1 0 0 0 0 \d+$", re.M))


if __name__ == "__main__":
    unittest.main()
