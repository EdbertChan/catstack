from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import backfill_models


class BackfillModelsTest(unittest.TestCase):
    def test_model_as_of_uses_the_latest_model_at_or_before_the_event(self) -> None:
        points = [
            ("2026-10-03T00:00:01.000Z", "gpt-5.6-sol"),
            ("2026-10-03T00:02:00.000Z", "gpt-5.6-terra"),
        ]
        self.assertEqual("gpt-5.6-sol", backfill_models.model_as_of(points, "2026-10-03T00:01:00.000000Z"))
        self.assertEqual("gpt-5.6-terra", backfill_models.model_as_of(points, "2026-10-03T00:03:00.000000Z"))

    def test_blank_event_borrows_the_only_nearby_session(self) -> None:
        peers = {
            ("host", "diu-stop"): [("2026-10-03T00:00:01.000000Z", "01a10028-ca44-7912-a665-696a93f26e16")],
        }
        session = backfill_models.recover_session(
            "host",
            "diu-stop",
            "2026-10-03T00:00:02.000000Z",
            peers,
        )
        self.assertEqual("01a10028-ca44-7912-a665-696a93f26e16", session)

    def test_two_nearby_sessions_stay_unmatched(self) -> None:
        peers = {
            ("host", "diu-stop"): [
                ("2026-10-03T00:00:01.000000Z", "01a10028-ca44-7912-a665-696a93f26e16"),
                ("2026-10-03T00:00:01.500000Z", "01a10029-ca44-7912-a665-696a93f26e16"),
            ],
        }
        self.assertEqual("", backfill_models.recover_session("host", "diu-stop", "2026-10-03T00:00:02.000000Z", peers))

    def test_plan_copies_fills_from_a_same_session_peer_timeline(self) -> None:
        session = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        events = [
            {
                "uuid": "blank-row",
                "timestamp": "2026-10-03T00:00:05.000000Z",
                "hook": "repeat-error-stop",
                "harness": "claude",
                "session_id": session,
                "machine": "host",
                "action": "invoked",
            }
        ]
        copies, unmatched = backfill_models.plan_copies(
            events,
            {session: [("2026-10-03T00:00:01.000Z", "claude-opus-5")]},
            backfill_models.peer_index(events),
            set(),
        )
        self.assertEqual(0, unmatched)
        self.assertEqual(1, len(copies))
        self.assertEqual("claude-opus-5", copies[0]["model"])
        self.assertEqual("session-model", copies[0]["model_source"])
        self.assertEqual("blank-row", copies[0]["source_uuid"])

    def test_plan_copies_names_the_model_and_skips_rows_already_copied(self) -> None:
        thread = "01a10028-ca44-7912-a665-696a93f26e16"
        events = [
            {
                "uuid": "already",
                "timestamp": "2026-10-03T00:00:02.000000Z",
                "hook": "diu-stop",
                "harness": "codex",
                "session_id": thread,
                "machine": "host",
                "action": "silent",
            },
            {
                "uuid": "new-one",
                "timestamp": "2026-10-03T00:00:02.000000Z",
                "hook": "diu-stop",
                "harness": "codex",
                "session_id": "",
                "machine": "host",
                "action": "silent",
            },
            {
                "uuid": "no-log",
                "timestamp": "2026-10-03T00:00:02.000000Z",
                "hook": "diu-stop",
                "harness": "codex",
                "session_id": "missing-session",
                "machine": "host",
                "action": "silent",
            },
        ]
        peers = backfill_models.peer_index(
            [
                {
                    "session_id": thread,
                    "machine": "host",
                    "hook": "diu-stop",
                    "timestamp": "2026-10-03T00:00:02.000000Z",
                }
            ]
        )
        copies, unmatched = backfill_models.plan_copies(
            events,
            {thread: [("2026-10-03T00:00:01.000Z", "gpt-5.6-luna")]},
            peers,
            {"already"},
        )
        self.assertEqual(1, unmatched)
        self.assertEqual(["new-one"], [row["source_uuid"] for row in copies])
        self.assertEqual("gpt-5.6-luna", copies[0]["model"])
        self.assertEqual(thread, copies[0]["session_id"])

    def test_index_codex_rollouts_reads_the_model_from_the_session_file(self) -> None:
        thread = "01a10028-ca44-7912-a665-696a93f26e16"
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "2026" / "10" / "03" / f"rollout-2026-10-03T00-00-00-{thread}.jsonl"
            rollout.parent.mkdir(parents=True)
            rollout.write_text(
                '{"timestamp":"2026-10-03T00:00:00.000Z","type":"session_meta","payload":{"session_id":"%s"}}\n'
                '{"timestamp":"2026-10-03T00:00:01.000Z","type":"turn_context","payload":{"model":"gpt-5.6-sol"}}\n'
                % thread,
                encoding="utf-8",
            )
            index = backfill_models.index_codex_rollouts(Path(tmp))
        self.assertEqual([("2026-10-03T00:00:01.000Z", "gpt-5.6-sol")], index[thread])

    def test_index_claude_transcripts_skips_synthetic(self) -> None:
        session = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            project.mkdir()
            path = project / f"{session}.jsonl"
            path.write_text(
                '{"type":"assistant","timestamp":"2026-10-03T00:00:01.000Z","message":{"model":"<synthetic>"}}\n'
                '{"type":"assistant","timestamp":"2026-10-03T00:00:02.000Z","message":{"model":"claude-sonnet-5"}}\n',
                encoding="utf-8",
            )
            index = backfill_models.index_claude_transcripts(Path(tmp))
        self.assertEqual([("2026-10-03T00:00:02.000Z", "claude-sonnet-5")], index[session])

    def test_queries_page_by_timestamp_instead_of_offset(self) -> None:
        first = backfill_models.blank_query("claude", ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"], None)
        self.assertNotIn("OFFSET", first)
        nxt = backfill_models.blank_query(
            "claude",
            ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
            ("2026-09-15 21:25:58.413000", "239368ae-17bf-8a68-0747-55a68696ed1e"),
        )
        self.assertIn("toString(timestamp)", nxt)
        self.assertNotIn("OFFSET", nxt)
        with self.assertRaises(ValueError):
            backfill_models.blank_query(
                "claude",
                ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
                ("not-a-time", "239368ae-17bf-8a68-0747-55a68696ed1e"),
            )


if __name__ == "__main__":
    unittest.main()
