"""Behaviour tests for the bounded CI-log capture and snippet helper.

Every case asserts the same safety invariant two ways: the artifact on disk
still hashes to the original bytes, and the serialized response never exceeds
the hard byte cap. A case that cannot prove both is a failing case.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
HELPER = REPO / "corpus" / "skills" / "principle-guard-the-context-window" / "scripts" / "ci_logs.py"
HARD_LIMIT = 16_384
MIN_LIMIT = 512

FAKE_GH = '''#!/usr/bin/env python3
"""Stand-in for the gh CLI so the fetch path is exercised without a network."""
import json
import os
import sys

with open(os.environ["FAKE_GH_CALLS"], "a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")

mode = os.environ.get("FAKE_GH_MODE", "ok")
endpoint = sys.argv[-1] if len(sys.argv) > 1 else ""

if endpoint.endswith("/logs"):
    if mode == "interrupted":
        with open(os.environ["FAKE_GH_LOG"], "rb") as source:
            sys.stdout.buffer.write(source.read(4096))
        sys.stdout.buffer.flush()
        sys.stderr.write("gh: connection reset by peer while streaming logs\\n")
        raise SystemExit(7)
    if mode == "fetch_error":
        sys.stderr.write("gh: HTTP 404 Not Found (log expired)\\n" * 600)
        raise SystemExit(1)
    with open(os.environ["FAKE_GH_LOG"], "rb") as source:
        sys.stdout.buffer.write(source.read())
    raise SystemExit(0)

if mode == "in_progress":
    print(json.dumps({"id": 41, "status": "in_progress", "conclusion": None}))
    raise SystemExit(0)
print(json.dumps({"id": 41, "status": "completed", "conclusion": "failure"}))
'''


def failing_log(blocks: int = 3, filler: int = 700) -> bytes:
    lines = ["##[group]Run the test suite"]
    for i in range(filler):
        lines.append(f"2026-09-22T00:00:{i % 60:02d}.0000000Z ordinary progress line {i} " + "x" * 110)
    for block in range(blocks):
        lines.append(f"the line just before failure {block}")
        lines.append(f"##[error]step {block} failed: expected 1, got 2")
        lines.append(f'  File "tests/test_thing.py", line {block + 10}, in test_thing')
        lines.append(f"the line just after failure {block}")
        for i in range(60):
            lines.append(f"filler between failure blocks {block} {i} " + "y" * 100)
    lines.append("##[endgroup]")
    lines.append("Process completed with exit code 1.")
    return ("\n".join(lines) + "\n").encode("utf-8")


def clean_log(filler: int = 700) -> bytes:
    lines = ["##[group]Run the test suite"]
    for i in range(filler):
        lines.append(f"2026-09-22T00:00:{i % 60:02d}.0000000Z ok step {i} finished " + "x" * 110)
    lines.append("UNIQUEMIDDLETOKEN-canary")
    for i in range(filler):
        lines.append(f"2026-09-22T00:01:{i % 60:02d}.0000000Z ok step {i} cleaned up " + "z" * 110)
    lines.append("##[endgroup]")
    lines.append("Process completed with exit code 0.")
    return ("\n".join(lines) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CiLogsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifacts = self.root / "artifacts"
        self.calls = self.root / "gh-calls.txt"
        self.gh = self.root / "fake-gh"
        self.gh.write_text(FAKE_GH, encoding="utf-8")
        self.gh.chmod(self.gh.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.tmp.cleanup()

    def run_helper(self, *args: str, expect: int | None = None, env: dict | None = None):
        merged = dict(os.environ)
        merged.update(env or {})
        proc = subprocess.run(
            [sys.executable, str(HELPER), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged,
            check=False,
        )
        raw = proc.stdout.rstrip(b"\n")
        self.assertTrue(raw, f"helper printed nothing; stderr={proc.stderr.decode('utf-8', 'replace')}")
        requested = int(args[args.index("--limit") + 1]) if "--limit" in args else HARD_LIMIT
        limit = max(MIN_LIMIT, min(HARD_LIMIT, requested))
        self.assertLessEqual(
            len(proc.stdout),
            limit + 1,
            f"response {len(proc.stdout)} bytes exceeds the {limit}-byte cap",
        )
        payload = json.loads(raw)
        if expect is not None:
            self.assertEqual(proc.returncode, expect, proc.stderr.decode("utf-8", "replace"))
        return payload, proc

    def import_log(self, data: bytes, name: str = "job.log"):
        source = self.root / name
        source.write_bytes(data)
        payload, _ = self.run_helper(
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--from-file",
            str(source),
            expect=0,
        )
        return payload, source

    def gh_env(self, log_bytes: bytes, mode: str = "ok"):
        log_path = self.root / "gh-source.log"
        log_path.write_bytes(log_bytes)
        return {
            "FAKE_GH_CALLS": str(self.calls),
            "FAKE_GH_LOG": str(log_path),
            "FAKE_GH_MODE": mode,
        }

    def call_log(self) -> list[str]:
        if not self.calls.exists():
            return []
        return [line for line in self.calls.read_text(encoding="utf-8").splitlines() if line]

    def block_text(self, payload: dict) -> str:
        return "\n".join(
            line["text"] for block in payload.get("blocks", []) for line in block["lines"]
        )


class TestCapture(CiLogsCase):
    def test_local_import_preserves_every_byte_and_hash(self):
        data = failing_log()
        payload, source = self.import_log(data)
        artifact = payload["artifact"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(artifact["completeness"], "complete")
        self.assertTrue(artifact["complete"])
        self.assertEqual(artifact["log_bytes"], len(data))
        self.assertEqual(artifact["log_sha256"], sha256(data))
        stored = Path(artifact["log_path"]).read_bytes()
        self.assertEqual(stored, data)
        self.assertEqual(stored, source.read_bytes())
        self.assertNotIn("##[error]", json.dumps(payload))

    def test_artifact_files_are_private_and_manifested(self):
        payload, _ = self.import_log(failing_log())
        artifact = payload["artifact"]
        log_path = Path(artifact["log_path"])
        self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)
        manifest = json.loads(Path(artifact["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["log"]["sha256"], artifact["log_sha256"])
        self.assertEqual(manifest["log"]["bytes"], artifact["log_bytes"])
        self.assertEqual(manifest["completeness"], "complete")
        self.assertIn("producer", manifest)
        self.assertIn("identity", manifest)

    def test_missing_source_file_is_an_explicit_error(self):
        payload, proc = self.run_helper(
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--from-file",
            str(self.root / "no-such.log"),
        )
        self.assertEqual(payload["status"], "error")
        self.assertTrue(payload["errors"])
        self.assertNotEqual(proc.returncode, 0)

    def test_github_fetch_records_identity_and_caches_on_repeat(self):
        data = failing_log()
        env = self.gh_env(data)
        args = (
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--attempt",
            "2",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
        )
        first, _ = self.run_helper(*args, expect=0, env=env)
        calls_after_first = self.call_log()
        second, _ = self.run_helper(*args, expect=0, env=env)
        calls_after_second = self.call_log()

        self.assertFalse(first["cached"])
        self.assertTrue(first["downloaded"])
        self.assertTrue(second["cached"])
        self.assertFalse(second["downloaded"])
        self.assertEqual(calls_after_first, calls_after_second)
        self.assertEqual(first["artifact"]["handle"], second["artifact"]["handle"])
        self.assertEqual(first["artifact"]["log_sha256"], sha256(data))
        self.assertEqual(second["artifact"]["log_sha256"], sha256(data))
        self.assertEqual(first["artifact"]["identity"]["run_id"], "12345")
        self.assertEqual(first["artifact"]["identity"]["attempt"], 2)
        self.assertEqual(first["artifact"]["job_conclusion"], "failure")

    def test_manifest_path_is_reported_from_disk_not_only_first_capture(self):
        data = failing_log()
        env = self.gh_env(data)
        args = (
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
        )
        first, _ = self.run_helper(*args, expect=0, env=env)
        second, _ = self.run_helper(*args, expect=0, env=env)
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            first["artifact"]["handle"],
            expect=0,
            env=env,
        )

        self.assertTrue(second["cached"])
        manifest_path = first["artifact"]["manifest_path"]
        self.assertTrue(manifest_path, "first capture reported no manifest_path")
        self.assertEqual(second["artifact"]["manifest_path"], manifest_path)
        self.assertEqual(snippet["artifact"]["manifest_path"], manifest_path)
        on_disk = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["manifest_path"], manifest_path)

    def test_snippet_after_capture_never_downloads_again(self):
        data = failing_log()
        env = self.gh_env(data)
        captured, _ = self.run_helper(
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
            expect=0,
            env=env,
        )
        before = self.call_log()
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            captured["artifact"]["handle"],
            expect=0,
            env=env,
        )
        self.assertEqual(self.call_log(), before)
        self.assertEqual(snippet["artifact"]["handle"], captured["artifact"]["handle"])
        self.assertEqual(snippet["artifact"]["log_sha256"], captured["artifact"]["log_sha256"])

    def test_nonzero_producer_is_incomplete_and_never_cached(self):
        env = self.gh_env(failing_log(), mode="fetch_error")
        args = (
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
        )
        first, proc = self.run_helper(*args, env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(first["artifact"]["completeness"], "incomplete")
        self.assertFalse(first["artifact"]["complete"])
        self.assertEqual(first["artifact"]["producer_exit_status"], 1)
        self.assertGreater(first["artifact"]["stderr_bytes"], HARD_LIMIT)
        stderr_stored = Path(first["artifact"]["stderr_path"]).read_bytes()
        self.assertEqual(len(stderr_stored), first["artifact"]["stderr_bytes"])
        self.assertEqual(sha256(stderr_stored), first["artifact"]["stderr_sha256"])

        calls_after_first = len(self.call_log())
        self.run_helper(*args, env=env)
        self.assertGreater(len(self.call_log()), calls_after_first)

    def test_interrupted_download_keeps_partial_bytes_but_stays_incomplete(self):
        data = failing_log()
        env = self.gh_env(data, mode="interrupted")
        args = (
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
        )
        payload, proc = self.run_helper(*args, env=env)
        artifact = payload["artifact"]
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(artifact["completeness"], "incomplete")
        self.assertEqual(artifact["producer_exit_status"], 7)
        self.assertEqual(artifact["log_bytes"], 4096)
        self.assertEqual(Path(artifact["log_path"]).read_bytes(), data[:4096])

        calls_after_first = len(self.call_log())
        self.run_helper(*args, env=env)
        self.assertGreater(len(self.call_log()), calls_after_first)

    def test_in_progress_job_is_never_marked_complete(self):
        env = self.gh_env(failing_log(), mode="in_progress")
        payload, _ = self.run_helper(
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
            env=env,
        )
        self.assertEqual(payload["artifact"]["job_status"], "in_progress")
        self.assertEqual(payload["artifact"]["completeness"], "incomplete")
        self.assertFalse(payload["artifact"]["complete"])


    def test_first_capture_lists_each_note_once(self):
        env = self.gh_env(failing_log(), mode="in_progress")
        payload, _ = self.run_helper(
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
            env=env,
        )
        notes = payload["notes"]
        self.assertTrue(notes, payload)
        self.assertEqual(len(notes), len(set(notes)), notes)

class TestSnippet(CiLogsCase):
    def test_structural_blocks_carry_the_failure_and_the_final_status(self):
        payload, _ = self.import_log(failing_log(blocks=1))
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            expect=0,
        )
        text = self.block_text(snippet)
        self.assertEqual(snippet["status"], "ok")
        self.assertFalse(snippet["no_match"])
        self.assertIn("##[error]step 0 failed: expected 1, got 2", text)
        self.assertIn("the line just before failure 0", text)
        self.assertIn('File "tests/test_thing.py", line 10, in test_thing', text)
        self.assertIn("Process completed with exit code 1.", text)
        kinds = {block["kind"] for block in snippet["blocks"]}
        self.assertIn("structural", kinds)
        self.assertIn("final_status", kinds)
        for block in snippet["blocks"]:
            self.assertEqual(block["start_line"], block["lines"][0]["n"])
            self.assertEqual(block["end_line"], block["lines"][-1]["n"])

    def test_literal_pattern_search_with_context(self):
        payload, _ = self.import_log(failing_log(blocks=1))
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--pattern",
            "ordinary progress line 42 ",
            "--context",
            "1",
            expect=0,
        )
        text = self.block_text(snippet)
        self.assertEqual(snippet["selection"]["mode"], "pattern")
        self.assertEqual(snippet["matches"]["pattern"], 1)
        self.assertIn("ordinary progress line 42 ", text)
        self.assertIn("ordinary progress line 41 ", text)
        self.assertNotIn("ordinary progress line 400 ", text)

    def test_pattern_with_no_hit_says_no_match_and_withholds_the_log(self):
        data = failing_log(blocks=1)
        payload, _ = self.import_log(data)
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--pattern",
            "this-literal-is-not-in-the-log",
        )
        self.assertEqual(snippet["status"], "no_match")
        self.assertTrue(snippet["no_match"])
        self.assertEqual(snippet["matches"]["pattern"], 0)
        self.assertNotEqual(proc.returncode, 0)
        self.assertLess(len(proc.stdout), len(data) // 4)
        self.assertTrue(snippet["warnings"])

    def test_clean_log_reports_no_match_without_claiming_success(self):
        data = clean_log()
        payload, _ = self.import_log(data)
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
        )
        serialized = json.dumps(snippet)
        self.assertEqual(snippet["status"], "no_match")
        self.assertEqual(snippet["matches"]["structural"], 0)
        self.assertNotIn("UNIQUEMIDDLETOKEN-canary", serialized)
        self.assertLess(len(proc.stdout), len(data) // 4)
        self.assertNotIn("success", serialized.lower())
        self.assertIn("Process completed with exit code 0.", self.block_text(snippet))

    def test_multi_failure_counts_every_block_and_reports_omissions(self):
        payload, _ = self.import_log(failing_log(blocks=5))
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--max-blocks",
            "2",
            expect=0,
        )
        structural = [b for b in snippet["blocks"] if b["kind"] == "structural"]
        self.assertEqual(snippet["matches"]["structural"], 5)
        self.assertEqual(snippet["matches"]["blocks_total"], 6)
        self.assertEqual(len(structural), 2)
        self.assertEqual(snippet["omitted"]["blocks"], 3)
        self.assertGreater(snippet["omitted"]["lines"], 0)

    def test_line_range_selection(self):
        payload, _ = self.import_log(failing_log(blocks=1))
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--lines",
            "2-5",
            expect=0,
        )
        block = next(b for b in snippet["blocks"] if b["kind"] == "range")
        self.assertEqual(snippet["selection"]["mode"], "range")
        self.assertEqual([line["n"] for line in block["lines"]], [2, 3, 4, 5])
        self.assertIn("ordinary progress line 0 ", block["lines"][0]["text"])

    def test_line_range_outside_the_log_is_no_match(self):
        payload, _ = self.import_log(failing_log(blocks=1))
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--lines",
            "900000-900010",
        )
        self.assertEqual(snippet["status"], "no_match")
        self.assertTrue(snippet["no_match"])

    def test_huge_single_line_is_clipped_and_reported(self):
        giant = "##[error]" + "A" * 300_000
        data = ("start\n" + giant + "\nProcess completed with exit code 1.\n").encode("utf-8")
        payload, _ = self.import_log(data)
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            expect=0,
        )
        line = next(
            entry
            for block in snippet["blocks"]
            for entry in block["lines"]
            if entry["text"].startswith("##[error]")
        )
        self.assertGreater(line["clipped_bytes"], 250_000)
        self.assertLess(len(line["text"].encode("utf-8")), 4096)
        self.assertGreater(snippet["omitted"]["clipped_bytes"], 0)
        self.assertLessEqual(len(proc.stdout), HARD_LIMIT + 1)
        self.assertEqual(Path(payload["artifact"]["log_path"]).read_bytes(), data)

    def test_multibyte_text_survives_and_clips_on_a_character_boundary(self):
        short = "##[error]测试失败 ✅ ünïcödé"
        giant = "##[error]" + "✅" * 100_000
        data = ("head\n" + short + "\n" + giant + "\ntail 完了\n").encode("utf-8")
        payload, _ = self.import_log(data)
        self.assertEqual(payload["artifact"]["log_sha256"], sha256(data))
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            expect=0,
        )
        texts = [entry["text"] for block in snippet["blocks"] for entry in block["lines"]]
        self.assertIn(short, texts)
        clipped = next(t for t in texts if t.startswith("##[error]✅"))
        self.assertNotIn("�", clipped)
        clipped.encode("utf-8").decode("utf-8")
        self.assertLessEqual(len(proc.stdout), HARD_LIMIT + 1)

    def test_unknown_handle_is_an_explicit_error(self):
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            "local-deadbeefdeadbeefdeadbeefdeadbeef",
        )
        self.assertEqual(snippet["status"], "error")
        self.assertTrue(snippet["errors"])
        self.assertNotEqual(proc.returncode, 0)

    def test_unreadable_artifact_is_an_error_not_a_clean_result(self):
        payload, _ = self.import_log(failing_log(blocks=1))
        Path(payload["artifact"]["log_path"]).unlink()
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
        )
        self.assertEqual(snippet["status"], "error")
        self.assertFalse(snippet.get("blocks"))
        self.assertTrue(snippet["errors"])
        self.assertNotEqual(proc.returncode, 0)

    def test_snippet_of_an_incomplete_artifact_says_incomplete(self):
        env = self.gh_env(failing_log(blocks=1), mode="interrupted")
        captured, _ = self.run_helper(
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--repo",
            "owner/name",
            "--run",
            "12345",
            "--job",
            "41",
            "--gh-path",
            str(self.gh),
            env=env,
        )
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            captured["artifact"]["handle"],
        )
        self.assertEqual(snippet["status"], "incomplete")
        self.assertEqual(snippet["artifact"]["completeness"], "incomplete")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(snippet["warnings"])

    def test_caller_may_lower_the_limit_but_not_raise_it(self):
        payload, _ = self.import_log(failing_log(blocks=5))
        lowered, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--limit",
            "2048",
            expect=0,
        )
        self.assertLessEqual(len(proc.stdout), 2049)
        self.assertEqual(lowered["limit"], 2048)

        raised, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--limit",
            "999999",
            expect=0,
        )
        self.assertEqual(raised["limit"], HARD_LIMIT)
        self.assertTrue(raised["limit_clamped"])
        self.assertLessEqual(len(proc.stdout), HARD_LIMIT + 1)


    def test_budget_below_the_floor_fails_loudly_and_keeps_the_failure_signal(self):
        payload, _ = self.import_log(failing_log(blocks=1))
        snippet, proc = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--limit",
            "10",
        )
        self.assertEqual(snippet["status"], "error")
        self.assertEqual(snippet["blocks"], [])
        self.assertEqual(snippet["artifact"]["completeness"], "complete")
        self.assertEqual(snippet["artifact"]["log_sha256"], payload["artifact"]["log_sha256"])
        self.assertTrue(snippet["response_truncated"])
        self.assertEqual(proc.returncode, 2)


class TestOutputBudgetRegression(CiLogsCase):
    def test_full_log_never_enters_the_response(self):
        data = failing_log(blocks=5)
        raw_bytes = len(data)
        self.assertGreater(raw_bytes, HARD_LIMIT)

        source = self.root / "budget.log"
        source.write_bytes(data)
        captured, proc_capture = self.run_helper(
            "capture",
            "--artifact-root",
            str(self.artifacts),
            "--from-file",
            str(source),
            expect=0,
        )
        self.assertEqual(captured["artifact"]["log_sha256"], sha256(data))
        self.assertEqual(captured["artifact"]["log_bytes"], raw_bytes)
        self.assertLessEqual(len(proc_capture.stdout), HARD_LIMIT + 1)

        snippet, proc_snippet = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            captured["artifact"]["handle"],
            expect=0,
        )
        self.assertLessEqual(len(proc_snippet.stdout), HARD_LIMIT + 1)
        self.assertGreater(raw_bytes, len(proc_snippet.stdout) * 4)

        total = len(proc_capture.stdout) + len(proc_snippet.stdout)
        self.assertLess(total, raw_bytes)
        self.assertEqual(Path(captured["artifact"]["log_path"]).read_bytes(), data)
        self.assertEqual(snippet["artifact"]["log_sha256"], sha256(data))


if __name__ == "__main__":
    unittest.main()
