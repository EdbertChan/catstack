#!/usr/bin/env python3
"""Unit tests for corpus_scan.py.

Run: python3 -m unittest discover -s skills/reflect/scripts/tests -v
(stdlib unittest only - no pytest in this environment)

Covers the pure/deterministic pieces only - no SSH, no real transcripts.
The two things worth locking down: (1) remote_scan_command's OUTPUT is
exactly what gets executed when --confirm-remote-scan is passed, since
that's the "show the exact command" transparency guarantee the skill
promises; (2) bucket_summary actually flags concurrent-host bursts, since
that's the whole reason this script exists over token_audit.py/
top_sessions.py.
"""
import contextlib
import io
import os
import sys
import unittest
import unittest.mock

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import corpus_scan  # noqa: E402


class TestMtimeMinutes(unittest.TestCase):
    def test_whole_hours(self):
        self.assertEqual(corpus_scan._mtime_minutes(24), 1440)
        self.assertEqual(corpus_scan._mtime_minutes(1), 60)

    def test_fractional_hours_round_not_truncate(self):
        # 0.5h must become a plain int minute count find(1) accepts on both
        # BSD (bfs) and GNU find - a fractional -mtime silently matches
        # nothing (the bug this function exists to prevent).
        self.assertEqual(corpus_scan._mtime_minutes(0.5), 30)
        self.assertIsInstance(corpus_scan._mtime_minutes(0.5), int)

    def test_never_zero(self):
        self.assertGreaterEqual(corpus_scan._mtime_minutes(0.001), 1)


class TestRemoteScanCommand(unittest.TestCase):
    def setUp(self):
        self.target = {"host": "1.2.3.4", "user": "invoker", "sshKeyPath": "/k"}

    def test_uses_mmin_not_mtime(self):
        cmd = corpus_scan.remote_scan_command(self.target, "e2e", 24)
        script = cmd[-1]
        self.assertIn("-mmin -1440", script)
        self.assertNotIn("-mtime", script)

    def test_ssh_args_from_target_config(self):
        cmd = corpus_scan.remote_scan_command(self.target, "e2e", 1)
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("-i", cmd)
        self.assertIn("/k", cmd)
        self.assertIn("invoker@1.2.3.4", cmd)

    def test_pattern_is_embedded_verbatim(self):
        cmd = corpus_scan.remote_scan_command(self.target, "e2e|playwright", 24)
        self.assertIn("e2e|playwright", cmd[-1])

    def test_read_only_no_write_commands(self):
        # `2>/dev/null` (discarding stderr) is fine and expected; nothing
        # here should write real output anywhere or reach out over the
        # network beyond the single already-open ssh session.
        cmd = corpus_scan.remote_scan_command(self.target, "e2e", 24)
        script = cmd[-1]
        for banned in ("rm ", "mv ", "scp", "curl", "wget"):
            self.assertNotIn(banned, script)
        self.assertNotIn(">/dev/null 2>&1 &", script)  # no backgrounding/detaching either

    def test_stderr_discarded_not_a_real_write(self):
        cmd = corpus_scan.remote_scan_command(self.target, "e2e", 24)
        script = cmd[-1]
        # every '>' in this script is a `2>/dev/null` stderr discard
        for m in __import__("re").finditer(r"[^2]>", script):
            self.fail(f"found a non-stderr redirect at {m.start()}: {script[max(0,m.start()-10):m.start()+10]!r}")

    def test_includes_cursor_agent_transcripts(self):
        cmd = corpus_scan.remote_scan_command(self.target, "e2e", 24)
        script = cmd[-1]
        self.assertIn("~/.cursor/projects", script)
        self.assertIn("*/agent-transcripts/*/*.jsonl", script)
        self.assertIn("CURSOR", script)


class TestDiscoverLocalKinds(unittest.TestCase):
    def test_discover_local_docstring_names_cursor(self):
        # Guard: discover_local must keep Cursor in its contract even if the
        # find path is empty on a given machine (no real transcripts needed).
        self.assertIn("Cursor", corpus_scan.discover_local.__doc__)


