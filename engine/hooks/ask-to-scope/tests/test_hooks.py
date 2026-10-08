#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402
import install_claude_hook  # noqa: E402

sys.path.append(detect.judge_channel.LLM_JUDGE_DIR)
import phrases  # noqa: E402
import registry  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable
HOOKS_TOML = os.path.join(os.path.dirname(HOOK_DIR), "hooks.toml")
FAKE_RUNNER = (
    "import json, os, sys\n"
    "text = sys.argv[1].rsplit('TEXT:', 1)[1].strip()\n"
    "last = text.splitlines()[-1].strip()\n"
    "ambiguous = {'open the file in gitlab for me', 'open it for me again', 'can you show me the logs?'}\n"
    "mode = os.environ.get('FAKE_AMBIGUOUS', 'by-message')\n"
    "if mode == 'by-message':\n"
    "    print(json.dumps({'match': last in ambiguous}))\n"
    "else:\n"
    "    print(json.dumps({'match': mode == 'true'}))\n"
)
FAKE = ["fake", [PY, "-c", FAKE_RUNNER, "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]
SLOW = ["slow", [PY, "-c", "import time; time.sleep(30)", "{prompt}"]]

GITLAB_URL = "https://gitlab.example.com/group/project/-/blob/main/ci/dependency-maps.gitlab-ci.yml"
OTHER_URL = "https://gitlab.example.com/group/project/-/blob/main/ci/build.gitlab-ci.yml"
JOB_URL = "https://gitlab.example.com/group/project/-/jobs/1234567"
NAVIGATE = "mcp__Claude_Browser__navigate"


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def say(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def use(use_id, name, tool_input):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": name, "input": tool_input}]}}


def result(use_id, text="ok"):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": use_id, "content": text}]}}


EARLIER = [
    user("why is the dependency map job red?"),
    say(f"The job at {JOB_URL} failed. The config is {GITLAB_URL} and a sibling is {OTHER_URL}. "
        "See also `dependency-maps.gitlab-ci.yml` and ci/other-maps.gitlab-ci.yml."),
]


class ScopeTestCase(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        os.environ[detect.STATE_ENV] = os.path.join(self.tmp.name, "scope-state")
        self.use_runners(FAKE)
        os.environ.pop("FAKE_AMBIGUOUS", None)

    def tearDown(self):
        for key in (detect.STATE_ENV, "FAKE_AMBIGUOUS", "CATSTACK_HOOK_MODE_ASK_TO_SCOPE"):
            os.environ.pop(key, None)
        self.tmp.cleanup()
        super().tearDown()

    def transcript(self, rows, name="t.jsonl"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def event(self, path, tool_name, tool_input, use_id="cur"):
        return {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_use_id": use_id,
                "transcript_path": path, "tool_input": tool_input}

    def navigate(self, path, url=GITLAB_URL):
        return self.event(path, NAVIGATE, {"url": url})

    def judge(self, event, wait=15):
        return detect.evaluate(event, wait=wait)


class AmbiguousAskBlocksTests(ScopeTestCase):
    def test_blocks_open_the_file_in_gitlab_after_several_files_were_cited(self):
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        outcome, message = self.judge(self.navigate(path))
        self.assertEqual(outcome, "block")
        self.assertIn(GITLAB_URL, message)
        self.assertIn(OTHER_URL, message)
        self.assertIn("dependency-maps.gitlab-ci.yml", message)
        self.assertIn("ask which one they mean", message)
        self.assertIn("not whether you may", message)

    def test_blocks_open_it_again_after_an_artifact_and_a_job_page(self):
        artifact = "https://gitlab.example.com/group/project/-/jobs/1234567/artifacts/browse"
        path = self.transcript([user("build it"), say(f"Artifacts are at {artifact} and the job page is {JOB_URL}."),
                                user("open it for me again")])
        outcome, message = self.judge(self.navigate(path, JOB_URL))
        self.assertEqual(outcome, "block")
        self.assertIn(artifact, message)
        self.assertIn(JOB_URL, message)

    def test_blocks_show_me_the_logs_when_nothing_names_a_log(self):
        path = self.transcript([user("build it"), say("Job 1234567 failed and job 1234568 passed."), user("can you show me the logs?")])
        outcome, message = self.judge(self.event(path, "Bash", {"command": "glab ci trace 1234567"}))
        self.assertEqual(outcome, "block")
        self.assertIn("1234567", message)
        self.assertIn("1234568", message)

    def test_blocks_an_edit_and_a_subagent_launch_too(self):
        edit = self.transcript([*EARLIER, user("open the file in gitlab for me")], "edit.jsonl")
        self.assertEqual(self.judge(self.event(edit, "Edit", {"file_path": "/repo/a.yml", "old_string": "a", "new_string": "b"}))[0], "block")
        launch = self.transcript([*EARLIER, user("open the file in gitlab for me")], "launch.jsonl")
        self.assertEqual(self.judge(self.event(launch, "Agent", {"prompt": "go find it", "description": "d"}))[0], "block")

    def test_only_the_last_two_turns_are_listed_as_candidates(self):
        old = "https://example.invalid/old-page"
        path = self.transcript([user("one"), say(f"see {old}"), user("two"), say(f"see {GITLAB_URL}"),
                                user("three"), say(f"see {JOB_URL}"), user("open the file in gitlab for me")])
        _, message = self.judge(self.navigate(path))
        self.assertNotIn(old, message)
        self.assertIn(GITLAB_URL, message)
        self.assertIn(JOB_URL, message)

    def test_hook_script_blocks_with_exit_2_and_names_candidates(self):
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        env = dict(os.environ, CATSTACK_HOOK_MODE_ASK_TO_SCOPE="stop", ASK_TO_SCOPE_WAIT_SECONDS="15")
        proc = subprocess.run([PY, os.path.join(HOOK_DIR, "claude_pretooluse.py")],
                              input=json.dumps(self.navigate(path)), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("ask-to-scope", proc.stderr)
        self.assertIn(OTHER_URL, proc.stderr)


class OncePerMessageTests(ScopeTestCase):
    def test_second_call_in_the_same_turn_passes_after_the_block(self):
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        self.assertEqual(self.judge(self.navigate(path))[0], "block")
        self.assertEqual(self.judge(self.navigate(path))[0], "allow")

    def test_second_call_passes_once_the_assistant_asked_with_the_ask_tool(self):
        rows = [*EARLIER, user("open the file in gitlab for me")]
        path = self.transcript(rows)
        self.assertEqual(self.judge(self.navigate(path))[0], "block")
        path = self.transcript([*rows, use("q1", "AskUserQuestion", {"questions": []}), result("q1")])
        self.assertEqual(self.judge(self.navigate(path))[0], "allow")

    def test_second_call_passes_once_the_assistant_asked_in_text(self):
        path = self.transcript([*EARLIER, user("open the file in gitlab for me"),
                                say("Which one do you mean, the config or the sibling?")])
        self.assertEqual(self.judge(self.navigate(path))[0], "allow")

    def test_a_new_user_message_clears_the_block(self):
        rows = [*EARLIER, user("open the file in gitlab for me")]
        self.assertEqual(self.judge(self.navigate(self.transcript(rows)))[0], "block")
        rows += [say("Which one?"), user("open it for me again")]
        self.assertEqual(self.judge(self.navigate(self.transcript(rows)))[0], "block")

    def test_a_url_in_a_question_mark_does_not_count_as_asking(self):
        path = self.transcript([*EARLIER, user("open the file in gitlab for me"), say(f"Opening {JOB_URL}?x=1 now.")])
        self.assertEqual(self.judge(self.navigate(path))[0], "block")


class SilentTests(ScopeTestCase):
    def test_message_with_the_exact_url_is_silent_without_asking_the_judge(self):
        self.use_runners(MISSING)
        path = self.transcript([*EARLIER, user(f"open {GITLAB_URL} for me")])
        self.assertEqual(self.judge(self.navigate(path), wait=1), ("allow", ""))

    def test_message_with_the_exact_file_name_is_silent_for_an_edit(self):
        self.use_runners(MISSING)
        path = self.transcript([*EARLIER, user("fix the typo in dependency-maps.gitlab-ci.yml")])
        event = self.event(path, "Edit", {"file_path": "/repo/ci/dependency-maps.gitlab-ci.yml"})
        self.assertEqual(self.judge(event, wait=1), ("allow", ""))

    def test_show_line_980_of_a_named_file_is_not_ambiguous(self):
        path = self.transcript([*EARLIER, user("show line 980 of dependency-maps.gitlab-ci.yml")])
        self.assertEqual(self.judge(self.navigate(path, GITLAB_URL + "#L980")), ("allow", ""))

    def test_run_the_tests_is_not_ambiguous(self):
        path = self.transcript([*EARLIER, user("run the tests")])
        self.assertEqual(self.judge(self.event(path, "Bash", {"command": "python3 -m pytest -q"})), ("allow", ""))

    def test_read_only_tools_are_never_blocked_or_judged(self):
        self.use_runners(MISSING)
        os.environ["FAKE_AMBIGUOUS"] = "true"
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        for name, tool_input in (
            ("Read", {"file_path": "/repo/a.yml"}),
            ("Grep", {"pattern": "x"}),
            ("Glob", {"pattern": "**/*.yml"}),
            ("AskUserQuestion", {"questions": []}),
            ("WebFetch", {"url": GITLAB_URL}),
        ):
            with self.subTest(tool=name):
                self.assertEqual(self.judge(self.event(path, name, tool_input), wait=1), ("allow", ""))

    def test_read_only_shell_commands_are_never_blocked_or_judged(self):
        self.use_runners(MISSING)
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        for command in ("git status", "ls -la ci", "grep -rn depends ci 2>/dev/null", "sed -n 980p ci/dependency-maps.gitlab-ci.yml",
                        "cd /repo && git log --oneline | head -5", "find . -name '*.yml'"):
            with self.subTest(command=command):
                self.assertEqual(self.judge(self.event(path, "Bash", {"command": command}), wait=1), ("allow", ""))

    def test_a_judge_that_says_clear_allows_and_is_cached(self):
        path = self.transcript([*EARLIER, user("run the tests")])
        event = self.event(path, "Bash", {"command": "make test"})
        self.assertEqual(self.judge(event)[0], "allow")
        self.use_runners(MISSING)
        self.assertEqual(self.judge(event, wait=0)[0], "allow")

    def test_a_relayed_machine_turn_as_the_latest_message_is_silent(self):
        os.environ["FAKE_AMBIGUOUS"] = "true"
        path = self.transcript([*EARLIER, user("open the file in gitlab for me"),
                                user("<task-notification>agent a1 finished</task-notification>")])
        self.assertEqual(self.judge(self.navigate(path)), ("allow", ""))

    def test_a_subagent_call_is_silent(self):
        os.environ["FAKE_AMBIGUOUS"] = "true"
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        event = self.navigate(path)
        event["agent_id"] = "sub-1"
        self.assertEqual(self.judge(event), ("allow", ""))

    def test_a_transcript_with_no_user_message_is_silent(self):
        os.environ["FAKE_AMBIGUOUS"] = "true"
        path = self.transcript([say("hello")])
        self.assertEqual(self.judge(self.navigate(path)), ("allow", ""))

    def test_mode_off_prints_nothing_and_exits_0(self):
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        env = dict(os.environ, CATSTACK_HOOK_MODE_ASK_TO_SCOPE="off", ASK_TO_SCOPE_WAIT_SECONDS="15")
        proc = subprocess.run([PY, os.path.join(HOOK_DIR, "claude_pretooluse.py")],
                              input=json.dumps(self.navigate(path)), capture_output=True, text=True, env=env)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        self.assertNotIn("Candidates", proc.stderr)


class UncheckedInputTests(ScopeTestCase):
    def test_unreadable_transcript_fails_open_with_unchecked(self):
        event = self.navigate(os.path.join(self.tmp.name, "missing.jsonl"))
        outcome, message = self.judge(event, wait=1)
        self.assertEqual(outcome, "unchecked")
        self.assertIn("UNCHECKED", message)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(detect.detect(event), [])
        self.assertIn("UNCHECKED", err.getvalue())
        self.assertEqual(len(event["_catstack_unchecked_findings"]), 1)

    def test_no_transcript_path_fails_open_with_unchecked(self):
        event = self.navigate("")
        event.pop("transcript_path")
        self.assertEqual(self.judge(event, wait=1)[0], "unchecked")

    def test_judge_unavailable_fails_open_with_unchecked_and_prints_the_line(self):
        self.use_runners(MISSING)
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        outcome, message = self.judge(self.navigate(path))
        self.assertEqual(outcome, "unchecked")
        self.assertIn("UNCHECKED", message)
        env = dict(os.environ, CATSTACK_HOOK_MODE_ASK_TO_SCOPE="stop", ASK_TO_SCOPE_WAIT_SECONDS="15")
        proc = subprocess.run([PY, os.path.join(HOOK_DIR, "claude_pretooluse.py")],
                              input=json.dumps(self.navigate(path)), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ask-to-scope: UNCHECKED", proc.stderr)

    def test_verdict_that_never_arrives_fails_open_with_unchecked(self):
        self.use_runners(SLOW)
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        outcome, message = self.judge(self.navigate(path), wait=1)
        self.assertEqual(outcome, "unchecked")
        self.assertIn("no verdict within", message)

    def test_garbage_transcript_lines_are_skipped_and_logged(self):
        path = os.path.join(self.tmp.name, "garbage.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json\n" + json.dumps(user("open the file in gitlab for me")) + "\n")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(self.judge(self.navigate(path))[0], "block")
        self.assertIn("skipped 1 unparseable", err.getvalue())

    def test_malformed_state_file_is_treated_empty_and_logged(self):
        path = self.transcript([*EARLIER, user("open the file in gitlab for me")])
        cache = detect.state_path(path)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(self.judge(self.navigate(path))[0], "block")
        self.assertIn("unreadable verdict cache", err.getvalue())


class ShellParsingTests(unittest.TestCase):
    def test_read_only_commands(self):
        for command in ("ls", "cat a.txt | head -3", "git diff HEAD~1", "git -C /repo status", "cd x && ls && pwd",
                        "grep -rn foo . 2>&1", "echo hi", "sed -n '1,5p' f"):
            with self.subTest(command=command):
                self.assertTrue(detect.is_read_only_command(command))

    def test_commands_that_write_open_or_run_things_are_gated(self):
        for command in ("open https://example.test", "git push", "git commit -m x", "sed -i s/a/b/ f", "find . -delete",
                        "find . -exec rm {} +", "cat a > b", "echo $(whoami)", "python3 run.py", "FOO=1 ls", "tee out",
                        "ls && rm -rf x", "cat `ls`", "xdg-open page.html"):
            with self.subTest(command=command):
                self.assertFalse(detect.is_read_only_command(command))

    def test_unparseable_command_is_gated_and_logged(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertFalse(detect.is_read_only_command("echo 'unterminated"))
        self.assertIn("could not parse the shell command", err.getvalue())


class ExtractionTests(unittest.TestCase):
    def test_extracts_urls_paths_ticked_files_and_ci_refs_in_order(self):
        text = f"see `build.yml`, engine/hooks/a.py, {JOB_URL}. Also /Users/x/a/b.txt and job 1234567"
        self.assertEqual(detect.extract_references(text),
                         ["build.yml", "engine/hooks/a.py", JOB_URL, "/Users/x/a/b.txt", "job 1234567"])

    def test_prose_with_slashes_is_not_a_path(self):
        self.assertEqual(detect.extract_references("use and/or, either/or, 1/2 and e.g. this"), [])

    def test_asks_a_question_ignores_code_and_urls(self):
        self.assertTrue(detect.asks_a_question("Done.\nWhich one do you mean?"))
        self.assertFalse(detect.asks_a_question("Opening https://x.test/a?b=1 now."))
        self.assertFalse(detect.asks_a_question("```\nwhy?\n```\nDone."))
        self.assertFalse(detect.asks_a_question("Run `what?` then stop."))

    def test_prompt_names_a_path_by_full_path_or_exact_file_name_only(self):
        self.assertTrue(detect.prompt_names("/repo/ci/a.yml", "edit ci/a.yml please"))
        self.assertTrue(detect.prompt_names("/repo/ci/a.yml", "edit `a.yml`"))
        self.assertFalse(detect.prompt_names("/repo/ci/a.yml", "edit the yml"))
        self.assertFalse(detect.prompt_names("/repo/ci/a.yml", "edit data.yml"))
        self.assertFalse(detect.prompt_names("https://x.test/a.yml", "open a.yml"))


class DictionaryRegistryAndInstallTests(unittest.TestCase):
    def test_dictionary_loads_and_reads_the_exchange(self):
        dictionary = phrases.load(detect.CHECKER)
        self.assertEqual(dictionary["reads"], "exchange")
        joined = " ".join(dictionary["on_hit"].split())
        self.assertIn("Do not ask for permission", joined)

    def test_registry_enrolls_the_hook_in_stop_mode(self):
        hooks, _ = registry.load_registry(HOOKS_TOML)
        self.assertEqual(hooks[detect.HOOK].mode, "stop")

    def test_matcher_covers_every_gated_tool_and_no_read_tool(self):
        with open(install_claude_hook.FRAGMENT_PATH) as handle:
            matcher = json.load(handle)["hooks"]["PreToolUse"][0]["matcher"]
        import re
        for name in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "Agent", "Task", NAVIGATE,
                     "mcp__claude-in-chrome__navigate"):
            with self.subTest(tool=name):
                self.assertTrue(re.fullmatch(matcher, name), name)
        for name in ("Read", "Grep", "Glob", "AskUserQuestion", "mcp__Claude_Browser__read_page"):
            with self.subTest(tool=name):
                self.assertFalse(re.fullmatch(matcher, name), name)

    def test_install_merge_is_idempotent_and_keeps_other_entries(self):
        with open(install_claude_hook.FRAGMENT_PATH) as handle:
            fragment = json.load(handle)
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "other.py"}]}
        settings, changed = install_claude_hook.merge_hook({"hooks": {"PreToolUse": [other]}}, fragment)
        self.assertTrue(changed)
        again, changed_again = install_claude_hook.merge_hook(settings, fragment)
        self.assertFalse(changed_again)
        self.assertEqual(len(again["hooks"]["PreToolUse"]), 2)


if __name__ == "__main__":
    unittest.main()
