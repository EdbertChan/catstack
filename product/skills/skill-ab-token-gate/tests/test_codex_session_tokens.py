from __future__ import annotations

import tempfile
import unittest

import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from codex_session_tokens import (  # noqa: E402
    discover_child_paths,
    last_total_usage,
    score_parent,
    uncached_plus_output,
)


def _write_rollout(path: Path, total: int, agent_thread_id: str | None = None) -> None:
    events = []
    if agent_thread_id:
        events.append(
            {
                "type": "response_item",
                "payload": {"agent_thread_id": agent_thread_id, "type": "message"},
            }
        )
    events.append(
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total,
                        "cached_input_tokens": 0,
                        "output_tokens": 10,
                        "total_tokens": total + 10,
                    }
                },
            },
        }
    )
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def test_last_total_usage_reads_final_event(tmp_path: Path) -> None:
    path = tmp_path / "rollout-parent.jsonl"
    _write_rollout(path, 100)
    usage = last_total_usage(path)
    assert usage is not None
    assert usage["total_tokens"] == 110


def test_score_parent_includes_child_tokens(tmp_path: Path) -> None:
    child_id = "01a0a803-ad21-72e3-b09d-76ad86cb6ffc"
    parent = tmp_path / "rollout-2026-01-01T00-00-00-01a0a802-parent.jsonl"
    child = tmp_path / f"rollout-2026-01-01T00-00-01-{child_id}.jsonl"
    _write_rollout(parent, 1000, agent_thread_id=child_id)
    _write_rollout(child, 200)
    scored = score_parent(parent, tmp_path)
    assert scored["child_total_tokens"] == 210
    assert scored["inclusive_total_tokens"] == 1000 + 10 + 210
    assert uncached_plus_output(scored["parent_usage"]) == 1010
    kids = discover_child_paths(parent, tmp_path)
    assert kids == [child]


class TestCodexSessionTokens(unittest.TestCase):
    def test_last_total_usage_reads_final_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_last_total_usage_reads_final_event(Path(tmp))

    def test_score_parent_includes_child_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_score_parent_includes_child_tokens(Path(tmp))


if __name__ == "__main__":
    unittest.main()
