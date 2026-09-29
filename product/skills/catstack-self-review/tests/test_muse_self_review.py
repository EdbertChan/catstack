#!/usr/bin/env python3
"""Tests for the catstack-self-review skill (Muse harness adapter).

Covers the isolated-Muse-judge protocol without needing a real subagent
judge: judge-request emission on a full sweep with "judge": true, no
request on the fast path, and verdict application (hit -> exit 2,
clean -> exit 0) via muse_judge_apply.py.

Run: python3 -m unittest discover -s product/skills/catstack-self-review/tests -v
Every subprocess gets a fake HOME so the real ~/.cache is never touched.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(SKILL_DIR, "bin")
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(SKILL_DIR))
)
HOOKS_DIR = os.path.join(REPO_ROOT, "engine", "hooks")

JARGON_DRAFT = (
    "We should leverage synergistic paradigms to operationalize holistic "
    "throughput and ideate a robust, scalable framework going forward."
)
CLEAN_DRAFT = "Done. The three droplets are deleted and the bill shows $0 for them."


class TestIsolatedJudgeProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake_home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.fake_home)

    def _env(self):
        env = dict(os.environ)
        env["HOME"] = self.fake_home
        env["CATSTACK_HOOKS_DIR"] = HOOKS_DIR
        return env

    def _run_review(self, review):
        path = os.path.join(self.tmp.name, "review.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(review, handle)
        return subprocess.run(
            [sys.executable, os.path.join(BIN, "muse_self_review.py"), path],
            capture_output=True,
            text=True,
            timeout=180,
            env=self._env(),
        )

    def _request_path_from(self, proc):
        for line in proc.stdout.splitlines():
            if line.startswith("JUDGE_REQUEST "):
                return line.split(" ", 1)[1].strip()
        return None

    def _emit_request(self):
        proc = self._run_review(
            {
                "session_id": "test-judge-emit",
                "user_message": "Is the cleanup done?",
                "draft": JARGON_DRAFT,
                "judge": True,
            }
        )
        path = self._request_path_from(proc)
        self.assertIsNotNone(path, f"no JUDGE_REQUEST emitted:\n{proc.stdout}\n{proc.stderr}")
        return path

    def _apply_verdict(self, request_path, verdict_json):
        return subprocess.run(
            [sys.executable, os.path.join(BIN, "muse_judge_apply.py"),
             request_path, verdict_json],
            capture_output=True,
            text=True,
            timeout=60,
            env=self._env(),
        )

    def test_full_sweep_with_judge_true_emits_judge_request(self):
        path = self._emit_request()
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as handle:
            request = json.load(handle)
        for key in ("id", "hook", "prompt", "hit_if_all_true", "reply",
                    "judge_system_prompt", "session_id"):
            self.assertIn(key, request)
        self.assertEqual(request["hook"], "diu-plain-words")
        self.assertIn(JARGON_DRAFT, request["reply"])

    def test_fast_path_without_judge_flag_emits_no_request(self):
        proc = self._run_review(
            {
                "session_id": "test-no-judge",
                "user_message": "Is the cleanup done?",
                "draft": CLEAN_DRAFT,
                "hooks": ["diu-stop", "scope-lock", "repeat-deny-stop"],
            }
        )
        self.assertIsNone(
            self._request_path_from(proc),
            f"fast path must not emit a judge request:\n{proc.stdout}",
        )

    def test_judge_child_env_never_spawns_cli_runner(self):
        # The adapter must not shell out to claude/codex/cursor CLIs, which
        # do not exist on this harness. If enqueue() ran, the 40s judge wait
        # would blow the timeout; the request path returns in seconds.
        proc = self._run_review(
            {
                "session_id": "test-no-cli",
                "user_message": "Is the cleanup done?",
                "draft": JARGON_DRAFT,
                "judge": True,
            }
        )
        self.assertIsNotNone(self._request_path_from(proc))
        self.assertNotIn("judge.py", proc.stderr)

    def test_apply_hit_verdict_returns_2_with_diu_message(self):
        path = self._emit_request()
        verdict = json.dumps(
            {
                "match": True,
                "category": "plain-words-tech-jargon",
                "closest": "leverage synergistic paradigms",
            }
        )
        proc = self._apply_verdict(path, verdict)
        self.assertEqual(proc.returncode, 2, f"{proc.stdout}\n{proc.stderr}")
        self.assertIn("judge verdict: HIT", proc.stdout)
        self.assertTrue(os.path.isfile(path + ".verdict.json"), "verdict file written")
        self.assertFalse(os.path.exists(path), "handled request is consumed")

    def test_apply_clean_verdict_returns_0(self):
        path = self._emit_request()
        proc = self._apply_verdict(path, json.dumps({"match": False}))
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")
        self.assertIn("judge verdict: clean", proc.stdout)

    def test_apply_unparseable_verdict_fails_open(self):
        path = self._emit_request()
        proc = self._apply_verdict(path, "no json here at all")
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")
        self.assertIn("unchecked", proc.stdout)


class TestMuseOnlyPlacement(unittest.TestCase):
    """The skill is Muse-only: a real install.sh run must link it under the
    Muse skills root and leave it out of the other three harnesses."""

    def test_installs_for_muse_only(self):
        sys.path.insert(0, REPO_ROOT)
        from tests.test_install import run_install, skill_src

        with tempfile.TemporaryDirectory() as fake_home:
            result = run_install(fake_home)
            self.assertEqual(result.returncode, 0, result.stderr)

            target = os.path.join(fake_home, "workspace", "skills",
                                  "catstack-self-review")
            self.assertTrue(os.path.islink(target),
                            "catstack-self-review not symlinked for muse")
            self.assertEqual(os.readlink(target),
                             skill_src("catstack-self-review"))

            for skills_dir in (".claude", ".cursor", ".codex"):
                absent = os.path.join(fake_home, skills_dir, "skills",
                                      "catstack-self-review")
                self.assertFalse(os.path.exists(absent) or os.path.islink(absent),
                                 f"catstack-self-review should be absent for {skills_dir}")


if __name__ == "__main__":
    unittest.main()
