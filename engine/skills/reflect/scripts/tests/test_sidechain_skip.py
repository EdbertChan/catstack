"""Subagent (sidechain) transcripts must not count as human sessions.

Claude Code writes Task-tool subagent transcripts to
<session-dir>/subagents/agent-<id>.jsonl; every record carries
isSidechain: true and the first record is the parent's instruction with
role=user. Recursive discovery picked those up as sessions, so each parent
instruction counted as a human "go" and inflated lead/deploy/rework.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import collect_dora_events  # noqa: E402
import corpus_scan  # noqa: E402
import dora_ai  # noqa: E402
import top_sessions  # noqa: E402

SESSION = "11111111-2222-3333-4444-555555555555"


def _row(text: str, *, sidechain: bool, role: str = "user") -> str:
    row = {
        "type": role,
        "isSidechain": sidechain,
        "sessionId": SESSION,
        "timestamp": "2026-01-01T00:00:00.000Z",
        "message": {"role": role, "content": text},
    }
    if sidechain:
        row["agentId"] = "agent-x"
    return json.dumps(row)


def _write(path: str, lines: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


class _FakeHome(unittest.TestCase):
    """One normal session, one subagents/ transcript, one sidechain-by-content file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = self.tmp.name
        project = os.path.join(home, ".claude", "projects", "-Users-x-repo")
        self.normal = os.path.join(project, f"{SESSION}.jsonl")
        self.subagent = os.path.join(project, SESSION, "subagents", "agent-x.jsonl")
        self.by_content = os.path.join(project, "aaaa-side.jsonl")
        _write(self.normal, [_row("hello go ahead", sidechain=False)])
        _write(self.subagent, [_row("hello go ahead", sidechain=True)])
        _write(self.by_content, [_row("hello go ahead", sidechain=True)])
        self._env = mock.patch.dict(os.environ, {"HOME": home})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()


class TestIsSidechainTranscript(_FakeHome):
    def test_path_and_first_record(self):
        self.assertFalse(corpus_scan.is_sidechain_transcript(self.normal))
        self.assertTrue(corpus_scan.is_sidechain_transcript(self.subagent))
        self.assertTrue(corpus_scan.is_sidechain_transcript(self.by_content))

    def test_missing_or_garbage_file_is_not_sidechain(self):
        self.assertFalse(corpus_scan.is_sidechain_transcript(self.normal + ".missing"))
        garbage = os.path.join(self.tmp.name, "garbage.jsonl")
        _write(garbage, ["not json"])
        self.assertFalse(corpus_scan.is_sidechain_transcript(garbage))


class TestCollectorSkipsSidechain(_FakeHome):
    def _collect(self, **kwargs):
        with redirect_stderr(io.StringIO()):
            return collect_dora_events.collect(
                hours=24, skip_gh=True, skip_sessions=False, skip_git=True, **kwargs
            )

    def test_default_skips_and_counts(self):
        events = self._collect()
        started = [e for e in events if e["kind"] == "execution_started"]
        self.assertEqual(len(started), 1)
        summary = dora_ai.summarize(events, window_days=1.0)
        skipped = summary["subagent_sessions_skipped"]
        self.assertEqual(skipped["count"], 2)
        parent_id = collect_dora_events._session_id(self.normal)
        self.assertEqual(skipped["by_parent"][parent_id], 1)
        public = collect_dora_events.public_summary(summary, window_days=1.0, hours=24)
        self.assertEqual(public["subagent_sessions_skipped"]["count"], 2)
        self.assertEqual(public["subagent_sessions_skipped"]["parents"], 2)
        self.assertIn("subagent_sessions_skipped=2", dora_ai.format_report(summary))

    def test_include_sidechain_restores_old_behaviour(self):
        events = self._collect(include_sidechain=True)
        started = [e for e in events if e["kind"] == "execution_started"]
        self.assertEqual(len(started), 3)
        summary = dora_ai.summarize(events, window_days=1.0)
        self.assertEqual(summary["subagent_sessions_skipped"]["count"], 0)

    def test_cli_flag(self):
        for argv, expected in (([], 1), (["--include-sidechain"], 3)):
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = collect_dora_events.main(["--skip-gh", "--skip-git", "--hours", "24", *argv])
            self.assertEqual(rc, 0)
            events = json.loads(out.getvalue())
            started = [e for e in events if e["kind"] == "execution_started"]
            self.assertEqual(len(started), expected, argv)

    def test_human_approval_utterance_yields_plan_approved(self):
        err = io.StringIO()
        with redirect_stderr(err):
            events = collect_dora_events.collect(
                hours=24, skip_gh=True, skip_sessions=False, skip_git=True
            )
        self.assertNotIn("skip session", err.getvalue())
        self.assertIn("plan_approved", [e["kind"] for e in events])

    def test_drop_sidechain_shared_by_both_discovery_paths(self):
        found = [
            ("claude", self.normal),
            ("claude", self.subagent),
            ("claude", self.by_content),
            ("codex", "/nope/rollout-1.jsonl"),
        ]
        kept, skipped = collect_dora_events._drop_sidechain(found, include_sidechain=False)
        self.assertEqual(kept, [("claude", self.normal), ("codex", "/nope/rollout-1.jsonl")])
        self.assertEqual(sum(skipped.values()), 2)
        kept, skipped = collect_dora_events._drop_sidechain(found, include_sidechain=True)
        self.assertEqual(kept, found)
        self.assertEqual(skipped, {})

