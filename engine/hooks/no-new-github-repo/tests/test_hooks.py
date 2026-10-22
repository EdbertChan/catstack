"""Tests for the no-new-github-repo PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/no-new-github-repo/tests -v

The two real payloads come from the session that created a repository by
mistake: the command that did it, and a later command that only wrote the
words into a memory note. The first must hit, the second must stay clean.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402

CLAUDE = os.path.join(HOOK_DIR, "claude_pretooluse.py")
CURSOR = os.path.join(HOOK_DIR, "cursor_pretooluse.py")
CODEX = os.path.join(HOOK_DIR, "codex_pretooluse.py")
INCIDENT = (
    'gh repo create EdbertChan/ci-projection-time-savings --private --description '
    '"CI savings projection: how much sooner pipelines would finish if a job or step ran faster"'
)
MODE_ENV = "CATSTACK_HOOK_MODE_NO_NEW_GITHUB_REPO"


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def payload(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def run_entrypoint(entrypoint, stdin, env_extra=None):
    env = dict(os.environ)
    env.pop(MODE_ENV, None)
    with tempfile.TemporaryDirectory() as metrics_dir:
        env["CATSTACK_HOOK_METRICS_DIR"] = metrics_dir
        env.setdefault("CATSTACK_HOOK_TEST_MODEL", "gpt-5.6-sol")
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, entrypoint],
            input=stdin if isinstance(stdin, bytes) else json.dumps(stdin).encode("utf-8"),
            capture_output=True,
            env=env,
        )


class DetectorHits(unittest.TestCase):
    def test_hit_incident_command(self):
        findings = detect.decide(INCIDENT)
        self.assertEqual([detect.RULE_GH_REPO_CREATE], [f.rule_id for f in findings])
        self.assertIn("No new GitHub repositories from this machine", findings[0].message)
        self.assertIn("ci-projection-time-savings", findings[0].message)

    def test_hit_real_transcript_script_that_created_the_repo(self):
        findings = detect.decide(read("incident_command.txt"))
        self.assertEqual([detect.RULE_GH_REPO_CREATE], [f.rule_id for f in findings])

    def test_hit_every_fixture_with_its_rule(self):
        for case in load("commands_hit.json"):
            with self.subTest(case["label"]):
                findings = detect.decide(case["command"])
                self.assertEqual([case["rule"]], [f.rule_id for f in findings], case["command"])

    def test_hit_two_creates_in_one_script_report_both(self):
        findings = detect.decide("gh repo create a/b; gh repo fork c/d")
        self.assertEqual(
            [detect.RULE_GH_REPO_CREATE, detect.RULE_GH_REPO_FORK],
            [f.rule_id for f in findings],
        )

    def test_hit_codex_argv_command_list(self):
        event = {"tool_name": "exec_command", "tool_input": {"command": ["bash", "-lc", "cd x && gh repo create a/b"]}}
        self.assertEqual([detect.RULE_GH_REPO_CREATE], [f.rule_id for f in detect.detect(event)])

    def test_hit_unbalanced_quote_still_decided_by_the_fallback_tokenizer(self):
        findings = detect.decide("echo 'oops && gh repo create a/b")
        self.assertEqual([detect.RULE_GH_REPO_CREATE], [f.rule_id for f in findings])


class DetectorStaysClean(unittest.TestCase):
    def test_clean_every_fixture(self):
        for case in load("commands_clean.json"):
            with self.subTest(case["label"]):
                self.assertEqual([], detect.decide(case["command"]), case["command"])

    def test_clean_real_transcript_memory_note_that_only_names_the_command(self):
        self.assertEqual([], detect.decide(read("memory_note_heredoc.txt")))

    def test_clean_non_shell_tool_without_a_command(self):
        event = {"tool_name": "Write", "tool_input": {"file_path": "x", "content": "gh repo create a/b"}}
        self.assertEqual([], detect.detect(event))


class DetectorRefusesWhatItCannotRead(unittest.TestCase):
    def test_unchecked_missing_command_field_refuses(self):
        findings = detect.detect({"tool_name": "Bash", "tool_input": {}})
        self.assertEqual([detect.RULE_UNCHECKED], [f.rule_id for f in findings])
        self.assertIn("could not read the command; refusing", findings[0].message)

    def test_unchecked_missing_tool_input_refuses(self):
        findings = detect.detect({"tool_name": "Bash"})
        self.assertEqual([detect.RULE_UNCHECKED], [f.rule_id for f in findings])

    def test_unchecked_command_that_is_not_text_refuses(self):
        findings = detect.detect({"tool_name": "Bash", "tool_input": {"command": 7}})
        self.assertEqual([detect.RULE_UNCHECKED], [f.rule_id for f in findings])
        self.assertIn("not text", findings[0].message)

    def test_unchecked_payload_error_refuses(self):
        findings = detect.detect({"_payload_error": "the hook payload is not JSON"})
        self.assertEqual([detect.RULE_UNCHECKED], [f.rule_id for f in findings])

    def test_unchecked_graphql_body_from_a_file_refuses(self):
        findings = detect.decide("gh api graphql --input mutation.json")
        self.assertEqual([detect.RULE_UNCHECKED], [f.rule_id for f in findings])
        self.assertIn("cannot read", findings[0].message)


class ClaudeEntrypoint(unittest.TestCase):
    def test_hit_exits_2_with_the_rule_and_matched_text_on_stderr(self):
        result = run_entrypoint(CLAUDE, payload(INCIDENT))
        self.assertEqual(2, result.returncode, result.stderr)
        stderr = result.stderr.decode("utf-8")
        self.assertIn("No new GitHub repositories from this machine; this project stays local.", stderr)
        self.assertIn("Ask the user where the code should live.", stderr)
        self.assertIn("EdbertChan/ci-projection-time-savings", stderr)
        self.assertEqual(b"", result.stdout)

    def test_hit_real_transcript_script_exits_2(self):
        result = run_entrypoint(CLAUDE, payload(read("incident_command.txt")))
        self.assertEqual(2, result.returncode, result.stderr)

    def test_clean_exits_0_with_no_output(self):
        result = run_entrypoint(CLAUDE, payload("gh repo view a/b"))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"", result.stdout)
        self.assertEqual(b"", result.stderr)

    def test_unchecked_missing_command_field_exits_2_refusing(self):
        result = run_entrypoint(CLAUDE, {"tool_name": "Bash", "tool_input": {"description": "no command here"}})
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("could not read the command; refusing", result.stderr.decode("utf-8"))

    def test_unchecked_non_json_stdin_exits_2_refusing(self):
        result = run_entrypoint(CLAUDE, b"this is not json")
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("could not read the command; refusing", result.stderr.decode("utf-8"))

    def test_unchecked_json_array_stdin_exits_2_refusing(self):
        result = run_entrypoint(CLAUDE, b'["tool_name", "Bash"]')
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("could not read the command; refusing", result.stderr.decode("utf-8"))

    def test_unchecked_non_utf8_stdin_exits_2_refusing(self):
        result = run_entrypoint(CLAUDE, b'{"tool_name": "Bash", "tool_input": {"command": "gh repo view \xff\xfe"}}')
        self.assertEqual(2, result.returncode, result.stderr)
        stderr = result.stderr.decode("utf-8")
        self.assertIn("could not read the command; refusing", stderr)
        self.assertIn("not UTF-8", stderr)

    def test_warn_override_turns_the_block_into_context(self):
        result = run_entrypoint(CLAUDE, payload(INCIDENT), {MODE_ENV: "warn"})
        self.assertEqual(0, result.returncode, result.stderr)
        body = json.loads(result.stdout)
        self.assertIn("No new GitHub repositories", body["hookSpecificOutput"]["additionalContext"])


class CursorAndCodexEntrypoints(unittest.TestCase):
    def test_hit_cursor_denies_with_the_rule(self):
        result = run_entrypoint(CURSOR, payload(INCIDENT))
        self.assertEqual(0, result.returncode, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual("deny", body["permission"])
        self.assertIn("No new GitHub repositories", body["user_message"])

    def test_hit_codex_denies_with_the_rule(self):
        result = run_entrypoint(CODEX, payload(INCIDENT))
        self.assertEqual(0, result.returncode, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual("deny", body["hookSpecificOutput"]["permissionDecision"])
        self.assertIn("No new GitHub repositories", body["hookSpecificOutput"]["permissionDecisionReason"])

    def test_clean_cursor_and_codex_stay_silent(self):
        for entrypoint in (CURSOR, CODEX):
            with self.subTest(os.path.basename(entrypoint)):
                result = run_entrypoint(entrypoint, payload("gh pr create --base main"))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(b"", result.stdout)


if __name__ == "__main__":
    unittest.main()
