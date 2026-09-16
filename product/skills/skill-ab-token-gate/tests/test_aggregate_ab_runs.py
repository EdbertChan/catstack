from __future__ import annotations

import tempfile
import unittest

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aggregate_ab_runs import build_aggregate, write_report  # noqa: E402


def _rollout(path: Path, total: int) -> None:
    ev = {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": total,
                }
            },
        },
    }
    # embed workflow markers for discovery
    marker = {"type": "custom", "payload": {"text": path.stem}}
    path.write_text(json.dumps(marker) + "\n" + json.dumps(ev) + "\n")


def test_pass_gate_when_b_median_lower(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for i, total in enumerate([300, 310, 290], start=1):
        p = sessions / f"rollout-A-r{i}-wfA{i}.jsonl"
        _rollout(p, total)
        p.write_text(p.read_text().replace(p.stem, f"wf-A-{i} " + p.stem))
    for i, total in enumerate([100, 110, 90], start=1):
        p = sessions / f"rollout-B-r{i}-wfB{i}.jsonl"
        body = json.dumps({"type": "custom", "payload": {"text": f"wf-B-{i}"}}) + "\n"
        body += json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": total,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": total,
                        }
                    },
                },
            }
        )
        p.write_text(body + "\n")

    registry = {
        "submissions": [
            {"arm": "A", "rep": "r1", "workflow_id": "wf-A-1"},
            {"arm": "A", "rep": "r2", "workflow_id": "wf-A-2"},
            {"arm": "A", "rep": "r3", "workflow_id": "wf-A-3"},
            {"arm": "B", "rep": "r1", "workflow_id": "wf-B-1"},
            {"arm": "B", "rep": "r2", "workflow_id": "wf-B-2"},
            {"arm": "B", "rep": "r3", "workflow_id": "wf-B-3"},
        ]
    }
    # rewrite A files with correct markers
    for i, total in enumerate([300, 310, 290], start=1):
        p = sessions / f"rollout-A-r{i}-wfA{i}.jsonl"
        body = json.dumps({"type": "custom", "payload": {"text": f"wf-A-{i}"}}) + "\n"
        body += json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": total,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": total,
                        }
                    },
                },
            }
        )
        p.write_text(body + "\n")

    agg = build_aggregate(registry, sessions)
    assert agg["pass_gate"] is True
    assert agg["by_arm"]["A"]["inclusive_total_tokens"]["median"] == 300
    assert agg["by_arm"]["B"]["inclusive_total_tokens"]["median"] == 100
    out = tmp_path / "out"
    out.mkdir()
    write_report(agg, out)
    assert "Pass gate" in (out / "REPORT.md").read_text()


def test_fail_gate_when_b_not_cheaper(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    registry = {"submissions": []}
    for arm, totals in [("A", [100, 110]), ("B", [200, 210])]:
        for i, total in enumerate(totals, start=1):
            wf = f"wf-{arm}-{i}"
            registry["submissions"].append({"arm": arm, "rep": f"r{i}", "workflow_id": wf})
            p = sessions / f"rollout-{arm}-{i}.jsonl"
            body = json.dumps({"type": "custom", "payload": {"text": wf}}) + "\n"
            body += json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": total,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": total,
                            }
                        },
                    },
                }
            )
            p.write_text(body + "\n")
    agg = build_aggregate(registry, sessions)
    assert agg["pass_gate"] is False


class TestAggregateAbRuns(unittest.TestCase):
    def test_pass_gate_when_b_median_lower(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_pass_gate_when_b_median_lower(Path(tmp))

    def test_fail_gate_when_b_not_cheaper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_fail_gate_when_b_not_cheaper(Path(tmp))


if __name__ == "__main__":
    unittest.main()
