"""Tests for history-before-reversal.

The incident command is the real one: a plain revert of a merged PR, run
after reading that PR's body but without looking up why the conflicting
guard existed.
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
sys.path.insert(0, HOOK_DIR)

from detect import decide, find_reversals  # noqa: E402

PRETOOLUSE = os.path.join(HOOK_DIR, "claude_pretooluse.py")

INCIDENT_COMMAND = (
    "cd /work/Invoker-wt; git status --porcelain | head -3; "
    "git revert --no-commit ec5a49faa0 && git diff --cached --stat | tail -2"
)
READ_REVERTED = "cd /work/Invoker-wt; git show --stat ec5a49faa0 | tail -12; git show ec5a49faa0 -- ':!*test*' | head -120"
UNRELATED_LOG = "git log origin/master --oneline --grep='bump patch' -5; git log --oneline 39ce06fc2a..bbdab3075d"
PICKAXE = 'git log origin/master --oneline -S "trg_tasks_executor_routing_insert" | head -5'


def transcript(commands: list[str]) -> str:
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "fix all of it"}})]
    for index, command in enumerate(commands):
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": f"t{index}", "name": "Bash", "input": {"command": command}}
            ]},
        }))
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    handle.write("\n".join(lines) + "\n")
    handle.close()
    return handle.name


def run_hook(command: str, transcript_path: str | None, tool_name: str = "Bash"):
    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    if transcript_path is not None:
        payload["transcript_path"] = transcript_path
    return subprocess.run(
        [sys.executable, PRETOOLUSE], input=json.dumps(payload), capture_output=True, text=True
    )


class TestIncident(unittest.TestCase):
    def test_incident_revert_blocks_without_history_search_even_after_reading_the_pr(self):
        path = transcript([READ_REVERTED, UNRELATED_LOG, INCIDENT_COMMAND])
        verdict = decide(INCIDENT_COMMAND, path)
        self.assertEqual(verdict.outcome, "block")
        self.assertIn("git log -S", verdict.message)
        self.assertNotIn("read the change you are reversing", verdict.message)

    def test_incident_revert_allowed_after_reading_and_pickaxe(self):
        path = transcript([READ_REVERTED, PICKAXE, INCIDENT_COMMAND])
        self.assertEqual(decide(INCIDENT_COMMAND, path).outcome, "allow")

    def test_entrypoint_exits_2_on_incident(self):
        result = run_hook(INCIDENT_COMMAND, transcript([READ_REVERTED]))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("history-before-reversal", result.stderr)

    def test_entrypoint_exits_0_when_satisfied(self):
        result = run_hook(INCIDENT_COMMAND, transcript([READ_REVERTED, PICKAXE]))
        self.assertEqual(result.returncode, 0, result.stderr)


class TestShapes(unittest.TestCase):
    def test_revert_with_nothing_read_names_both_steps(self):
        verdict = decide("git revert abc1234", transcript([]))
        self.assertEqual(verdict.outcome, "block")
        self.assertIn("git show abc1234", verdict.message)
        self.assertIn("git log -S", verdict.message)

    def test_revert_forms_are_detected(self):
        for command in (
            "git revert abc1234",
            "git -C /repo revert --no-edit abc1234",
            "GIT_EDITOR=true git revert -m 1 abc1234",
            "cd /repo && git revert HEAD~1",
            'git commit -m "Revert \\"Persist pool routing (#12465)\\""',
            "git commit -q --message='Revert \"x\"'",
        ):
            self.assertTrue(find_reversals(command), command)

    def test_hand_written_revert_commit_needs_a_read(self):
        verdict = decide('git commit -m "Revert \\"x\\""', transcript([PICKAXE]))
        self.assertEqual(verdict.outcome, "block")
        self.assertIn("git show <sha>", verdict.message)

    def test_pr_view_counts_as_reading_the_change(self):
        path = transcript(["gh pr view 12465 --json body", "git blame -L 690,720 -- schema.ts"])
        self.assertEqual(decide("git revert ec5a49faa0", path).outcome, "allow")

    def test_history_search_spellings(self):
        for search in (
            "git log -Strg_tasks", "git log -G 'routing.*invariant'", "git log --follow -- a.ts",
            "git log -L 10,20:a.ts", "git blame a.ts",
        ):
            path = transcript(["git show ec5a49faa0", search])
            self.assertEqual(decide("git revert ec5a49faa0", path).outcome, "allow", search)

    def test_message_grep_is_not_a_history_search(self):
        path = transcript(["git show ec5a49faa0", "git log --grep=revert --oneline"])
        self.assertEqual(decide("git revert ec5a49faa0", path).outcome, "block")

    def test_reading_a_different_sha_does_not_count(self):
        path = transcript(["git show 1111111", PICKAXE])
        self.assertEqual(decide("git revert ec5a49faa0", path).outcome, "block")


def session_layout(main_commands: list[str], helper_commands: list[str]) -> tuple[str, str]:
    root = tempfile.mkdtemp()
    main_log = os.path.join(root, "sess-1.jsonl")
    os.makedirs(os.path.join(root, "sess-1", "subagents"))
    helper_log = os.path.join(root, "sess-1", "subagents", "agent-abc.jsonl")
    for target, commands in ((main_log, main_commands), (helper_log, helper_commands)):
        with open(transcript(commands)) as source, open(target, "w") as sink:
            sink.write(source.read())
    return main_log, helper_log


class TestDelegatedResearch(unittest.TestCase):
    def test_history_search_done_by_a_helper_agent_counts(self):
        main_log, _ = session_layout([READ_REVERTED], [PICKAXE, "gh pr view 11576 --json body"])
        self.assertEqual(decide(INCIDENT_COMMAND, main_log).outcome, "allow")

    def test_helper_agent_revert_sees_the_main_session_research(self):
        _, helper_log = session_layout([READ_REVERTED, PICKAXE], [])
        self.assertEqual(decide(INCIDENT_COMMAND, helper_log).outcome, "allow")

    def test_helper_agent_without_history_search_still_blocks(self):
        main_log, _ = session_layout([READ_REVERTED], ["git log --oneline -5 -- schema.ts"])
        self.assertEqual(decide(INCIDENT_COMMAND, main_log).outcome, "block")

    def test_unreadable_helper_log_adds_no_evidence(self):
        main_log, helper_log = session_layout([READ_REVERTED], [])
        with open(helper_log, "w") as handle:
            handle.write("corrupt\n")
        self.assertEqual(decide(INCIDENT_COMMAND, main_log).outcome, "block")


class TestNeighbours(unittest.TestCase):
    def test_non_reversal_commands_are_silent(self):
        empty = transcript([])
        for command in (
            "git revert --abort",
            "git revert --continue",
            "git log --grep=revert",
            "echo 'git revert abc1234'",
            "gh pr view 12818",
            'git commit -m "Do not revert the pool change"',
            "git reset --hard origin/main",
            "rg 'git revert' docs/",
            "cat <<EOF > notes.md\ngit revert abc1234\nEOF",
        ):
            self.assertEqual(decide(command, empty).outcome, "allow", command)

    def test_non_shell_tool_is_silent(self):
        result = run_hook("git revert abc1234", transcript([]), tool_name="Write")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")


class TestUnreadable(unittest.TestCase):
    def test_missing_transcript_is_unchecked_and_fails_open(self):
        verdict = decide("git revert abc1234", "/nonexistent/transcript.jsonl")
        self.assertEqual(verdict.outcome, "unchecked")
        result = run_hook("git revert abc1234", "/nonexistent/transcript.jsonl")
        self.assertEqual(result.returncode, 0)
        self.assertIn("UNCHECKED", result.stderr)

    def test_malformed_transcript_is_unchecked(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        handle.write("not json\nstill not json\n")
        handle.close()
        self.assertEqual(decide("git revert abc1234", handle.name).outcome, "unchecked")

    def test_no_transcript_path_is_unchecked(self):
        result = run_hook("git revert abc1234", None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("UNCHECKED", result.stderr)

    def test_malformed_payload_fails_open(self):
        result = subprocess.run(
            [sys.executable, PRETOOLUSE], input="{not json", capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("UNCHECKED", result.stderr)


if __name__ == "__main__":
    unittest.main()