class TestAuditOneCursor(unittest.TestCase):
    def test_audit_one_accepts_cursor_kind_without_tokens(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as handle:
            # Minimal cursor-shaped line: message with a tool_use, no usage.
            handle.write(
                '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"path":"a.py"}}]}}\n'
            )
            path = handle.name
        try:
            entry = corpus_scan.audit_one("cursor", path, {})
        finally:
            os.unlink(path)
        self.assertEqual(entry["kind"], "cursor")
        self.assertIsNone(entry["total_tokens"])
        self.assertEqual(entry["path"], path)


class TestBucketSummary(unittest.TestCase):
    def test_detects_concurrent_multi_host_burst(self):
        results = [
            {"host": "remote_digital_ocean_1", "ts_raw": "2026-08-15T07-37-08-abc"},
            {"host": "remote_digital_ocean_3", "ts_raw": "2026-08-15T07-38-01-abc"},
            {"host": "remote_digital_ocean_6", "ts_raw": "2026-08-15T07-38-23-abc"},
            {"host": "remote_digital_ocean_4", "ts_raw": "2026-08-15T09-10-00-abc"},  # isolated
        ]
        buckets = corpus_scan.bucket_summary(results, bucket_minutes=15)
        # three of four sessions land in the same 07:30 bucket, one each host
        same_window = [k for k in buckets if k[1] == "07" and k[2] == "30"]
        self.assertEqual(len(same_window), 3)
        for k in same_window:
            self.assertEqual(len(buckets[k]), 1)  # one session per host in that bucket
        isolated = [k for k in buckets if k[1] == "09"]
        self.assertEqual(len(isolated), 1)

    def test_ignores_entries_without_timestamp(self):
        results = [{"host": "local", "ts_raw": None}]
        buckets = corpus_scan.bucket_summary(results)
        self.assertEqual(len(buckets), 0)


class TestGrepMatchFilesSkips(unittest.TestCase):
    """_grep_match_files must survive one slow or oversized transcript: skip
    it with an explicit stderr line naming the path, and still return every
    other match. A 146 MB Codex rollout once raised TimeoutExpired out of
    the per-file grep and killed the whole corpus scan."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.fast = os.path.join(self.tmp.name, "fast.jsonl")
        self.slow = os.path.join(self.tmp.name, "slow.jsonl")
        self.other = os.path.join(self.tmp.name, "other.jsonl")
        for path, body in ((self.fast, "hit\n"), (self.slow, "hit\n"), (self.other, "hit\n")):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
        self.real_run = corpus_scan.subprocess.run

    def tearDown(self):
        corpus_scan.subprocess.run = self.real_run
        self.tmp.cleanup()

    def _fake_run_factory(self, timeout_on):
        import subprocess as sp

        listed = "\n".join([self.fast, self.slow, self.other]) + "\n"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "find":
                return sp.CompletedProcess(cmd, 0, stdout=listed, stderr="")
            if cmd[-1] == timeout_on:
                raise sp.TimeoutExpired(cmd, kwargs.get("timeout"))
            return sp.CompletedProcess(cmd, 0, stdout=cmd[-1] + "\n", stderr="")

        return fake_run

    def _run(self, **kwargs):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            matched = corpus_scan._grep_match_files(["find", self.tmp.name], "hit", 24, **kwargs)
        return matched, err.getvalue()

    def test_timeout_on_one_file_skips_it_and_keeps_the_rest(self):
        corpus_scan.subprocess.run = self._fake_run_factory(timeout_on=self.slow)
        matched, err = self._run()
        self.assertEqual(matched, [self.fast, self.other])
        self.assertIn(self.slow, err)
        self.assertIn("timed out", err)
        self.assertIn(str(corpus_scan.GREP_TIMEOUT_SECONDS), err)

    def test_file_above_max_bytes_is_skipped_with_stderr_line(self):
        corpus_scan.subprocess.run = self._fake_run_factory(timeout_on=None)
        with open(self.slow, "w", encoding="utf-8") as handle:
            handle.write("x" * 100)
        matched, err = self._run(max_file_bytes=50)
        self.assertEqual(matched, [self.fast, self.other])
        self.assertIn(self.slow, err)
        self.assertIn("max-file-bytes", err)
        self.assertIn("50", err)

    def test_default_cap_is_64_mb(self):
        self.assertEqual(corpus_scan.DEFAULT_MAX_FILE_BYTES, 64 * 1024 * 1024)

    def test_find_failure_raises_unchecked_instead_of_returning_empty(self):
        """An empty list reads as 'no sessions matched'. A listing that never
        ran is a different answer, so it must not come back as one."""
        import subprocess as sp

        def boom(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd, kwargs.get("timeout"))

        corpus_scan.subprocess.run = boom
        with self.assertRaises(corpus_scan.SourceUnchecked) as caught:
            self._run()
        self.assertIn(self.tmp.name, str(caught.exception))
        self.assertIn("TimeoutExpired", str(caught.exception))

    def test_find_timeout_leaves_room_for_a_large_projects_dir(self):
        self.assertGreaterEqual(corpus_scan.FIND_TIMEOUT_SECONDS, 300)


class TestUncheckedSources(unittest.TestCase):
    """One source whose listing fails is recorded as unchecked; the others
    are still scanned; a caller that passes no list gets the error."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        for sub in (".claude/projects/p", ".codex/sessions/2026"):
            os.makedirs(os.path.join(self.home, sub))
        self.codex_file = os.path.join(self.home, ".codex/sessions/2026/rollout-a.jsonl")
        with open(self.codex_file, "w", encoding="utf-8") as handle:
            handle.write("hit\n")
        self.real_run = corpus_scan.subprocess.run
        self.real_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home

        import subprocess as sp

        def fake_run(cmd, **kwargs):
            if cmd[0] == "find" and ".claude" in cmd[1]:
                raise sp.TimeoutExpired(cmd, kwargs.get("timeout"))
            if cmd[0] == "find" and ".codex" in cmd[1]:
                return sp.CompletedProcess(cmd, 0, stdout=self.codex_file + "\n", stderr="")
            if cmd[0] == "find":
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            return sp.CompletedProcess(cmd, 0, stdout=cmd[-1] + "\n", stderr="")

        corpus_scan.subprocess.run = fake_run

    def tearDown(self):
        corpus_scan.subprocess.run = self.real_run
        if self.real_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.real_home
        self.tmp.cleanup()

    def test_failed_source_is_recorded_and_the_rest_still_scanned(self):
        unchecked = []
        with contextlib.redirect_stderr(io.StringIO()):
            found = corpus_scan.discover_local("hit", 24, unchecked=unchecked)
        self.assertEqual([k for k, _p, _h in found], ["codex"])
        self.assertEqual([u["source"] for u in unchecked], ["claude"])
        self.assertIn(".claude", unchecked[0]["root"])

    def test_caller_without_an_unchecked_list_gets_the_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(corpus_scan.SourceUnchecked):
                corpus_scan.discover_local("hit", 24)

    def test_main_prints_unchecked_and_exits_3(self):
        out_path = os.path.join(self.tmp.name, "out.json")
        argv = ["corpus_scan.py", "hit", "--hours", "24", "--out", out_path]
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as caught:
                    corpus_scan.main()
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("UNCHECKED: claude", out.getvalue())
        self.assertTrue(os.path.exists(out_path))


if __name__ == "__main__":
    unittest.main()
