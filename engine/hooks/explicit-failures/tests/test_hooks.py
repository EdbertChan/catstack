#!/usr/bin/env python3
"""Tests for the explicit-failures PreToolUse hook.

Each fixture pair under tests/fixtures/ is one silent-failure shape:
`<shape>_fires.*` must produce at least one advisory line, `<shape>_silent.*`
must produce none. The hidden_stock pair vendors the real defect the
principle was written from (`if not lots[t]: ... continue`) and its fix.

Run: python3 -m unittest discover -s engine/hooks/explicit-failures/tests -v
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402

ON = {detect.ENABLED_ENV: "1"}
LINE_RE = re.compile(
    r"^[^\n]+:\d+: .+ — explicit-failures: raise, log with context, or emit a status row \(principle-explicit-errors\)$"
)


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def write_payload(name: str, content: str | None = None) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": f"/repo/{name}", "content": fixture(name) if content is None else content}}


def bash_payload(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def run_hook(payload: dict, env: dict | None = None):
    err, out = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, env if env is not None else ON, clear=False):
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with redirect_stderr(err), redirect_stdout(out):
                try:
                    claude_pretooluse.main()
                except SystemExit as exc:
                    return exc.code, err.getvalue(), out.getvalue()
    return 0, err.getvalue(), out.getvalue()


def lines_for(payload: dict) -> list[str]:
    tool_input = payload["tool_input"]
    return detect.report_lines(payload["tool_name"], tool_input)


class TestFires(unittest.TestCase):
    def test_fires_on_except_pass_fixture(self):
        hits = lines_for(write_payload("except_pass_fires.py"))
        self.assertEqual(len(hits), 2, hits)
        self.assertIn("except_pass_fires.py:5: `except OSError: pass`", hits[0])
        self.assertIn("except_pass_fires.py:13: `except ValueError: pass`", hits[1])

    def test_fires_on_if_none_bare_exit_fixture(self):
        hits = lines_for(write_payload("if_none_bare_exit_fires.py"))
        shapes = [h.split(" — ")[0] for h in hits]
        self.assertEqual(
            shapes,
            [
                "/repo/if_none_bare_exit_fires.py:2: `if not rows:` guard that only returns",
                "/repo/if_none_bare_exit_fires.py:7: `if not ticker:` guard that only continues",
                "/repo/if_none_bare_exit_fires.py:10: `if quote is None:` guard that only breaks",
                "/repo/if_none_bare_exit_fires.py:17: `if len(lots) == 0:` guard that only returns",
                "/repo/if_none_bare_exit_fires.py:23: `if table.get(key) == None:` guard that only returns",
            ],
        )

    def test_fires_on_try_except_continue_fixture(self):
        hits = lines_for(write_payload("try_except_continue_fires.py"))
        self.assertEqual(len(hits), 1, hits)
        self.assertIn(":6: `except (KeyError, ValueError):` block that only continues", hits[0])

    def test_fires_on_js_blank_catch_fixture(self):
        hits = lines_for(write_payload("catch_blank_fires.ts"))
        self.assertEqual(len(hits), 2, hits)
        self.assertIn("catch_blank_fires.ts:4: `catch {}` with an empty body", hits[0])
        self.assertIn("catch_blank_fires.ts:13: catch block that only `continue`s", hits[1])

    def test_fires_on_js_comment_only_catch_body(self):
        text = "try { a() } catch (e) {\n  // swallow\n}\n"
        hits = detect.scan_js(text)
        self.assertEqual(hits, [(1, "`catch {}` with an empty body")])

    def test_fires_on_promise_catch_noop_fixture(self):
        hits = lines_for(write_payload("promise_catch_noop_fires.js"))
        self.assertEqual([h.split(": ", 1)[1].split(" — ")[0] for h in hits], ["`.catch(() => {})` no-op rejection handler"] * 2)
        self.assertTrue(hits[0].startswith("/repo/promise_catch_noop_fires.js:4:"), hits[0])

    def test_fires_on_js_null_guard_bare_exit_fixture(self):
        hits = lines_for(write_payload("null_guard_bare_exit_fires.ts"))
        self.assertEqual(len(hits), 4, hits)
        self.assertIn(":4: `if (!row.ticker)` guard that only exits", hits[0])
        self.assertIn(":6: `if (px == null)` guard that only exits", hits[1])
        self.assertIn(":9: `if (out.length === 0)` guard that only exits", hits[2])
        self.assertIn(":14: `if (lots === undefined)` guard that only exits", hits[3])

    def test_fires_on_bash_heredoc_fixture_with_target_path(self):
        hits = lines_for(bash_payload(fixture("heredoc_write_fires.sh")))
        self.assertEqual(len(hits), 1, hits)
        self.assertTrue(hits[0].startswith("build.py:4: `if not lots[t]:` guard that only continues"), hits[0])

    def test_fires_on_bash_heredoc_without_path_using_both_grammars(self):
        cmd = "python3 - <<EOF\ntry:\n    x()\nexcept: pass\nEOF\nnode - <<'JS'\ntry { y() } catch {}\nJS\n"
        hits = lines_for(bash_payload(cmd))
        self.assertEqual([h.split(" — ")[0] for h in hits], ["<heredoc>:3: `except: pass`", "<heredoc>:1: `catch {}` with an empty body"])

    def test_fires_on_edit_and_multiedit_shapes(self):
        edit = {"tool_name": "Edit", "tool_input": {"file_path": "/r/a.py", "old_string": "x", "new_string": "if not x:\n    return None\n"}}
        multi = {"tool_name": "MultiEdit", "tool_input": {"file_path": "/r/a.ts", "edits": [{"new_string": "let a = 1;\n"}, {"new_string": "p.catch(() => {});\n"}]}}
        self.assertEqual(len(lines_for(edit)), 1)
        self.assertEqual(len(lines_for(multi)), 1)

    def test_hook_fires_advisory_only_exit_zero_with_additional_context(self):
        code, err, out = run_hook(write_payload("except_pass_fires.py"))
        self.assertEqual(code, 0)
        for line in err.strip().splitlines():
            self.assertRegex(line, LINE_RE)
        parsed = json.loads(out)
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(parsed["hookSpecificOutput"]["additionalContext"], err.strip())

    def test_hook_fires_by_default_with_no_env_and_no_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = dict(write_payload("except_pass_fires.py"), cwd=tmp)
            code, err, _ = run_hook(payload, env={detect.ENABLED_ENV: ""})
        self.assertEqual(code, 0)
        self.assertIn("`except OSError: pass`", err)

    def test_hidden_stock_build_lots_defect_fires(self):
        """Effectiveness: the vendored ed4495c-era `build_lots_and_realized` body drops
        a sell with no cost lot behind a bare `continue`; the hook names that line."""
        code, err, _ = run_hook(write_payload("hidden_stock_build_lots_fires.py"))
        self.assertEqual(code, 0)
        self.assertIn("hidden_stock_build_lots_fires.py:21: `if not lots[t]:` guard that only continues", err)
        self.assertIn("emit a status row (principle-explicit-errors)", err)

    def test_reported_hits_are_capped_with_a_trailer(self):
        text = "".join(f"if not v{i}:\n    continue\n" for i in range(detect.MAX_REPORTED + 3))
        with patch.dict(os.environ, ON):
            message = detect.decide(write_payload("x.py", text))
        self.assertEqual(len(message.splitlines()), detect.MAX_REPORTED + 1)
        self.assertTrue(message.splitlines()[-1].startswith("(+3 more"), message)


class TestSilent(unittest.TestCase):
    def assert_silent(self, payload: dict):
        self.assertEqual(lines_for(payload), [])
        code, err, out = run_hook(payload)
        self.assertEqual((code, err, out), (0, "", ""))

    def test_silent_on_except_with_log_or_raise_fixture(self):
        self.assert_silent(write_payload("except_pass_silent.py"))

    def test_silent_on_if_none_with_status_row_fixture(self):
        self.assert_silent(write_payload("if_none_bare_exit_silent.py"))

    def test_silent_on_try_except_with_status_row_fixture(self):
        self.assert_silent(write_payload("try_except_continue_silent.py"))

    def test_silent_on_js_catch_with_real_body_fixture(self):
        self.assert_silent(write_payload("catch_blank_silent.ts"))

    def test_silent_on_promise_catch_with_handler_fixture(self):
        self.assert_silent(write_payload("promise_catch_noop_silent.js"))

    def test_silent_on_js_null_guard_with_status_row_fixture(self):
        self.assert_silent(write_payload("null_guard_bare_exit_silent.ts"))

    def test_silent_on_bash_heredoc_with_status_row_and_plain_text_fixture(self):
        self.assert_silent(bash_payload(fixture("heredoc_write_silent.sh")))

    def test_silent_on_pragma_allow_marker_fixture(self):
        self.assert_silent(write_payload("allow_marker_silent.py"))

    def test_silent_on_explicit_failures_allow_comment_line(self):
        py = "for r in rows:\n    if not r:\n        # explicit-failures: allow\n        continue\n"
        self.assertEqual(detect.scan_python(py), [])
        py2 = "# explicit-failures: allow\nexcept ValueError:\n    pass\n"
        self.assertEqual(detect.scan_python(py2), [])
        js = "if (!el) return; // explicit-failures: allow\n"
        self.assertEqual(detect.scan_js(js), [])

    def test_silent_on_non_code_files_and_non_heredoc_bash(self):
        self.assert_silent({"tool_name": "Write", "tool_input": {"file_path": "/r/notes.md", "content": "except: pass\n"}})
        self.assert_silent({"tool_name": "Write", "tool_input": {"file_path": "/r/x.json", "content": "{}"}})
        self.assert_silent(bash_payload("grep -n 'except: pass' src/*.py && echo 'if not x: continue'"))

    def test_silent_on_guards_that_are_not_null_checks(self):
        py = "for r in rows:\n    if r.delta >= 0:\n        continue\n    if need <= 1e-12:\n        continue\n"
        self.assertEqual(detect.scan_python(py), [])
        js = "for (const r of rows) { if (r.delta >= 0) continue; if (x !== null) return; }\n"
        self.assertEqual(detect.scan_js(js), [])

    def test_silent_when_env_turns_it_off(self):
        for value in ("0", "false", "off", "no"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                payload = dict(write_payload("except_pass_fires.py"), cwd=tmp)
                self.assertNotEqual(lines_for(payload), [])
                code, err, out = run_hook(payload, env={detect.ENABLED_ENV: value})
                self.assertEqual((code, err, out), (0, "", ""))

    def test_fails_open_on_garbage_stdin(self):
        err, out = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, ON), patch.object(sys, "stdin", io.StringIO("nope")):
            with redirect_stderr(err), redirect_stdout(out):
                claude_pretooluse.main()
        self.assertEqual((err.getvalue(), out.getvalue()), ("", ""))


if __name__ == "__main__":
    unittest.main()