class TestCorpusScanSkipsSidechain(_FakeHome):
    def test_discover_local_skips_and_reports(self):
        err = io.StringIO()
        with redirect_stderr(err):
            found = corpus_scan.discover_local("hello", 24)
        self.assertEqual([p for _k, p, _h in found], [self.normal])
        self.assertIn("subagent_sessions_skipped: 2", err.getvalue())

    def test_discover_local_include_sidechain(self):
        with redirect_stderr(io.StringIO()):
            found = corpus_scan.discover_local("hello", 24, include_sidechain=True)
        self.assertEqual(len(found), 3)


def _assistant_row(mid: str, input_tokens: int, output_tokens: int) -> str:
    return json.dumps({
        "type": "assistant",
        "uuid": f"u-{mid}",
        "timestamp": "2026-01-01T00:00:01.000Z",
        "message": {
            "id": mid,
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "content": [{"type": "text", "text": "ok"}],
        },
    })


class TestCorpusScanEvidenceBundle(_FakeHome):
    """A matched parent session carries its subagent files as evidence; the
    subagent file is never its own session row."""

    def test_audit_one_lists_parent_subagent_files(self):
        with redirect_stderr(io.StringIO()):
            entry = corpus_scan.audit_one("claude", self.normal, {})
        self.assertEqual(entry["subagents"], [self.subagent])
        self.assertEqual(entry["subagent_count"], 1)

    def test_audit_one_non_claude_has_empty_subagents(self):
        rollout = os.path.join(self.tmp.name, "rollout-1.jsonl")
        _write(rollout, ["{}"])
        with redirect_stderr(io.StringIO()):
            entry = corpus_scan.audit_one("codex", rollout, {})
        self.assertEqual(entry["subagents"], [])
        self.assertEqual(entry["subagent_count"], 0)

    def test_subagent_file_is_evidence_not_a_session(self):
        with redirect_stderr(io.StringIO()):
            found = corpus_scan.discover_local("hello", 24)
            entries = [corpus_scan.audit_one(k, p, {}) for k, p, _h in found]
        paths = [e["path"] for e in entries]
        self.assertEqual(paths, [self.normal])
        self.assertIn(self.subagent, entries[0]["subagents"])


class TestTopSessionsSubagentColumn(_FakeHome):
    def setUp(self):
        super().setUp()
        _write(self.normal, [_row("hello go ahead", sidechain=False), _assistant_row("p1", 7, 3)])
        _write(self.subagent, [_row("hello go ahead", sidechain=True), _assistant_row("s1", 60, 40)])
        _write(self.by_content, [_row("hello go ahead", sidechain=True)])

    def test_subagent_tokens_for_parent(self):
        self.assertEqual(top_sessions.subagent_tokens_for(self.normal), (100, 1))
        self.assertEqual(top_sessions.subagent_tokens_for(self.by_content), (0, 0))

    def test_ranking_adds_subagent_tokens_with_separate_column(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()), mock.patch.object(sys, "argv", ["top_sessions.py", "3"]):
            top_sessions.main()
        text = out.getvalue()
        rows = top_sessions.parse_top_block(text)
        self.assertEqual(rows, [(110, "claude", self.normal)])
        self.assertNotIn(self.subagent, text)
        self.assertIn("own=10", text)
        self.assertIn("subagents=100 (1 file(s))", text)


if __name__ == "__main__":
    unittest.main()
