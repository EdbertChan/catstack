from __future__ import annotations

import tempfile
import unittest

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import publish_ab_gist as pub  # noqa: E402


def test_collect_files_prefers_report_and_sessions(tmp_path: Path) -> None:
    (tmp_path / "REPORT.md").write_text("# hi\n")
    (tmp_path / "aggregate.json").write_text("{}\n")
    (tmp_path / "registry.json").write_text("{}\n")
    (tmp_path / "session-A-r1-parent.jsonl").write_text("{}\n")
    (tmp_path / "noise.txt").write_text("x\n")
    names = [p.name for p in pub.collect_files(tmp_path)]
    assert names == [
        "REPORT.md",
        "aggregate.json",
        "registry.json",
        "session-A-r1-parent.jsonl",
    ]


def test_main_writes_gist_meta(tmp_path: Path, monkeypatch=None) -> None:
    (tmp_path / "REPORT.md").write_text("# hi\n")
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if cmd[:3] == ["gh", "gist", "create"]:
            return "https://gist.github.com/deadbeef"
        raise AssertionError(cmd)

    pub.run = fake_run  # type: ignore
    old = sys.argv
    try:
        sys.argv = ["publish_ab_gist.py", "--out", str(tmp_path), "--desc", "t"]
        assert pub.main() == 0
    finally:
        sys.argv = old
    meta = json.loads((tmp_path / "gist-meta.json").read_text())
    assert meta["gist_id"] == "deadbeef"
    assert "html_url" in meta
    assert any(c[:3] == ["gh", "gist", "create"] for c in calls)


class TestPublishAbGist(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(setattr, pub, "run", pub.run)

    def test_collect_files_prefers_report_and_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_collect_files_prefers_report_and_sessions(Path(tmp))

    def test_main_writes_gist_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_main_writes_gist_meta(Path(tmp))


if __name__ == "__main__":
    unittest.main()
