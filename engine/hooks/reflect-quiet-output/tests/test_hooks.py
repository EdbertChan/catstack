#!/usr/bin/env python3
"""Tests for reflect-quiet-output (Stop).

`fixtures/findings_reply_fires.md` is a real reflect reply from a Claude Code
session, with its transcript paths removed: a cost-audit line, then Accepted,
Backlog, Route-to-automate-me and Rejected sections, all printed into the chat
window. `fixtures/one_sentence_silent.md` is the reply the rule asks for.

The reflect invocation shapes come from the harness: the typed slash command's
`<command-message>reflect</command-message><command-name>/reflect</command-name>`
envelope (the same text the wrong-check-reflect tests use), a `Skill` tool
call with `skill: reflect`, and a `Read` of `.../skills/reflect/SKILL.md`.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402

REFLECT_COMMAND = "<command-message>reflect</command-message>\n<command-name>/reflect</command-name>\n"
SKILL_PATH = "/Users/someone/.claude/skills/reflect/SKILL.md"


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def human(text: str, **fields) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}, **fields}


def assistant_text(text: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def tool_use(name: str, inp: dict, tool_id: str = "toolu_1") -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}]},
    }


def tool_result(text: str, tool_id: str = "toolu_1") -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text}]},
        "toolUseResult": {"stdout": text},
    }


def transcript(rows: list[dict]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(row) for row in rows) + "\n")
    tmp.close()
    return tmp.name


def decide(message: str, rows: list[dict], **extra):
    err = io.StringIO()
    path = transcript(rows)
    try:
        finding = detect.decide({"last_assistant_message": message, "transcript_path": path, **extra}, stderr=err)
    finally:
        os.unlink(path)
    return finding, err.getvalue()


def run_hook(payload: dict):
    out, err = io.StringIO(), io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out), redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class TestFiresOnFindingsInChat(unittest.TestCase):
    def test_fires_on_real_multi_section_findings_reply_after_reflect_command(self):
        finding, err = decide(fixture("findings_reply_fires.md"), [human(REFLECT_COMMAND)])
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_id, detect.RULE_FINDINGS_IN_CHAT)
        self.assertIn("cost audit", finding.evidence)
        self.assertIn("accepted", finding.evidence)
        self.assertIn("PR body", finding.message)
        self.assertEqual(err, "")

    def test_fires_on_two_sentence_reply_after_skill_tool_loaded_reflect(self):
        rows = [human("please reflect on this session"), tool_use("Skill", {"skill": "reflect"})]
        finding, _ = decide("Opened https://github.com/o/r/pull/9. The Accepted items are a hook and a test.", rows)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_id, detect.RULE_MULTI_SENTENCE)
        self.assertIn("Skill tool", finding.evidence)

    def test_fires_on_bulleted_reply_after_read_of_reflect_skill(self):
        rows = [human("Stop hook feedback:\nreflect-on-thrash: run /reflect"), tool_use("Read", {"file_path": SKILL_PATH})]
        finding, _ = decide("PR opened: https://github.com/o/r/pull/9\n- hook added\n- test added", rows)
        self.assertIsNotNone(finding)
        self.assertIn("Read of skills/reflect/SKILL.md", finding.evidence)

    def test_fires_when_agent_prompt_names_the_reflect_skill(self):
        rows = [human("reflect"), tool_use("Agent", {"prompt": f"Read {SKILL_PATH} and run steps 1-4 on this transcript."})]
        finding, _ = decide("Accepted:\n- one\nBacklog:\n- two", rows)
        self.assertIsNotNone(finding)

    def test_hook_blocks_with_exit_2_and_names_the_pr_body(self):
        path = transcript([human(REFLECT_COMMAND)])
        with tempfile.TemporaryDirectory() as metrics:
            with patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": metrics}):
                code, out, err = run_hook({
                    "hook_event_name": "Stop",
                    "session_id": "reflect-quiet-output-test",
                    "last_assistant_message": fixture("findings_reply_fires.md"),
                    "transcript_path": path,
                })
        os.unlink(path)
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        self.assertIn("reflect-quiet-output", err)
        self.assertIn("exactly one sentence", err)


class TestSilentOnCompliantOrUnrelatedReplies(unittest.TestCase):
    def test_silent_on_one_sentence_reply_with_pr_link(self):
        finding, err = decide(fixture("one_sentence_silent.md"), [human(REFLECT_COMMAND)])
        self.assertIsNone(finding)
        self.assertEqual(err, "")

    def test_silent_when_the_one_sentence_mentions_accepted_mid_sentence(self):
        finding, _ = decide(
            "Opened [the PR](https://github.com/o/r/pull/9) with the Accepted and Backlog list in its body.",
            [human(REFLECT_COMMAND)],
        )
        self.assertIsNone(finding)

    def test_silent_on_long_reply_when_no_reflect_invocation(self):
        rows = [human("fix the flaky test"), tool_use("Bash", {"command": "pytest -q"})]
        finding, err = decide(fixture("findings_reply_fires.md"), rows)
        self.assertIsNone(finding)
        self.assertEqual(err, "")

    def test_silent_when_reflect_command_is_only_quoted_in_a_tool_result(self):
        rows = [
            human("what did the last session ask for?"),
            tool_use("Bash", {"command": "grep -m1 command-name session.jsonl"}),
            tool_result('{"content": "<command-name>/reflect</command-name>"}'),
        ]
        finding, _ = decide("Two things.\nFirst it asked for X.\nThen for Y.", rows)
        self.assertIsNone(finding)

    def test_silent_when_reflect_ran_in_an_earlier_turn(self):
        rows = [
            human(REFLECT_COMMAND),
            assistant_text("Reflect opened https://github.com/o/r/pull/9, one question in the PR."),
            human("drop item 2"),
        ]
        finding, _ = decide("Dropped item 2 from the PR. The branch is updated and the body rewritten.", rows)
        self.assertIsNone(finding)

    def test_silent_when_the_turn_edits_the_reflect_skill_instead_of_running_it(self):
        rows = [
            human("tighten step 7 of the reflect skill"),
            tool_use("Read", {"file_path": SKILL_PATH}),
            tool_use("Edit", {"file_path": SKILL_PATH, "old_string": "a", "new_string": "b"}, "toolu_2"),
        ]
        finding, _ = decide("Step 7 now says the list goes in the PR.\nTest added.\nPreflight passed.", rows)
        self.assertIsNone(finding)

    def test_slash_command_still_counts_when_the_turn_also_edits_the_skill(self):
        rows = [
            human(REFLECT_COMMAND),
            tool_use("Edit", {"file_path": SKILL_PATH, "old_string": "a", "new_string": "b"}),
        ]
        finding, _ = decide("Accepted:\n- edit step 7\nRejected:\n- nothing", rows)
        self.assertIsNotNone(finding)

    def test_silent_when_task_notification_is_the_last_user_row(self):
        rows = [
            human("plan the release"),
            human("<task-notification>agent done: <command-name>/reflect</command-name></task-notification>"),
        ]
        finding, _ = decide("Release plan.\nStep one.\nStep two.", rows)
        self.assertIsNone(finding)

    def test_allows_when_stop_hook_active(self):
        finding, err = decide(fixture("findings_reply_fires.md"), [human(REFLECT_COMMAND)], stop_hook_active=True)
        self.assertIsNone(finding)
        self.assertEqual(err, "")


class TestUncheckedWhenTheTranscriptCannotBeRead(unittest.TestCase):
    def test_unreadable_transcript_is_unchecked_not_clean(self):
        err = io.StringIO()
        finding = detect.decide(
            {"last_assistant_message": fixture("findings_reply_fires.md"), "transcript_path": "/missing/session.jsonl"},
            stderr=err,
        )
        self.assertIsNone(finding)
        self.assertIn("catstack-hook-unchecked reflect-quiet-output", err.getvalue())
        self.assertIn("could not be read", err.getvalue())

    def test_missing_transcript_path_is_unchecked(self):
        err = io.StringIO()
        finding = detect.decide({"last_assistant_message": "Accepted:\n- x"}, stderr=err)
        self.assertIsNone(finding)
        self.assertIn("no transcript path", err.getvalue())

    def test_empty_reply_is_unchecked(self):
        finding, err = decide("   ", [human(REFLECT_COMMAND)])
        self.assertIsNone(finding)
        self.assertIn("no assistant reply text", err)

    def test_garbage_lines_in_transcript_are_skipped_and_the_rest_read(self):
        path = transcript([human(REFLECT_COMMAND)])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("not json\n")
        err = io.StringIO()
        finding = detect.decide(
            {"last_assistant_message": "Accepted:\n- x\nRejected:\n- y", "transcript_path": path}, stderr=err
        )
        os.unlink(path)
        self.assertIsNotNone(finding)


class TestManifest(unittest.TestCase):
    def test_manifest_opts_out_of_subagent_stop_with_a_reason(self):
        with open(os.path.join(HOOK_DIR, "claude.hook.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIs(manifest["subagent_stop"]["inherit"], False)
        self.assertIn("subagent", manifest["subagent_stop"]["reason"])
        commands = [h["command"] for e in manifest["hooks"]["Stop"] for h in e["hooks"]]
        self.assertTrue(any("reflect-quiet-output/claude_stop_check.py" in c for c in commands), commands)


class TestSentenceCounting(unittest.TestCase):
    def test_url_dots_do_not_split_sentences(self):
        self.assertEqual(detect.sentence_count("Opened https://github.com/o/r/pull/9 with the findings in its body."), 1)

    def test_markdown_link_is_one_token(self):
        self.assertEqual(detect.sentence_count("Opened [PR 9](https://github.com/o/r/pull/9), one question in the PR."), 1)

    def test_two_sentences_count_as_two(self):
        self.assertEqual(detect.sentence_count("Opened the PR. One question in it."), 2)

    def test_newline_separated_lines_count_separately(self):
        self.assertEqual(detect.sentence_count("Opened the PR\n- hook\n- test"), 3)


if __name__ == "__main__":
    unittest.main()
