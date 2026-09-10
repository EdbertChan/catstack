#!/usr/bin/env python3
"""Tests for session_mine.py — no real home-directory transcript scans."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import session_mine  # noqa: E402


def _claude_jsonl(path: str, texts: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for text in texts:
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": text},
                    }
                )
                + "\n"
            )


class TestRunMine(unittest.TestCase):
    def test_writes_queue_with_ready_when_yes_and_no_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.jsonl")
            b = os.path.join(tmp, "b.jsonl")
            c = os.path.join(tmp, "c.jsonl")
            _claude_jsonl(a, ["make a PR"])
            _claude_jsonl(b, ["make a PR"])
            _claude_jsonl(c, ["don't make a PR yet", "make a PR"])
            state = os.path.join(tmp, "state")
            with patch.object(
                session_mine, "discover_intervention_paths", return_value=[a, b, c]
            ):
                with patch.object(session_mine, "open_pr_hashes_for_cluster", return_value=[]):
                    queue = session_mine.run_mine(
                        hours=24,
                        state_dir=state,
                        min_sessions=3,
                        min_utterances=5,
                        events_path=None,
                    )
            self.assertTrue(os.path.isfile(os.path.join(state, "queue.json")))
            ready = queue.get("pending_headless") or []
            self.assertEqual(len(ready), 1)
            self.assertEqual(ready[0]["cluster_key"], "make_pr")
            self.assertTrue(ready[0].get("ready_for_headless"))

    def test_cooldown_blocks_redispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.jsonl")
            b = os.path.join(tmp, "b.jsonl")
            c = os.path.join(tmp, "c.jsonl")
            _claude_jsonl(a, ["make a PR"])
            _claude_jsonl(b, ["make a PR"])
            _claude_jsonl(c, ["don't open a PR", "make a PR"])
            state = os.path.join(tmp, "state")
            with patch.object(
                session_mine, "discover_intervention_paths", return_value=[a, b, c]
            ):
                with patch.object(session_mine, "open_pr_hashes_for_cluster", return_value=[]):
                    q1 = session_mine.run_mine(
                        hours=24,
                        state_dir=state,
                        min_sessions=3,
                        min_utterances=3,
                        events_path=None,
                    )
                    h = q1["pending_headless"][0]["hash"]
                    session_mine.mark_headless_dispatched(state, h)
                    q2 = session_mine.run_mine(
                        hours=24,
                        state_dir=state,
                        min_sessions=3,
                        min_utterances=3,
                        events_path=None,
                    )
            self.assertEqual(q2.get("pending_headless"), [])
            blocked = [b for b in q2.get("blocked") or [] if b.get("blocked_reason") == "cooldown"]
            self.assertTrue(blocked)


NOW = 1_900_000_000.0

PARTIAL_UPDATE = (
    "sqlite3 invoker.db \"update tasks set pool_id='local-worktree', execution_agent='claude' "
    "where status in ('pending','queued')\""
)


def _human(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _agent(text: str, mid: str) -> dict:
    return {"type": "assistant", "message": {
        "id": mid, "usage": {"input_tokens": 10, "output_tokens": 5},
        "content": [{"type": "text", "text": text}],
    }}


def _bash(command: str, mid: str) -> dict:
    return {"type": "assistant", "message": {
        "id": mid, "usage": {"input_tokens": 7, "output_tokens": 3},
        "content": [{"type": "tool_use", "id": mid, "name": "Bash", "input": {"command": command}}],
    }}


FRUSTRATED = [
    _agent("I changed the endpoint shape.", "m1"),
    _human("I already told you not to change the response shape of the users endpoint."),
    _agent("Changed it again for consistency.", "m2"),
    _human("I told you the API contract must stay backward compatible."),
]
CLEAN = [
    _human("please add a unit test for the parser"),
    _agent("Added the test and it passes.", "m1"),
    _human("thanks, looks good"),
]
NARROWED = [
    _human("can you make all tasks use claude and local executor"),
    _bash(PARTIAL_UPDATE, "m1"),
    _human("ok"),
]


def _write_session(home: str, name: str, rows: list[dict], mtime: float) -> str:
    project = os.path.join(home, ".claude", "projects", "-proj")
    os.makedirs(project, exist_ok=True)
    path = os.path.join(project, f"{name}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    os.utime(path, (mtime, mtime))
    return path


class RecordingFiler:
    def __init__(self, fail: bool = False):
        self.plans: list[dict] = []
        self.fail = fail

    def __call__(self, plan: dict) -> str:
        if self.fail:
            raise RuntimeError("owner unreachable")
        self.plans.append(plan)
        return f"wf-{len(self.plans)}"


def _trend(state: str) -> list[dict]:
    with open(os.path.join(state, session_mine.TREND_FILE), encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


class TestAuditWorker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")
        self.state = os.path.join(self._tmp.name, "state")

    def tearDown(self):
        self._tmp.cleanup()

    def audit(self, filer, now=NOW, **kwargs):
        return session_mine.run_audit(
            state_dir=self.state, filer=filer, repo_url="https://example.invalid/repo.git",
            home=self.home, now=now, **kwargs,
        )

    def test_frustrated_session_fires_trend_row_and_filing_with_turn_pairs(self):
        _write_session(self.home, "sess-frustrated", FRUSTRATED, NOW - 60)
        filer = RecordingFiler()
        summary = self.audit(filer)
        rows = _trend(self.state)
        self.assertEqual(list(rows[0].keys()), list(session_mine.TREND_COLUMNS))
        self.assertEqual(rows[0]["session_id"], "sess-frustrated")
        self.assertEqual(rows[0]["intervention_must_automate"], "yes")
        self.assertEqual(rows[0]["intervention_count"], "2")
        self.assertEqual(rows[0]["tokens"], "30")
        self.assertEqual(summary["filing"], {"filed": 1})
        prompt = filer.plans[0]["tasks"][0]["prompt"]
        self.assertIn("sess-frustrated", prompt)
        self.assertIn("intervention-must-automate: yes (count=2)", prompt)
        self.assertIn("agent: 'I changed the endpoint shape.'", prompt)
        self.assertIn("user: 'I already told you not to change", prompt)
        self.assertEqual(filer.plans[0]["mergeMode"], "external_review")

    def test_narrowed_scope_fires_filing_with_the_narrowing_predicate(self):
        _write_session(self.home, "sess-narrowed", NARROWED, NOW - 60)
        filer = RecordingFiler()
        self.audit(filer)
        row = _trend(self.state)[0]
        self.assertEqual(row["narrowed"], "1")
        self.assertEqual(row["intervention_must_automate"], "no")
        prompt = filer.plans[0]["tasks"][0]["prompt"]
        self.assertIn("[narrowed] line 0", prompt)
        self.assertIn("status in", prompt)

    def test_clean_session_writes_a_row_and_never_files(self):
        _write_session(self.home, "sess-clean", CLEAN, NOW - 60)
        filer = RecordingFiler()
        summary = self.audit(filer)
        row = _trend(self.state)[0]
        self.assertEqual((row["intervention_must_automate"], row["narrowed"]), ("no", "0"))
        self.assertEqual(filer.plans, [])
        self.assertEqual(summary["filing"], {})

    def test_session_over_size_cap_is_unchecked_not_clean(self):
        _write_session(self.home, "sess-big", FRUSTRATED, NOW - 60)
        filer = RecordingFiler()
        summary = self.audit(filer, max_file_bytes=10)
        row = _trend(self.state)[0]
        self.assertEqual(row["intervention_must_automate"], session_mine.UNCHECKED)
        self.assertEqual(row["narrowed"], session_mine.UNCHECKED)
        self.assertEqual(summary["unchecked"], 1)
        self.assertEqual(filer.plans, [])

    def test_only_sessions_modified_since_last_run_are_audited_and_compared(self):
        _write_session(self.home, "sess-a", CLEAN, NOW - 60)
        first = self.audit(RecordingFiler())
        self.assertEqual(first["vs_previous_run"], {})
        _write_session(self.home, "sess-b", FRUSTRATED, NOW + 60)
        second = self.audit(RecordingFiler(), now=NOW + 120)
        self.assertEqual([r["session_id"] for r in _trend(self.state)], ["sess-a", "sess-b"])
        self.assertEqual(second["sessions"], 1)
        self.assertEqual(second["vs_previous_run"]["intervention_yes"], 1)

    def test_already_filed_session_does_not_refile_until_counts_increase(self):
        path = _write_session(self.home, "sess-x", FRUSTRATED, NOW - 60)
        filer = RecordingFiler()
        self.audit(filer)
        os.utime(path, (NOW + 60, NOW + 60))
        repeat = self.audit(filer, now=NOW + 120)
        self.assertEqual(repeat["filing"], {"already-filed": 1})
        self.assertEqual(len(filer.plans), 1)
        worse = FRUSTRATED + [_agent("Reverted nothing.", "m3"), _human("I told you three times now.")]
        _write_session(self.home, "sess-x", worse, NOW + 180)
        capped = self.audit(filer, now=NOW + 240)
        self.assertEqual(capped["filing"], {"session-rate-cap": 1})
        self.assertEqual(capped["rising"], [{"session": "claude:sess-x", "intervention_count": 1, "narrowed": 0}])
        _write_session(self.home, "sess-x", worse, NOW + session_mine.FILING_WINDOW_SECONDS + 300)
        refiled = self.audit(filer, now=NOW + session_mine.FILING_WINDOW_SECONDS + 360)
        self.assertEqual(refiled["filing"], {"filed": 1})
        self.assertIn("intervention-must-automate: yes (count=3)", filer.plans[1]["tasks"][0]["prompt"])

    def test_window_rate_cap_blocks_a_flood_of_filings(self):
        for n in range(session_mine.MAX_FILINGS_PER_WINDOW + 2):
            _write_session(self.home, f"sess-{n}", FRUSTRATED, NOW - 60)
        filer = RecordingFiler()
        summary = self.audit(filer)
        self.assertEqual(len(filer.plans), session_mine.MAX_FILINGS_PER_WINDOW)
        self.assertEqual(summary["filing"], {"filed": session_mine.MAX_FILINGS_PER_WINDOW, "window-rate-cap": 2})

    def test_failed_filing_is_not_marked_filed_and_retries(self):
        path = _write_session(self.home, "sess-retry", FRUSTRATED, NOW - 60)
        first = self.audit(RecordingFiler(fail=True))
        self.assertEqual(first["filing"], {"filing-failed": 1})
        os.utime(path, (NOW + 60, NOW + 60))
        filer = RecordingFiler()
        second = self.audit(filer, now=NOW + 120)
        self.assertEqual(second["filing"], {"filed": 1})

    def test_concurrent_audit_skips_instead_of_double_filing(self):
        _write_session(self.home, "sess-lock", FRUSTRATED, NOW - 60)
        os.makedirs(self.state)
        with session_mine._audit_lock(self.state) as held:
            self.assertTrue(held)
            self.assertIsNone(self.audit(RecordingFiler()))


class TestTurnPairSelection(unittest.TestCase):
    def test_narrowed_pairs_are_never_crowded_out_by_interventions(self):
        pairs = [{"kind": "intervention:told-you", "line": n} for n in range(20)]
        pairs += [{"kind": "narrowed", "line": 100}, {"kind": "narrowed", "line": 200}]
        chosen = session_mine.select_turn_pairs(pairs)
        self.assertEqual(len(chosen), session_mine.MAX_TURN_PAIRS)
        self.assertEqual([p["line"] for p in chosen if p["kind"] == "narrowed"], [100, 200])
        self.assertEqual([p["line"] for p in chosen], sorted(p["line"] for p in chosen))


class TestRegisterWorker(unittest.TestCase):
    def test_register_adds_the_kind_once_and_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = os.path.join(tmp, "config.json")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump({"autoFixRetries": 3, "externalWorkers": [{"kind": "other", "launch": {"executable": "x"}}]}, handle)
            os.chmod(config, 0o600)
            first = session_mine.register_worker(config, python="/usr/bin/python3", script="/repo/session_mine.py", interval=3600)
            second = session_mine.register_worker(config, python="/usr/bin/python3", script="/repo/session_mine.py", interval=3600)
            with open(config, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertTrue(first.startswith("registered"))
            self.assertEqual(second, "unchanged")
            self.assertEqual(saved["autoFixRetries"], 3)
            self.assertEqual([w["kind"] for w in saved["externalWorkers"]], ["other", session_mine.WORKER_KIND])
            self.assertEqual(saved["externalWorkers"][1]["launch"]["args"], ["/repo/session_mine.py", "worker", "--interval", "3600"])
            self.assertEqual(os.stat(config).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
