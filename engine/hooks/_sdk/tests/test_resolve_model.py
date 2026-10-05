from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

from transcripts import cursor_peer_model, named_model, resolve_model


class ResolveModelHarnessMatrixTest(unittest.TestCase):
    def test_named_model_skips_blank_and_synthetic(self) -> None:
        self.assertEqual("", named_model({"model": ""}))
        self.assertEqual("", named_model({"model": "  "}))
        self.assertEqual("", named_model({"model": "<synthetic>"}))
        self.assertEqual("claude-sonnet-5", named_model({"model": "claude-sonnet-5"}))
        self.assertEqual(
            "composer-2",
            named_model({"metadata": {"modelId": "composer-2"}}),
        )

    def test_claude_transcript_resolves_when_envelope_omits_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-10-03T00:00:01.000Z",
                        "message": {"model": "<synthetic>"},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-10-03T00:00:02.000Z",
                        "message": {"model": "claude-opus-5"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            model = resolve_model(
                {"session_id": "s-claude", "transcript_path": str(transcript)},
                "claude",
            )
        self.assertEqual("claude-opus-5", model)

    def test_codex_rollout_resolves_when_envelope_omits_model(self) -> None:
        thread = "01a10028-ca44-7912-a665-696a93f26e16"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_CODEX_SESSIONS_DIR": tmp}, clear=False
        ):
            rollout = Path(tmp) / "2026" / "10" / "03" / f"rollout-2026-10-03T00-00-00-{thread}.jsonl"
            rollout.parent.mkdir(parents=True)
            rollout.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-10-03T00:00:00.000Z",
                                "type": "session_meta",
                                "payload": {"session_id": thread},
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-10-03T00:00:01.000Z",
                                "type": "turn_context",
                                "payload": {"model": "gpt-5.6-sol"},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            model = resolve_model({"thread-id": thread}, "codex")
        self.assertEqual("gpt-5.6-sol", model)

    def test_cursor_named_and_peer_resolution(self) -> None:
        self.assertEqual(
            "composer-2",
            resolve_model({"session_id": "cursor-sess", "model": "composer-2"}, "cursor"),
        )
        peers = {
            "cursor-sess": [
                ("2026-10-03T00:00:01.000Z", "composer-1"),
                ("2026-10-03T00:00:03.000Z", "composer-2"),
            ]
        }
        self.assertEqual(
            "composer-1",
            resolve_model(
                {"session_id": "cursor-sess", "ts": "2026-10-03T00:00:02.000Z"},
                "cursor",
                peer_models=peers,
            ),
        )
        self.assertEqual(
            "composer-2",
            cursor_peer_model("cursor-sess", "2026-10-03T00:00:04.000Z", peers),
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            self.assertEqual(
                "",
                resolve_model({"session_id": "cursor-sess"}, "cursor"),
            )

    def test_cursor_local_metrics_peer_resolution(self) -> None:
        from datetime import date

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            path = Path(tmp) / f"events-{date.today().isoformat()}.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "session_id": "cursor-local",
                                "harness": "cursor",
                                "ts": "2026-10-05T12:00:00.000Z",
                                "model": "grok-4.7",
                                "event": "invoked",
                            }
                        ),
                        json.dumps(
                            {
                                "session_id": "cursor-local",
                                "harness": "cursor",
                                "ts": "2026-10-05T12:00:05.000Z",
                                "model": "",
                                "event": "skill_used",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            model = resolve_model(
                {
                    "session_id": "cursor-local",
                    "ts": "2026-10-05T12:00:05.000Z",
                },
                "cursor",
            )
        self.assertEqual("grok-4.7", model)


if __name__ == "__main__":
    unittest.main()
