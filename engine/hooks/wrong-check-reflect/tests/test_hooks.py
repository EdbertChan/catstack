#!/usr/bin/env python3
"""Tests for wrong-check-reflect."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import codex_notify  # noqa: E402
import cursor_session  # noqa: E402
import detect  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_flags"))
import flags  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox  # noqa: E402
import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402


PY = sys.executable
REFLECT_COMMAND = "<command-message>reflect</command-message><command-name>/reflect</command-name>"
HIT_TEXT = "Correction: the file I pointed you to earlier is not the one in use; the real one is src/b.py."
OPTION_TEXT = "You're right. Let's go with option B."
COUNT_TEXT = "I double-checked my earlier count and it holds; nothing in it was wrong."
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": HIT_TEXT})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
SLOW_CLEAN = ["slow", [PY, "-c", f"import time; time.sleep(2); print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


def run_cursor(payload: dict) -> tuple[dict, str]:
    out = io.StringIO()
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out), redirect_stderr(err):
            cursor_session.main()
    return json.loads(out.getvalue() or "{}"), err.getvalue()


def run_codex_notify(argv: list[str]) -> str:
    err = io.StringIO()
    with patch.object(sys, "argv", ["codex_notify.py", *argv]):
        with redirect_stderr(err):
            codex_notify.main()
    return err.getvalue()


def transcript_line(role: str, text: str) -> str:
    """One transcript row. A role of "meta" is the harness talking, not the user.

    The shape of a meta row is taken from a real Claude Code transcript: the
    harness files its Stop-hook feedback and a skill's injected body as
    `type: "user"` rows carrying `isMeta: true`. A `sidechain-` prefix files
    the row under a subagent, which a real transcript marks with
    `isSidechain: true`.

    A role of "tool_result" is the other user-shaped row the harness writes,
    and the one it flags with none of those keys: a real transcript gives it
    a `tool_result` content block and a `toolUseResult` field, and no
    `isMeta`.

    A role of "stacked" is the second command of one submission. Typing
    `/reflect /cat-mode text` writes an envelope row per command, and marks
    every row after the first `stackedExpansion: true`; the shape is taken
    from `engine/skills/reflect/scripts/tests/fixtures/provenance/`
    `stacked_commands/claude.jsonl`.
    """
    if role == "stacked":
        return json.dumps({
            "type": "user",
            "message": {"role": "user", "content": text},
            "stackedExpansion": True,
        })
    if role == "tool_result":
        return json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": text}]},
            "toolUseResult": {"stdout": text},
        })
    sidechain = role.startswith("sidechain-")
    role = role[len("sidechain-"):] if sidechain else role
    meta = role == "meta"
    kind = "user" if meta else role
    row = {"type": kind, "message": {"role": kind, "content": [{"type": "text", "text": text}]}}
    if meta or sidechain:
        row["isMeta"] = meta
        row["isSidechain"] = sidechain
    return json.dumps(row)


class TestWrongCheckReflect(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.reflect_state = tempfile.TemporaryDirectory()
        self.reflect_env = patch.dict(os.environ, {
            flags.REFLECT_ENFORCEMENT: "1",
            "WRONG_CHECK_REFLECT_STATE_DIR": self.reflect_state.name,
        })
        self.reflect_env.start()
        self.use_runners(ANSWERS_HIT)
        detect.STATE_DIR = self.reflect_state.name
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.reflect_env.stop()
        self.reflect_state.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        super().tearDown()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, *lines: tuple[str, str], name: str = "session.jsonl") -> str:
        path = os.path.join(self.reflect_state.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            for role, text in lines:
                handle.write(transcript_line(role, text) + "\n")
        return path

    def wait_for_jobs(self, count: int, seconds: float = 5) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            jobs = self.jobs()
            if len(jobs) == count:
                return jobs
            time.sleep(0.05)
        return self.jobs()

    def wait_for_messages(self, path: str, seconds: float = 15) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            got = judge_inbox.messages(path)
            if got:
                return got
            time.sleep(0.1)
        return []

    def test_dictionary_loads(self):
        dictionary = phrases.load("wrong-check-reflect")
        self.assertEqual(dictionary["checker"], "wrong-check-reflect")
        self.assertEqual(dictionary["on_hit"], detect.FOLLOWUP)

    def test_decide_no_longer_returns_pattern_hit(self):
        self.assertIsNone(detect.decide({"last_assistant_message": HIT_TEXT}))

    def test_enqueue_is_off_unless_the_flag_is_on(self):
        """No job is queued, and none is silently deferred either.

        The gate sits inside enqueue_judge rather than in the harness wrapper
        so every entry point -- Claude Stop, the Codex notify, the Cursor
        session hook -- is covered by the one check.
        """
        path = self.write_transcript(("assistant", HIT_TEXT))
        for value in (None, "0", "false", "off", "no"):
            env = {"HOME": self.reflect_state.name}
            if value is not None:
                env[flags.REFLECT_ENFORCEMENT] = value
            with self.subTest(value=value), patch.dict(os.environ, env, clear=True):
                self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_claude_stop_queues_job_for_normal_reply(self):
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(("assistant", HIT_TEXT))
        blocked, err = run_claude({"transcript_path": path})
        self.assertFalse(blocked)
        self.assertEqual(err, "")
        jobs = self.wait_for_jobs(1)
        self.assertEqual(len(jobs), 1)
        with open(os.path.join(self.state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertEqual(job["hook"], "wrong-check-reflect")
        self.assertEqual(job["transcript"], path)
        self.assertEqual(job["on_hit"], detect.FOLLOWUP)

    def test_hit_verdict_reaches_agent_as_dictionary_on_hit(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.wait_for_messages(path), [detect.FOLLOWUP])

    def test_clean_verdict_says_nothing(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(("assistant", OPTION_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_unchecked_verdict_says_could_not_judge(self):
        self.use_runners(MISSING)
        path = self.write_transcript(("assistant", COUNT_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_judge_not_enqueued_when_stop_hook_active(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path, "stop_hook_active": True}))
        self.assertEqual(self.jobs(), [])

    def test_subagent_stop_with_no_transcript_file_queues_nothing(self):
        """Claude Code fires SubagentStop for the one-line progress blurbs it
        writes about a running background agent. Those payloads name an
        agent transcript that is never written, so the job had no transcript
        and its verdict had nowhere to go."""
        parent = self.write_transcript(("assistant", HIT_TEXT))
        blocked, err = run_claude({
            "hook_event_name": "SubagentStop",
            "transcript_path": parent,
            "agent_id": "a174ed04b87c4ecc1",
            "agent_transcript_path": os.path.join(
                self.reflect_state.name, "subagents", "agent-a174ed04b87c4ecc1.jsonl"
            ),
            "last_assistant_message": "Running the first 12-second sleep",
        })
        self.assertFalse(blocked)
        self.assertEqual(err, "")
        self.assertEqual(self.jobs(), [])

    def test_judge_not_enqueued_when_already_prompted(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        detect.mark_prompted(detect.reply_key(path, HIT_TEXT))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_judge_not_enqueued_when_user_already_asked_reflect(self):
        path = self.write_transcript(("user", REFLECT_COMMAND), ("assistant", HIT_TEXT))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_prose_about_reflect_does_not_count_as_asking_for_one(self):
        """A sentence naming the command is not an invocation of it.

        `"Claim I made was wrong" is a trigger for /reflect` describes when
        the hook fires. Treating that as a request let a sentence about the
        hook switch the hook off for the rest of the turn.
        """
        path = self.write_transcript(
            ("user", '"Claim I made was wrong" is a trigger for /reflect'),
            ("assistant", HIT_TEXT),
            name="prose-mention.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_the_later_correction_still_fires_after_the_reply_before_it(self):
        """Lockout one: the Stop of the pre-correction reply spent the key."""
        self.use_runners(SLOW_CLEAN)
        turn_one = (("user", "check the path"), ("assistant", "The live file is src/a.py."))
        path = self.write_transcript(*turn_one, name="turn.jsonl")
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.write_transcript(
            *turn_one,
            ("user", "are you sure?"),
            ("assistant", HIT_TEXT),
            name="turn.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_reflect_asked_earlier_in_the_session_does_not_silence_a_later_reply(self):
        """Lockout two: one /reflect used to switch the hook off for good."""
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(
            ("user", "please /reflect on the last hour"),
            ("assistant", "Here is the reflect write-up."),
            ("user", "now fix the import"),
            ("assistant", HIT_TEXT),
            name="long.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_reflect_asked_in_this_same_turn_is_still_not_doubled_up(self):
        path = self.write_transcript(
            ("user", "fix the import"),
            ("assistant", "Done."),
            ("user", "that was wrong. " + REFLECT_COMMAND),
            ("assistant", HIT_TEXT),
            name="same-turn.jsonl",
        )
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_the_same_reply_is_never_queued_twice(self):
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(("assistant", HIT_TEXT), name="dedup.jsonl")
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))

    def test_the_same_reply_is_judged_under_both_spellings_of_the_stop_event(self):
        """Harness parity: no branch may turn on the case of the event name."""
        self.use_runners(SLOW_CLEAN)
        queued = {}
        for spelling in ("Stop", "stop"):
            path = self.write_transcript(
                ("assistant", HIT_TEXT), name=f"parity-{spelling}.jsonl")
            queued[spelling] = detect.enqueue_judge(
                {"transcript_path": path, "hook_event_name": spelling})
        self.assertIsNotNone(queued["Stop"])
        self.assertIsNotNone(queued["stop"])

    def test_a_stop_hook_feedback_line_does_not_suppress_the_hook(self):
        """The ecosystem used to silence itself: diu-stop's own block says reflect."""
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(
            ("user", "fix the import"),
            ("meta", "Stop hook feedback: [diu-stop/claude_stop_check.py]: read the "
                     "reflect skill and say why"),
            ("assistant", HIT_TEXT),
            name="hook-feedback.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_the_reflect_skills_own_body_does_not_suppress_the_hook(self):
        """Running /reflect used to disarm the detector that asks for it."""
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(
            ("user", "fix the import"),
            ("meta", "Base directory for this skill: ~/.claude/skills/reflect\n# Reflect"),
            ("assistant", HIT_TEXT),
            name="skill-body.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_a_real_user_reflect_request_in_the_same_turn_still_suppresses(self):
        path = self.write_transcript(
            ("user", "fix the import"),
            ("assistant", "Done."),
            ("user", "that was wrong. " + REFLECT_COMMAND),
            ("meta", "Stop hook feedback: unrelated"),
            ("assistant", HIT_TEXT),
            name="real-request.jsonl",
        )
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_a_reflect_this_turn_counts_before_the_reply_row_is_written(self):
        """The Stop payload carries the reply; its transcript row is not there yet.

        Anchoring the window on the last assistant row made that row the
        PREVIOUS turn's reply, so the `/reflect` the person typed a moment
        ago sat past the window and the hook nagged for a reflect already
        in flight.
        """
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(
            ("user", "fix the import"),
            ("assistant", "Done."),
            ("user", "that was wrong. " + REFLECT_COMMAND),
            name="reply-row-not-written.jsonl",
        )
        self.assertIsNone(detect.enqueue_judge(
            {"transcript_path": path, "last_assistant_message": HIT_TEXT}))
        self.assertEqual(self.jobs(), [])

    def test_last_turns_reflect_does_not_silence_a_reply_still_being_written(self):
        """The same stale window, pointing the other way: a one-turn lockout."""
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(
            ("user", "that was wrong. " + REFLECT_COMMAND),
            ("assistant", "Here is the reflect write-up."),
            ("user", "now fix the import"),
            name="stale-window.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge(
            {"transcript_path": path, "last_assistant_message": HIT_TEXT}))

    def test_mid_turn_narration_does_not_push_the_window_past_the_request(self):
        """A turn writes many assistant rows: narration, then the reply.

        Starting the window after the previous assistant row cut the turn's
        own opening message out of it, so the `/reflect` in that message was
        never seen.
        """
        path = self.write_transcript(
            ("user", "that was wrong. " + REFLECT_COMMAND),
            ("assistant", "Let me open the file first."),
            ("assistant", HIT_TEXT),
            name="mid-turn-narration.jsonl",
        )
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_a_subagents_reply_row_does_not_hide_the_turns_request(self):
        """Sidechain rows land in the same file and used to move the window."""
        path = self.write_transcript(
            ("user", "that was wrong. " + REFLECT_COMMAND),
            ("assistant", "Spawning a subagent."),
            ("sidechain-user", "go read the file"),
            ("sidechain-assistant", "The live file is src/b.py."),
            ("assistant", HIT_TEXT),
            name="sidechain.jsonl",
        )
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_a_tool_result_row_does_not_push_the_window_past_the_request(self):
        """Claude Code files a tool result as a `type: "user"` row with no `isMeta`.

        Treating it as the person speaking made the turn's first tool call
        the start of the window, so the `/reflect` typed at the top of the
        turn sat before it and the hook nagged for a reflect already asked
        for.
        """
        path = self.write_transcript(
            ("user", "that was wrong. " + REFLECT_COMMAND),
            ("assistant", "Let me open the file first."),
            ("tool_result", "def parse_args(argv):\n    return argv[1]\n"),
            ("assistant", HIT_TEXT),
            name="tool-result.jsonl",
        )
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_a_second_stacked_command_does_not_hide_the_reflect_beside_it(self):
        """`/reflect /cat-mode text` is one submission, not two turns.

        The harness writes an envelope row per command and flags every row
        after the first `stackedExpansion`. Anchoring the turn on the last
        user-shaped row put the start on `/cat-mode`, so the `/reflect` the
        person typed in the same breath sat before the window and the hook
        nagged for a reflect already asked for.
        """
        path = self.write_transcript(
            ("user", REFLECT_COMMAND),
            ("meta", "Base directory for this skill: /skills/reflect\n\n# Reflect\n\nbody"),
            ("stacked", "<command-message>cat-mode</command-message>"
                        "<command-name>/cat-mode</command-name>"),
            ("meta", "Base directory for this skill: /skills/cat-mode\n\n# cat-mode\n\nbody"),
            ("assistant", HIT_TEXT),
            name="stacked-commands.jsonl",
        )
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_a_stacked_submission_without_reflect_still_lets_the_hook_fire(self):
        """Not anchoring on a stacked row must not mute the hook either.

        `/cat-mode /plan text` is the same one-submission shape with no
        reflect in it, so the correction after it still has to reach the
        judge.
        """
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(
            ("user", "<command-message>cat-mode</command-message>"
                     "<command-name>/cat-mode</command-name>"),
            ("meta", "Base directory for this skill: /skills/cat-mode\n\n# cat-mode\n\nbody"),
            ("stacked", "<command-message>plan</command-message>"
                        "<command-name>/plan</command-name>"),
            ("assistant", HIT_TEXT),
            name="stacked-no-reflect.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_a_typed_slash_command_row_is_the_person_not_harness_text(self):
        """`META_USER_PREFIXES` must never grow a `<command` entry.

        A typed `/reflect` arrives as a plain `type: "user"` row whose text
        opens with `<command-message>`. Filing that shape as harness text
        would re-arm the hook on the exact turn the person asked to skip.
        """
        row = {"type": "user", "message": {"role": "user", "content": REFLECT_COMMAND}}
        self.assertFalse(detect._is_meta_line(row))
        for prefix in detect.META_USER_PREFIXES:
            self.assertFalse(REFLECT_COMMAND.startswith(prefix), prefix)

    def test_a_tool_result_quoting_reflect_is_not_a_request_for_one(self):
        """Grepping the hook's own source prints the word; that is not an ask."""
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(
            ("user", "grep the hook"),
            ("assistant", "Running grep."),
            ("tool_result", "detect.py:31:ALREADY_REFLECT_RE = re.compile(r\"/reflect\")"),
            ("assistant", HIT_TEXT),
            name="tool-result-prose.jsonl",
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_unreadable_transcript_reports_unchecked_instead_of_going_quiet(self):
        missing = os.path.join(self.reflect_state.name, "does-not-exist.jsonl")
        self.assertFalse(detect.user_already_asked_reflect(missing))
        directory = os.path.join(self.reflect_state.name, "a-directory.jsonl")
        os.makedirs(directory, exist_ok=True)
        err = io.StringIO()
        with redirect_stderr(err):
            rows = detect._transcript_roles(directory)
        self.assertIsNone(rows)
        self.assertIn("unchecked", err.getvalue())

    def stage_rows(self):
        folder = os.path.join(self.state.name, "metrics")
        rows = []
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name.startswith("events-"):
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    rows.extend(json.loads(line) for line in handle)
        return [row for row in rows if row.get("mode_source") == "stage"]

    def test_every_skip_records_its_reason(self):
        path = self.write_transcript(("user", REFLECT_COMMAND), ("assistant", HIT_TEXT))
        detect.enqueue_judge({"transcript_path": path, "stop_hook_active": True}, "claude")
        detect.enqueue_judge({"transcript_path": path}, "claude")
        other = self.write_transcript(("assistant", HIT_TEXT), name="other.jsonl")
        detect.mark_prompted(detect.reply_key(other, HIT_TEXT))
        detect.enqueue_judge({"transcript_path": other}, "cursor")
        with patch.dict(os.environ, {flags.REFLECT_ENFORCEMENT: "0"}):
            detect.enqueue_judge({"transcript_path": other}, "codex")
        detect.enqueue_judge({"last_assistant_message": "   "}, "claude")
        self.assertEqual(
            [(r["action"], r["reason"], r["harness"]) for r in self.stage_rows()],
            [
                ("judge_skipped", "stop_hook_active", "claude"),
                ("judge_skipped", "user_asked_reflect", "claude"),
                ("judge_skipped", "already_prompted", "cursor"),
                ("judge_skipped", "gate_off", "codex"),
                ("judge_skipped", "empty_reply", "claude"),
            ],
        )
        self.assertEqual(self.jobs(), [])

    def test_claude_stop_records_the_queued_job_under_the_claude_harness(self):
        self.use_runners(SLOW_CLEAN)
        path = self.write_transcript(("assistant", HIT_TEXT))
        run_claude({"transcript_path": path, "session_id": "s-1"})
        queued = [r for r in self.stage_rows() if r["action"] == "judge_queued"]
        self.assertEqual([(r["hook"], r["harness"], r["reason"]) for r in queued],
                         [("wrong-check-reflect", "claude", "transcript")])
        self.assertEqual(queued[0]["finding_id"], self.wait_for_jobs(1)[0][: -len(".json")])

    def test_real_codex_notify_queues_against_its_rollout_file(self):
        self.use_runners(SLOW_CLEAN)
        thread = "01a0ce9a-301b-7d42-bb5c-b9a9a4cfe8c6"
        day = os.path.join(self.reflect_state.name, "codex-sessions", "2026", "09", "23")
        os.makedirs(day)
        rollout = os.path.join(day, f"rollout-2026-09-23T22-10-06-{thread}.jsonl")
        with open(rollout, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        payload = {"type": "agent-turn-complete", "thread-id": thread, "turn-id": "t", "cwd": "/",
                   "client": "codex_exec", "input-messages": ["hi"], "last-assistant-message": HIT_TEXT}
        with patch.dict(os.environ, {"CATSTACK_CODEX_SESSIONS_DIR": os.path.dirname(os.path.dirname(os.path.dirname(day)))}):
            err = run_codex_notify([json.dumps(payload)])
        self.assertEqual(err, "")
        [job] = self.wait_for_jobs(1)
        with open(os.path.join(self.state.name, "jobs", job), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["transcript"], rollout)
        queued = [r for r in self.stage_rows() if r["action"] == "judge_queued"]
        self.assertEqual([(r["harness"], r["reason"]) for r in queued], [("codex", "transcript")])

    def test_claude_malformed_stdin_fail_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not-json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_cursor_returns_empty_followup(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        body, err = run_cursor({"transcript_path": path})
        self.assertEqual(body, {"followup_message": ""})
        self.assertEqual(err, "")

    def test_codex_still_chains(self):
        chain = os.path.join(self.reflect_state.name, "chain.sh")
        marker = os.path.join(self.reflect_state.name, "chained")
        with open(chain, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\necho ok > {marker}\n")
        os.chmod(chain, 0o755)
        payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": HIT_TEXT})
        run_codex_notify([chain, payload])
        self.assertTrue(os.path.isfile(marker))

    def test_judge_enqueue_failure_leaves_reply_untouched(self):
        payload = {"last_assistant_message": HIT_TEXT, "type": "agent-turn-complete", "last-assistant-message": HIT_TEXT}
        with patch.object(detect, "enqueue_judge", side_effect=RuntimeError("boom")):
            blocked, err = run_claude(payload)
            body, cursor_err = run_cursor(payload)
            codex_err = run_codex_notify([json.dumps(payload)])
        self.assertFalse(blocked)
        self.assertEqual(err, "catstack-hook-error wrong-check-reflect: RuntimeError: boom\n")
        self.assertEqual(body, {"followup_message": ""})
        self.assertEqual(cursor_err, "catstack-hook-error wrong-check-reflect: RuntimeError: boom\n")
        self.assertEqual(codex_err, "catstack-hook-error wrong-check-reflect: RuntimeError: boom\n")


class TestSubagentTranscript(unittest.TestCase):
    def test_resolve_transcript_prefers_agent_transcript_path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        parent = os.path.join(tmp.name, "session.jsonl")
        agent = os.path.join(tmp.name, "agent-a0231adb57400d820.jsonl")
        for path in (parent, agent):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("")
        self.assertEqual(
            detect.resolve_transcript({"transcript_path": parent, "agent_transcript_path": agent}),
            agent,
        )
        self.assertEqual(detect.resolve_transcript({"transcript_path": parent}), parent)

    def test_missing_agent_transcript_does_not_fall_back_to_the_parent(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        parent = os.path.join(tmp.name, "session.jsonl")
        with open(parent, "w", encoding="utf-8") as handle:
            handle.write("")
        gone = os.path.join(tmp.name, "agent-gone.jsonl")
        self.assertEqual(
            detect.resolve_transcript({"transcript_path": parent, "agent_transcript_path": gone}),
            "",
        )


class TestCodexInstaller(unittest.TestCase):
    def test_compute_notify_update_prepends(self):
        from install_codex_notify import compute_notify_update

        text = 'notify = ["python3", "/home/x/.codex/hooks/diu-stop/codex_notify.py"]\n'
        new_text, changed, _ = compute_notify_update(
            text, "/home/x/.codex/hooks/wrong-check-reflect/codex_notify.py"
        )
        self.assertTrue(changed)
        self.assertIn("wrong-check-reflect/codex_notify.py", new_text)
        self.assertIn("diu-stop/codex_notify.py", new_text)
        self.assertLess(
            new_text.index("wrong-check-reflect"),
            new_text.index("diu-stop"),
        )


if __name__ == "__main__":
    unittest.main()
