from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
HELPER = REPO / "corpus" / "skills" / "principle-guard-the-context-window" / "scripts" / "capture_tool_result.py"


class TestCaptureToolResult(unittest.TestCase):
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
        raw = proc.stdout.rstrip(b"\n")
        self.assertLessEqual(len(raw), self.limit_from(args))
        return json.loads(raw), raw

    @staticmethod
    def limit_from(args: tuple[str, ...]) -> int:
        if "--limit" in args:
            return int(args[args.index("--limit") + 1])
        return 16384

    def test_tiny_command_includes_body(self):
        payload, _ = self.run_helper(
            "--artifact-root",
            str(self.artifacts),
            "--",
            sys.executable,
            "-c",
            "print('hello-small')",
        )
        self.assertTrue(payload["artifact"]["body_included"])
        self.assertIn("hello-small", payload["stdout"])
        stdout_path = Path(payload["artifact"]["stdout_path"])
        self.assertTrue(stdout_path.is_file())
        self.assertEqual(stdout_path.read_text(encoding="utf-8").strip(), "hello-small")

    def test_over_cap_omits_payload_bytes(self):
        payload, raw = self.run_helper(
            "--artifact-root",
            str(self.artifacts),
            "--limit",
            "1024",
            "--",
            sys.executable,
            "-c",
            "print('x' * 5000)",
        )
        self.assertFalse(payload["artifact"]["body_included"])
        self.assertNotIn("stdout", payload)
        self.assertNotIn("stderr", payload)
        self.assertGreater(payload["omitted_payload_bytes"], 1024)
        self.assertLessEqual(len(raw), 1024)
        on_disk = Path(payload["artifact"]["stdout_path"]).read_bytes()
        self.assertGreater(len(on_disk), 1024)
        self.assertEqual(payload["artifact"]["stdout_sha256"], self.sha(on_disk))

    def test_hash_matches_file_and_nonzero_exit(self):
        payload, _ = self.run_helper(
            "--artifact-root",
            str(self.artifacts),
            "--",
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('boom\\n'); sys.exit(17)",
            expect=1,
        )
        self.assertEqual(payload["artifact"]["producer_exit_status"], 17)
        err = Path(payload["artifact"]["stderr_path"]).read_bytes()
        self.assertEqual(payload["artifact"]["stderr_sha256"], self.sha(err))
        self.assertIn("producer exited 17", payload["errors"][0])

    def test_utf8_and_huge_line_still_capped(self):
        payload, raw = self.run_helper(
            "--artifact-root",
            str(self.artifacts),
            "--limit",
            "800",
            "--",
            sys.executable,
            "-c",
            "print('café ' + ('😀' * 2000))",
        )
        self.assertFalse(payload["artifact"]["body_included"])
        self.assertLessEqual(len(raw), 800)
        on_disk = Path(payload["artifact"]["stdout_path"]).read_bytes()
        self.assertEqual(payload["artifact"]["stdout_sha256"], self.sha(on_disk))

    def test_gh_run_view_log_forces_metadata(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text("#!/bin/sh\necho short-log\n", encoding="utf-8")
        gh.chmod(0o700)
        import os
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        proc = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "--artifact-root",
                str(self.artifacts),
                "--",
                "gh",
                "run",
                "view",
                "9",
                "--log",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        data = json.loads(proc.stdout)
        self.assertFalse(data["artifact"]["body_included"])
        self.assertNotIn("stdout", data)

    def test_force_metadata_flag(self):
        payload, _ = self.run_helper(
            "--artifact-root",
            str(self.artifacts),
            "--force-metadata",
            "--",
            sys.executable,
            "-c",
            "print('tiny')",
        )
        self.assertFalse(payload["artifact"]["body_included"])
        self.assertNotIn("stdout", payload)

    @staticmethod
    def sha(data: bytes) -> str:
        import hashlib

        return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
