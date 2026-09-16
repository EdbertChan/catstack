from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
HELPER = REPO / "corpus" / "skills" / "principle-guard-the-context-window" / "scripts" / "ci_logs.py"


class CountingLogHandler(http.server.BaseHTTPRequestHandler):
    body = b""
    mode = "ok"
    hits = 0

    def do_GET(self):  # noqa: N802
        type(self).hits += 1
        if type(self).mode == "partial":
            self.send_response(200)
            self.send_header("Content-Length", str(len(type(self).body) + 100))
            self.end_headers()
            self.wfile.write(type(self).body[: max(1, len(type(self).body) // 2)])
            self.wfile.flush()
            self.connection.close()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, format, *args):  # noqa: A002
        return


class TestCiLogs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifacts = self.root / "artifacts"

    def tearDown(self):
        self.tmp.cleanup()

    def run_helper(self, *args: str, expect: int | None = 0) -> tuple[dict, bytes]:
        proc = subprocess.run(
            [sys.executable, str(HELPER), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if expect is not None:
            self.assertEqual(proc.returncode, expect, proc.stderr.decode("utf-8", "replace"))
        self.assertLessEqual(len(proc.stdout.rstrip(b"\n")), self.limit_from(args))
        return json.loads(proc.stdout), proc.stdout.rstrip(b"\n")

    @staticmethod
    def limit_from(args: tuple[str, ...]) -> int:
        if "--limit" in args:
            return int(args[args.index("--limit") + 1])
        return 16384

    def write_log(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def capture_local(self, path: Path, *extra: str, expect: int = 0) -> dict:
        payload, _ = self.run_helper(
            "capture",
            "local",
            "--artifact-root",
            str(self.artifacts),
            "--file",
            str(path),
            *extra,
            expect=expect,
        )
        return payload

    def test_positive_capture_and_literal_snippet_preserve_hash(self):
        data = b"setup\nAssertionError: expected true\nteardown\n"
        log = self.write_log("positive.log", data)
        payload = self.capture_local(log)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["artifact"]["stdout_sha256"], self.sha(data))
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            payload["artifact"]["handle"],
            "--pattern",
            "AssertionError",
            "--context",
            "1",
        )
        self.assertEqual(snippet["status"], "match")
        self.assertEqual(snippet["artifact"]["handle"], payload["artifact"]["handle"])
        self.assertIn("AssertionError", snippet["snippets"][0]["excerpt"])

    def test_output_budget_regression_preserves_hash_and_caps_response(self):
        data = (b"line ok\n" * 256) + b"FAILED final assertion\n" + (b"tail\n" * 256)
        naive = json.dumps({"status": "match", "excerpt": data.decode("utf-8")}).encode("utf-8")
        self.assertGreater(len(naive), 2048)
        log = self.write_log("budget.log", data)
        capture = self.capture_local(log)
        self.assertEqual(capture["artifact"]["stdout_sha256"], self.sha(data))
        snippet, raw = self.run_helper(
            "--limit",
            "2048",
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            capture["artifact"]["handle"],
            "--pattern",
            "FAILED",
            "--context",
            "2",
        )
        self.assertLessEqual(len(raw), 2048)
        self.assertEqual(snippet["artifact"]["stdout_sha256"], self.sha(data))
        self.assertIn("FAILED final assertion", snippet["snippets"][0]["excerpt"])

    def test_negative_missing_file_is_explicit_and_bounded(self):
        payload = self.capture_local(self.root / "missing.log", "--producer-exit-status", "2", expect=1)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(payload["artifact"]["complete"])
        self.assertEqual(payload["artifact"]["producer_exit_status"], 2)
        self.assertIn("local import failed", payload["errors"][0])

    def test_unreadable_path_is_explicit(self):
        payload = self.capture_local(self.root, expect=1)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(payload["artifact"]["complete"])

    def test_huge_individual_line_obeys_cap(self):
        log = self.write_log("huge.log", b"prefix " + (b"x" * 50000) + b" FAILED\n")
        capture = self.capture_local(log)
        snippet, raw = self.run_helper(
            "--limit",
            "1024",
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            capture["artifact"]["handle"],
            "--pattern",
            "FAILED",
            "--context",
            "0",
        )
        self.assertLessEqual(len(raw), 1024)
        self.assertTrue(snippet["response_truncated"] or snippet["snippets"][0]["excerpt_truncated"])

    def test_utf8_multibyte_text_obeys_cap(self):
        data = ("start\nFAIL: cafe \u00e9 " + ("\U0001f642" * 3000) + "\nend\n").encode("utf-8")
        log = self.write_log("utf8.log", data)
        capture = self.capture_local(log)
        snippet, raw = self.run_helper(
            "--limit",
            "1200",
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            capture["artifact"]["handle"],
            "--pattern",
            "FAIL:",
            "--context",
            "0",
        )
        self.assertLessEqual(len(raw), 1200)
        snippet["snippets"][0]["excerpt"].encode("utf-8")

    def test_no_match_returns_no_excerpt_without_success_inference(self):
        log = self.write_log("nomatch.log", b"all green maybe\nbut no requested literal\n")
        capture = self.capture_local(log)
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            capture["artifact"]["handle"],
            "--pattern",
            "NeedleNotHere",
        )
        self.assertEqual(snippet["status"], "no_match")
        self.assertEqual(snippet["selection"]["match_count"], 0)
        self.assertEqual(snippet["snippets"], [])

    def test_multi_failure_returns_multiple_bounded_ranges(self):
        log = self.write_log("multi.log", b"FAIL: one\nok\nok\nERROR: two\nok\nFAILED three\n")
        capture = self.capture_local(log)
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            capture["artifact"]["handle"],
            "--context",
            "0",
        )
        self.assertEqual(snippet["status"], "match")
        self.assertGreaterEqual(snippet["selection"]["match_count"], 3)
        self.assertGreaterEqual(snippet["selection"]["returned_ranges"], 3)

    def test_nonzero_producer_status_is_preserved(self):
        log = self.write_log("nonzero.log", b"FAILED\n")
        payload = self.capture_local(log, "--producer-exit-status", "17")
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["artifact"]["producer_exit_status"], 17)
        manifest = self.manifest(payload)
        self.assertEqual(manifest["producer"]["exit_status"], 17)
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["files"]["stdout"]["bytes"], len(b"FAILED\n"))
        artifact_dir = self.artifacts / "artifacts" / payload["artifact"]["handle"]
        stdout_mode = artifact_dir.joinpath("stdout.log").stat().st_mode & 0o777
        manifest_mode = artifact_dir.joinpath("manifest.json").stat().st_mode & 0o777
        self.assertEqual(stdout_mode, 0o600)
        self.assertEqual(manifest_mode, 0o600)

    def test_interrupted_download_is_not_cached_complete(self):
        CountingLogHandler.body = b"FAILED midway\n" * 10
        CountingLogHandler.mode = "partial"
        CountingLogHandler.hits = 0
        with self.http_server() as url:
            payload, _ = self.run_helper(
                "capture",
                "github",
                "--artifact-root",
                str(self.artifacts),
                "--api-url",
                url,
                "--repo",
                "owner/repo",
                "--run-id",
                "123",
                "--attempt",
                "1",
                "--job-id",
                "999",
                expect=1,
            )
        self.assertEqual(payload["status"], "error")
        self.assertFalse(payload["artifact"]["complete"])
        self.assertGreater(payload["artifact"]["stdout_bytes"], 0)
        self.assertNotEqual(payload["artifact"]["producer_exit_status"], 0)
        self.assertEqual(CountingLogHandler.hits, 1)
        self.assertFalse((self.artifacts / "cache").exists())

    def test_repeated_github_fetch_uses_cached_complete_artifact(self):
        CountingLogHandler.body = b"setup\nFAILED cached once\n"
        CountingLogHandler.mode = "ok"
        CountingLogHandler.hits = 0
        with self.http_server() as url:
            first, _ = self.run_helper(
                "capture",
                "github",
                "--artifact-root",
                str(self.artifacts),
                "--api-url",
                url,
                "--repo",
                "owner/repo",
                "--run-id",
                "123",
                "--attempt",
                "1",
                "--job-id",
                "999",
            )
            second, _ = self.run_helper(
                "capture",
                "github",
                "--artifact-root",
                str(self.artifacts),
                "--api-url",
                url,
                "--repo",
                "owner/repo",
                "--run-id",
                "123",
                "--attempt",
                "1",
                "--job-id",
                "999",
            )
        self.assertEqual(CountingLogHandler.hits, 1)
        self.assertEqual(first["artifact"]["handle"], second["artifact"]["handle"])
        self.assertEqual(first["artifact"]["stdout_sha256"], second["artifact"]["stdout_sha256"])
        self.assertFalse(first["artifact"]["cache_hit"])
        self.assertTrue(second["artifact"]["cache_hit"])
        snippet, _ = self.run_helper(
            "snippet",
            "--artifact-root",
            str(self.artifacts),
            "--handle",
            second["artifact"]["handle"],
            "--pattern",
            "FAILED",
        )
        self.assertEqual(snippet["artifact"]["handle"], second["artifact"]["handle"])
        self.assertEqual(snippet["artifact"]["stdout_sha256"], second["artifact"]["stdout_sha256"])

    def manifest(self, payload: dict) -> dict:
        path = self.artifacts / "artifacts" / payload["artifact"]["handle"] / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def sha(data: bytes) -> str:
        import hashlib

        return hashlib.sha256(data).hexdigest()

    def http_server(self):
        class ServerContext:
            def __enter__(inner_self):
                inner_self.server = socketserver.TCPServer(("127.0.0.1", 0), CountingLogHandler)
                inner_self.thread = threading.Thread(target=inner_self.server.serve_forever, daemon=True)
                inner_self.thread.start()
                host, port = inner_self.server.server_address
                return f"http://{host}:{port}"

            def __exit__(inner_self, exc_type, exc, tb):
                inner_self.server.shutdown()
                inner_self.server.server_close()
                inner_self.thread.join(timeout=5)

        return ServerContext()


if __name__ == "__main__":
    unittest.main()
