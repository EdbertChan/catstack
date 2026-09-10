"""Tests for categorical-scope-guard.

The positive commands under fixtures/ are real tool calls copied verbatim from
a transcript, paired with the real human turns that preceded them. Each
silence condition gets its own negative, and every way the input can be
unreadable gets an UNCHECKED test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402
from detect import CLEAN, HIT, UNCHECKED, LiveWindow, decide, read_live_window  # noqa: E402

ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse.py")

ALL_TASKS_FIRST = "can you make all tasks use claude and local executor"
ALL_TASKS_THIRD = "that's fine, just make all tasks use the local-worktree pool as the executor and claude as the model"
SUBSET_QUESTION = (
    "ok now are all failed tasks and pending tasks using local-worktree as the executor "
    "and claude as the agent? Yes or no?"
)
FOLLOW_UPS = (
    "just do it ad hoc for now",
    "there should be a invoker-cli mutation command to do this",
    "just use the local-only pool. Use Claude for hte AI models",
)
ALL_THE_PRS = "tag all the prs in catstack with admin-bypass"


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def human(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def said(text: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def tool_result(text: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": text}]},
        "toolUseResult": {"stdout": text},
    }


def write_transcript(entries: list[dict]) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    with handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return handle.name


def verdict_for(command: str, entries: list[dict]):
    path = write_transcript(entries)
    try:
        return decide(command, lambda: read_live_window(path))
    finally:
        os.unlink(path)


def run_entrypoint(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, ENTRYPOINT],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


class RealTranscriptPositives(unittest.TestCase):
    def test_blocks_update_tasks_status_in_after_all_tasks(self):
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), [human(ALL_TASKS_FIRST)])
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn(ALL_TASKS_FIRST, verdict.message)
        self.assertIn("status in ('pending','queued')", verdict.message)

    def test_blocks_when_all_tasks_was_said_three_follow_ups_back(self):
        entries = [human(ALL_TASKS_FIRST)] + [human(text) for text in FOLLOW_UPS]
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), entries)
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn(ALL_TASKS_FIRST, verdict.message)

    def test_blocks_when_the_subset_was_only_named_inside_a_state_question(self):
        entries = [human(ALL_TASKS_THIRD), said("Done: pending and queued."), human(SUBSET_QUESTION)]
        verdict = verdict_for(fixture("update_tasks_status_in_failed_pending_queued.txt"), entries)
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn("status in ('failed','pending','queued')", verdict.message)

    def test_blocks_status_not_in_narrowing(self):
        verdict = verdict_for(fixture("update_tasks_status_not_in_terminal.txt"), [human(ALL_TASKS_FIRST)])
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn("drops completed, skipped, cancelled", verdict.message)

    def test_blocks_gh_pr_list_state_open_feeding_an_edit_loop(self):
        verdict = verdict_for(fixture("gh_pr_list_state_open_edit_loop.txt"), [human(ALL_THE_PRS)])
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn("--state open", verdict.message)
        self.assertIn("all the prs", verdict.message)


class ShapePositives(unittest.TestCase):
    def test_blocks_invoker_query_tasks_status_feeding_a_retry(self):
        command = (
            "invoker-cli query tasks --status failed --output json | jq -r '.[].id' "
            "| xargs -n1 invoker-cli retry-task"
        )
        verdict = verdict_for(command, [human("retry every task in the workflow")])
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn("--status failed", verdict.message)

    def test_blocks_retry_tasks_status_flag(self):
        verdict = verdict_for("invoker-cli retry-tasks --status failed", [human("retry all tasks")])
        self.assertEqual(verdict.outcome, HIT, verdict.message)

    def test_blocks_jq_select_on_state_feeding_a_merge(self):
        command = (
            "gh pr list --json number,state --jq '.[]|select(.state==\"OPEN\")|.number' "
            "| xargs -n1 gh pr merge --squash"
        )
        verdict = verdict_for(command, [human("merge all of the pull requests")])
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn('.state=="OPEN"', verdict.message)

    def test_blocks_grep_narrowing_a_listing_by_state(self):
        command = (
            "invoker-cli query tasks --output text | grep -E 'pending|failed' | awk '{print $1}' "
            "| xargs -n1 invoker-cli retry-task"
        )
        verdict = verdict_for(command, [human("any and all tasks need a retry")])
        self.assertEqual(verdict.outcome, HIT, verdict.message)

    def test_blocks_python_filter_that_skips_a_status_set(self):
        command = (
            "invoker-cli query tasks --output json | python3 -c \"\n"
            "import json,sys\n"
            "ACTIVE = {'running','fixing_with_ai'}\n"
            "for t in json.load(sys.stdin):\n"
            "    if t['status'] in ACTIVE: continue\n"
            "    print(t['id'])\n"
            "\" | xargs -I{} invoker-ui --headless set task {} config.poolId local-only"
        )
        verdict = verdict_for(command, [human("make every task use the local-only pool")])
        self.assertEqual(verdict.outcome, HIT, verdict.message)
        self.assertIn("drops running, fixing_with_ai", verdict.message)

    def test_blocks_on_singular_and_each_phrasings(self):
        command = fixture("update_tasks_status_in_pending_queued.txt")
        for text in ("set every task to claude", "each task should use claude", "move the whole task list"):
            with self.subTest(text=text):
                self.assertEqual(verdict_for(command, [human(text)]).outcome, HIT)

    def test_blocks_on_slash_command_arguments(self):
        text = "<command-message>cat-mode</command-message>\n<command-name>/cat-mode</command-name>\n<command-args>make all tasks use claude</command-args>"
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), [human(text)])
        self.assertEqual(verdict.outcome, HIT, verdict.message)

    def test_block_message_names_both_exits(self):
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), [human(ALL_TASKS_FIRST)])
        self.assertIn("Drop the filter", verdict.message)
        self.assertIn("Complete set:", verdict.message)
        self.assertIn("keeps only pending, queued", verdict.message)


class SilenceConditions(unittest.TestCase):
    def test_silent_when_user_named_the_subset(self):
        command = fixture("update_tasks_status_in_pending_queued.txt")
        for text in ("make all the pending ones use claude", "every failed task and every pending task should use claude",
                     "set the pending tasks to claude"):
            with self.subTest(text=text):
                self.assertEqual(verdict_for(command, [human(text)]).outcome, CLEAN)

    def test_silent_when_the_filter_is_the_complete_enumeration(self):
        every = ",".join(f"'{s}'" for s in sorted(detect.TASK_STATUSES))
        command = f"sqlite3 invoker.db \"update tasks set execution_agent='claude' where status in ({every})\""
        self.assertEqual(verdict_for(command, [human(ALL_TASKS_FIRST)]).outcome, CLEAN)
        loop = "for n in $(gh pr list --state all --json number --jq '.[].number'); do gh pr edit $n --add-label x; done"
        self.assertEqual(verdict_for(loop, [human(ALL_THE_PRS)]).outcome, CLEAN)

    def test_silent_on_read_only_listing(self):
        self.assertEqual(verdict_for(fixture("gh_pr_list_state_open_readonly.txt"), [human(ALL_THE_PRS)]).outcome, CLEAN)
        self.assertEqual(verdict_for(fixture("invoker_query_status_readonly.txt"), [human(ALL_TASKS_FIRST)]).outcome, CLEAN)

    def test_silent_when_a_listing_is_only_displayed_beside_an_unrelated_mutation(self):
        command = (
            "gh pr close 337 --comment superseded\n"
            "echo \"open now: $(gh pr list --state open --json number -q length)\"\n"
            "gh pr list --state open --json number -q 'length' | sed 's/^/  /'"
        )
        self.assertEqual(verdict_for(command, [human("yes lets land everything in the catstack prs.")]).outcome, CLEAN)

    def test_silent_without_a_categorical_word(self):
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), [human(FOLLOW_UPS[2])])
        self.assertEqual(verdict.outcome, CLEAN)

    def test_silent_when_the_filter_targets_a_different_noun(self):
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), [human(ALL_THE_PRS)])
        self.assertEqual(verdict.outcome, CLEAN)

    def test_silent_on_the_unfiltered_update(self):
        self.assertEqual(verdict_for(fixture("update_tasks_unfiltered.txt"), [human(ALL_TASKS_THIRD)]).outcome, CLEAN)

    def test_silent_on_a_dry_run(self):
        verdict = verdict_for("invoker-cli retry-tasks --status failed --dry-run", [human("retry all tasks")])
        self.assertEqual(verdict.outcome, CLEAN)

    def test_silent_on_bare_all_in_an_unrelated_sentence(self):
        command = fixture("update_tasks_status_in_pending_queued.txt")
        for text in ("all right, use the local-only pool for tasks", "that's all for tasks today, move pending ones",
                     "not all tasks need claude"):
            with self.subTest(text=text):
                self.assertEqual(verdict_for(command, [human(text)]).outcome, CLEAN)

    def test_silent_when_all_tasks_only_appears_in_quoted_or_fenced_text(self):
        command = fixture("update_tasks_status_in_pending_queued.txt")
        for text in ('the old prompt said "make all tasks use claude", ignore it', "```\nmake all tasks use claude\n```\nmove pending ones",
                     "> make all tasks use claude\nthat was someone else"):
            with self.subTest(text=text):
                self.assertEqual(verdict_for(command, [human(text)]).outcome, CLEAN)

    def test_notifications_and_hook_feedback_are_not_human_turns(self):
        entries = [
            human("move the pending ones to claude"),
            human("<task-notification>\n<summary>make all tasks use claude</summary></task-notification>"),
            human("Stop hook feedback:\n[diu-stop]: make all tasks use claude"),
            tool_result("make all tasks use claude"),
        ]
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), entries)
        self.assertEqual(verdict.outcome, CLEAN)

    def test_allow_after_a_complete_set_line_in_the_reply(self):
        entries = [human(ALL_THE_PRS), said("Complete set: closed and merged PRs cannot take a merge-gate label.")]
        verdict = verdict_for(fixture("gh_pr_list_state_open_edit_loop.txt"), entries)
        self.assertEqual(verdict.outcome, CLEAN)

    def test_complete_set_line_before_the_latest_human_turn_does_not_clear(self):
        entries = [said("Complete set: only open PRs matter."), human(ALL_THE_PRS)]
        verdict = verdict_for(fixture("gh_pr_list_state_open_edit_loop.txt"), entries)
        self.assertEqual(verdict.outcome, HIT)

    def test_categorical_word_beyond_the_live_window_is_silent(self):
        entries = [human(ALL_TASKS_FIRST)] + [human(f"unrelated follow-up {i}") for i in range(detect.LIVE_TURNS)]
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), entries)
        self.assertEqual(verdict.outcome, CLEAN)

    def test_id_keyed_update_with_no_status_select_is_clean(self):
        command = (
            "python3 - <<'PY'\nimport sqlite3\nc=sqlite3.connect('x.db')\n"
            "rows=list(c.execute(\"select id, config from tasks where id like 'merge%'\"))\n"
            "for tid, cfg in rows:\n    c.execute(\"update tasks set config=? where id=?\", (cfg, tid))\nPY"
        )
        self.assertEqual(verdict_for(command, [human(ALL_TASKS_FIRST)]).outcome, CLEAN)

    def test_id_keyed_update_fed_by_a_status_select_is_blocked(self):
        command = (
            "python3 - <<'PY'\nimport sqlite3\nc=sqlite3.connect('x.db')\n"
            "rows=list(c.execute(\"select id from tasks where status in ('pending','queued')\"))\n"
            "for (tid,) in rows:\n    c.execute(\"update tasks set execution_agent='claude' where id=?\", (tid,))\nPY"
        )
        self.assertEqual(verdict_for(command, [human(ALL_TASKS_FIRST)]).outcome, HIT)


class UncheckedOutcomes(unittest.TestCase):
    def test_unchecked_blocks_a_filter_whose_values_cannot_be_read(self):
        commands = (
            "python3 -c \"c.execute(f\\\"update tasks set pool_id='x' where status in ({marks})\\\", wanted)\"",
            "for id in $(invoker-cli query tasks --status \"$S\" --output json | jq -r '.[].id'); do invoker-cli retry-task $id; done",
            "python3 -c \"c.execute('update tasks set pool_id=1 where ' + cond)\"",
        )
        for command in commands:
            with self.subTest(command=command):
                verdict = verdict_for(command, [human(ALL_TASKS_FIRST)])
                self.assertEqual(verdict.outcome, UNCHECKED, verdict.message)
                self.assertIn("UNCHECKED", verdict.message)

    def test_unreadable_transcript_missing_blocks_unchecked(self):
        verdict = decide(fixture("update_tasks_status_in_pending_queued.txt"),
                         lambda: read_live_window("/nonexistent/transcript.jsonl"))
        self.assertEqual(verdict.outcome, UNCHECKED)
        self.assertIn("could not read the live human turn", verdict.message)

    def test_no_transcript_path_blocks_unchecked(self):
        verdict = decide(fixture("update_tasks_status_in_pending_queued.txt"), lambda: read_live_window(""))
        self.assertEqual(verdict.outcome, UNCHECKED)

    def test_malformed_transcript_line_blocks_unchecked(self):
        path = write_transcript([human(ALL_TASKS_FIRST)])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
            handle.write(json.dumps(said("ok")) + "\n")
        try:
            verdict = decide(fixture("update_tasks_status_in_pending_queued.txt"), lambda: read_live_window(path))
        finally:
            os.unlink(path)
        self.assertEqual(verdict.outcome, UNCHECKED)
        self.assertIn("malformed", verdict.message)

    def test_torn_final_line_is_tolerated_not_unchecked(self):
        path = write_transcript([human(ALL_TASKS_FIRST)])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"type": "assistant", "mess')
        try:
            verdict = decide(fixture("update_tasks_status_in_pending_queued.txt"), lambda: read_live_window(path))
        finally:
            os.unlink(path)
        self.assertEqual(verdict.outcome, HIT)

    def test_transcript_with_no_human_turn_blocks_unchecked(self):
        verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), [said("hello")])
        self.assertEqual(verdict.outcome, UNCHECKED)

    def test_too_large_scan_window_blocks_unchecked(self):
        entries = [human(ALL_TASKS_FIRST)] + [said("x" * 2000) for _ in range(20)]
        with mock.patch.object(detect, "MAX_SCAN_BYTES", 4096), mock.patch.object(detect, "CHUNK_BYTES", 1024):
            verdict = verdict_for(fixture("update_tasks_status_in_pending_queued.txt"), entries)
        self.assertEqual(verdict.outcome, UNCHECKED)
        self.assertIn("scan cap", verdict.message)

    def test_parser_error_blocks_unchecked(self):
        with mock.patch.object(detect, "sql_filters", side_effect=RuntimeError("boom")):
            verdict = decide("update tasks set a=1 where status='x'", lambda: LiveWindow(turns=[ALL_TASKS_FIRST]))
        self.assertEqual(verdict.outcome, UNCHECKED)

    def test_missing_transcript_never_blocks_a_command_without_a_status_filter(self):
        verdict = decide("git status && ls -la", lambda: read_live_window("/nonexistent/transcript.jsonl"))
        self.assertEqual(verdict.outcome, CLEAN)


class Entrypoint(unittest.TestCase):
    def test_entrypoint_blocks_with_exit_2(self):
        path = write_transcript([human(ALL_TASKS_FIRST)])
        try:
            result = run_entrypoint({
                "tool_name": "Bash",
                "transcript_path": path,
                "tool_input": {"command": fixture("update_tasks_status_in_pending_queued.txt")},
            })
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("categorical-scope-guard", result.stderr)

    def test_entrypoint_unchecked_blocks_with_exit_2_when_transcript_is_missing(self):
        result = run_entrypoint({
            "tool_name": "Bash",
            "transcript_path": "/nonexistent/transcript.jsonl",
            "tool_input": {"command": fixture("update_tasks_status_in_pending_queued.txt")},
        })
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("UNCHECKED", result.stderr)

    def test_entrypoint_allows_a_clean_command(self):
        path = write_transcript([human(ALL_TASKS_FIRST)])
        try:
            result = run_entrypoint({"tool_name": "Bash", "transcript_path": path, "tool_input": {"command": "git status"}})
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_shell_tool_is_ignored(self):
        result = run_entrypoint({"tool_name": "Write", "tool_input": {"content": fixture("update_tasks_status_in_pending_queued.txt")}})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_garbage_payload_fails_open_with_log(self):
        result = subprocess.run([sys.executable, ENTRYPOINT], input="not json", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("not JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
