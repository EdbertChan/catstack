"""End-to-end tests for gh-write-verification's three detectors.

Each detector gets a case that fires and a case that stays quiet, plus the
entrypoints exercised as real subprocesses so the exit-2 contract is proven,
not assumed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
CATSTACK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(CATSTACK_ROOT, "scripts"))

from git_test_repo import init_repo  # noqa: E402
from detect import (  # noqa: E402
    TRUST_PR_EDIT_ENV,
    broken_pr_edit,
    decide_stop,
    merges_missing_landing_proof,
    pretooluse_problems,
    self_matching_process_waits,
    silenced_mutations,
)

PRETOOLUSE = os.path.join(HOOK_DIR, "claude_pretooluse.py")
STOP_CHECK = os.path.join(HOOK_DIR, "claude_stop_check.py")

INCIDENT_RETARGET = 'gh pr edit "$1" --base main >/dev/null 2>&1'
LOOP_HEAD = "until"
NAP = "sleep"
INCIDENT_WAIT = f"{LOOP_HEAD} ! pgrep -f run_all_tests.sh >/dev/null; do {NAP} 10; done"


def run_entrypoint(entrypoint: str, payload: dict, env_extra: dict | None = None):
    env = dict(os.environ)
    env.pop(TRUST_PR_EDIT_ENV, None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, entrypoint],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


def bash_payload(command: str) -> dict:
    return {"tool_name": "Bash", "cwd": HOOK_DIR, "tool_input": {"command": command}}


def transcript(commands: list[str]) -> str:
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "land the stack"}})]
    for command in commands:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ]},
        }))
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    handle.write("\n".join(lines) + "\n")
    handle.close()
    return handle.name


class TestBrokenPrEdit(unittest.TestCase):
    def test_every_flag_of_gh_pr_edit_is_blocked(self):
        for command in (
            "gh pr edit 295 --base main",
            "gh pr edit 295 --add-label admin-bypass",
            "gh pr edit 295 --title 'x'",
            "gh pr edit 295 --body-file /tmp/body.md",
        ):
            self.assertIsNotNone(broken_pr_edit(command), command)

    def test_block_message_names_the_gh_api_replacements(self):
        result = run_entrypoint(PRETOOLUSE, bash_payload("gh pr edit 295 --base main"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("gh api -X PATCH repos/<owner>/<repo>/pulls/<n>", result.stderr)
        self.assertIn("gh api -X POST repos/<owner>/<repo>/issues/<n>/labels", result.stderr)

    def test_the_sanctioned_gh_api_replacement_is_allowed(self):
        for command in (
            "gh api -X PATCH repos/EdbertChan/catstack/pulls/295 -f base=main",
            "gh api repos/EdbertChan/catstack/pulls/295 --jq .base.ref",
            "gh pr view 295 --json baseRefName",
        ):
            self.assertEqual(pretooluse_problems(command), [], command)

    def test_trust_env_lets_gh_pr_edit_through(self):
        result = run_entrypoint(
            PRETOOLUSE,
            bash_payload("gh pr edit 295 --base main"),
            {TRUST_PR_EDIT_ENV: "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class TestSilencedMutation(unittest.TestCase):
    def test_the_incident_line_is_flagged(self):
        self.assertEqual(silenced_mutations(INCIDENT_RETARGET), [INCIDENT_RETARGET])

    def test_mutations_with_both_streams_discarded_are_flagged(self):
        for command in (
            "git push origin HEAD >/dev/null 2>&1",
            "gh pr merge 291 --squash &>/dev/null",
            "gh api -X POST repos/o/r/issues/1/labels -f 'labels[]=x' > /dev/null 2>/dev/null",
            "git merge origin/main 2>/dev/null >/dev/null",
            "curl -X DELETE https://example.test/thing >/dev/null 2>&1",
        ):
            self.assertTrue(silenced_mutations(command), command)

    def test_read_only_commands_with_discarded_output_stay_silent(self):
        for command in (
            "grep -q needle haystack.txt 2>/dev/null",
            "command -v shellcheck >/dev/null 2>&1",
            "git cat-file -e abc123^{commit} 2>/dev/null",
            "git status --porcelain >/dev/null 2>&1",
            "gh pr view 295 --json state >/dev/null 2>&1",
            "pgrep -f run_all_tests >/dev/null 2>&1",
            "diff -q a b >/dev/null 2>&1",
        ):
            self.assertEqual(silenced_mutations(command), [], command)

    def test_a_checked_exit_code_stays_silent(self):
        for command in (
            "git push origin HEAD >/dev/null 2>&1 || exit 1",
            "if ! git push origin HEAD >/dev/null 2>&1; then echo failed; fi",
            "git push origin HEAD >/dev/null 2>&1 && echo pushed",
            "set -euo pipefail\ngit push origin HEAD >/dev/null 2>&1",
        ):
            self.assertEqual(silenced_mutations(command), [], command)

    def test_one_stream_left_visible_stays_silent(self):
        for command in (
            "git push origin HEAD >/dev/null",
            "git push origin HEAD 2>/dev/null",
            "git push origin HEAD 2>&1 >/dev/null",
        ):
            self.assertEqual(silenced_mutations(command), [], command)

    def test_a_redirect_belonging_to_an_earlier_command_stays_silent(self):
        command = "grep -q main .git/HEAD 2>/dev/null && git push origin HEAD"
        self.assertEqual(silenced_mutations(command), [])

    def test_a_file_write_mentioning_the_shape_is_allowed(self):
        payload = {
            "tool_name": "Write",
            "cwd": HOOK_DIR,
            "tool_input": {"file_path": "/tmp/notes.md", "content": INCIDENT_RETARGET},
        }
        result = run_entrypoint(PRETOOLUSE, payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_heredoc_written_script_is_flagged(self):
        command = "cat > retarget.sh <<'EOS'\ngh pr merge 291 --squash >/dev/null 2>&1\nEOS"
        self.assertTrue(silenced_mutations(command))

    def test_entrypoint_denies_a_discarded_mutation(self):
        result = run_entrypoint(PRETOOLUSE, bash_payload("git push origin HEAD >/dev/null 2>&1"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("discards both stdout and stderr", result.stderr)


class TestSelfMatchingProcessWait(unittest.TestCase):
    def test_the_incident_wait_loop_is_flagged(self):
        self.assertEqual(self_matching_process_waits(INCIDENT_WAIT), ["pgrep -f run_all_tests.sh"])

    def test_a_pattern_occurring_only_once_is_still_flagged(self):
        self.assertTrue(self_matching_process_waits("pgrep -f wwww_once_only_ghwv"))

    def test_a_one_shot_status_check_is_flagged_because_the_wrapper_carries_the_pattern(self):
        """`pgrep -f postgres` looks like a legitimate "is it running?" check and is not.

        The harness runs each tool call as `bash -c '<the whole command>'`, so
        the pattern is already in a live process cmdline: the search returns the
        wrapper and exits 0 for a service running nowhere. Verified against a
        token present on no process. Do not relax this to silent -- the one-shot
        answer is wrong too, just less loudly than a loop that never exits.
        """
        self.assertEqual(self_matching_process_waits("pgrep -f postgres"), ["pgrep -f postgres"])
        self.assertTrue(self_matching_process_waits("if pgrep -f nginx; then echo up; fi"))

    def test_destructive_pkill_is_flagged(self):
        self.assertEqual(self_matching_process_waits("pkill -f run_all_tests.sh"), ["pkill -f run_all_tests.sh"])

    def test_full_match_spellings_are_all_flagged(self):
        for command in (
            "pgrep -af my_worker.py >/dev/null 2>&1",
            "pgrep --full my_worker.py",
            "pgrep -f -u edbert my_worker.py",
        ):
            self.assertTrue(self_matching_process_waits(command), command)

    def test_a_bracket_class_undone_by_a_plain_mention_is_flagged(self):
        command = "pgrep -f '[r]un_all_tests.sh' ; echo run_all_tests.sh"
        self.assertTrue(self_matching_process_waits(command))

    def test_the_bracket_trick_alone_stays_silent(self):
        self.assertEqual(self_matching_process_waits("pgrep -f '[r]un_all_tests' >/dev/null"), [])

    def test_a_log_sentinel_wait_stays_silent(self):
        command = f"{LOOP_HEAD} grep -q '^EXIT=' out.log; do {NAP} 10; done"
        self.assertEqual(self_matching_process_waits(command), [])

    def test_a_name_match_without_full_stays_silent(self):
        for command in ("pgrep run_all_tests.sh", "pgrep -x bash", "pkill -x node"):
            self.assertEqual(self_matching_process_waits(command), [], command)

    def test_a_captured_pid_or_variable_pattern_stays_silent(self):
        for command in ('kill -0 "$PID" 2>/dev/null', 'pgrep -f "$PATTERN"', "pgrep -f `cat p`"):
            self.assertEqual(self_matching_process_waits(command), [], command)

    def test_entrypoint_denies_the_incident_wait_loop(self):
        result = run_entrypoint(PRETOOLUSE, bash_payload(INCIDENT_WAIT))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("matches the shell asking the question", result.stderr)
        self.assertIn("kill -0", result.stderr)


class TestUnverifiedLanding(unittest.TestCase):
    def test_a_merge_with_no_landing_check_is_flagged(self):
        self.assertEqual(
            merges_missing_landing_proof(["gh pr merge 291 --squash --admin", "gh pr view 291"]),
            ["PR #291"],
        )

    def test_every_unproven_merge_in_the_turn_is_flagged(self):
        commands = [
            "gh pr merge 291 --squash",
            "gh pr merge 292 --squash",
            "bash verify_pr_landed_on_trunk.sh 292",
        ]
        self.assertEqual(merges_missing_landing_proof(commands), ["PR #291"])

    def test_a_verified_landing_stays_silent(self):
        for proof in (
            "bash verify_pr_landed_on_trunk.sh 291",
            "bash verify_pr_landed_on_trunk.sh --repo acme/widgets 291",
            "bash verify_pr_landed_on_trunk.sh https://github.com/acme/widgets/pull/291",
            "git merge-base --is-ancestor 314f0447 origin/main",
            "git branch -r --contains 314f0447",
        ):
            self.assertEqual(
                merges_missing_landing_proof(["gh pr merge 291 --squash", proof]), [], proof
            )

    def test_a_turn_with_no_merge_stays_silent(self):
        self.assertEqual(merges_missing_landing_proof(["git status", "gh pr view 291"]), [])

    def test_stop_entrypoint_denies_an_unproven_merge(self):
        path = transcript(["gh pr merge 291 --squash --admin"])
        try:
            result = run_entrypoint(STOP_CHECK, {"transcript_path": path})
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("verify_pr_landed_on_trunk.sh", result.stderr)
            self.assertIn("--repo <owner/name> <pr-number>", result.stderr)
            self.assertIn("PR #291", result.stderr)
        finally:
            os.unlink(path)

    def test_stop_entrypoint_allows_a_proven_merge(self):
        path = transcript([
            "gh pr merge 291 --squash --admin",
            'bash "$HOME/.claude/hooks/gh-write-verification/verify_pr_landed_on_trunk.sh" 291',
        ])
        try:
            result = run_entrypoint(STOP_CHECK, {"transcript_path": path})
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            os.unlink(path)

    def test_a_missing_transcript_fails_open(self):
        self.assertIsNone(decide_stop({"transcript_path": "/nonexistent/transcript.jsonl"}))
        self.assertIsNone(decide_stop({}))

    def test_a_malformed_transcript_line_is_ignored(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        handle.write("not json at all\n{\n")
        handle.close()
        try:
            self.assertIsNone(decide_stop({"transcript_path": handle.name}))
        finally:
            os.unlink(handle.name)

    def test_stop_hook_active_stays_silent(self):
        path = transcript(["gh pr merge 291 --squash --admin"])
        try:
            self.assertIsNone(decide_stop({"transcript_path": path, "stop_hook_active": True}))
        finally:
            os.unlink(path)


VERIFY_SCRIPT = os.path.join(HOOK_DIR, "verify_pr_landed_on_trunk.sh")
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_UNCHECKED = 3
EXIT_USAGE = 64

FAKE_GH = """#!{python}
import json, os, sys
with open(os.environ["FAKE_GH_STATE"], encoding="utf-8") as handle:
    state = json.load(handle)
args = sys.argv[1:]
if args[:2] == ["repo", "view"]:
    if not state.get("default_repo"):
        sys.stderr.write("no git remotes found\\n")
        sys.exit(1)
    print(state["default_repo"])
    sys.exit(0)
if args[:1] == ["api"]:
    pull = state.get("pulls", {{}}).get(args[1])
    if pull is None:
        sys.stderr.write("HTTP 404: Not Found\\n")
        sys.exit(1)
    print("\\t".join([pull["merged"], pull["base"], pull["sha"] or "none"]))
    sys.exit(0)
sys.stderr.write("fake gh: unhandled " + " ".join(args) + "\\n")
sys.exit(1)
"""


def pull(merged: bool, base: str, sha: str | None) -> dict:
    return {"merged": "true" if merged else "false", "base": base, "sha": sha}


class TestVerificationScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ghwv-verify-")
        cls.git_config = os.path.join(cls.root, "gitconfig")
        open(cls.git_config, "w").close()
        cls.env = dict(os.environ)
        cls.env.update({
            "GIT_CONFIG_GLOBAL": cls.git_config,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
        })

        remotes = os.path.join(cls.root, "remotes") + os.sep
        bare = os.path.join(remotes, "acme", "widgets.git")
        seed = os.path.join(cls.root, "seed")
        cls.checkout = os.path.join(cls.root, "checkout")
        init_repo(bare, "--bare", "-b", "main", env=cls.env)
        init_repo(seed, "-b", "main", env=cls.env)
        cls.git("commit", "--quiet", "--allow-empty", "-m", "base", cwd=seed)
        cls.git("commit", "--quiet", "--allow-empty", "-m", "landed", cwd=seed)
        cls.landed = cls.git("rev-parse", "HEAD", cwd=seed)
        cls.git("checkout", "--quiet", "-b", "stack", cwd=seed)
        cls.git("commit", "--quiet", "--allow-empty", "-m", "stranded", cwd=seed)
        cls.stranded = cls.git("rev-parse", "HEAD", cwd=seed)
        cls.git("push", "--quiet", bare, "main", "stack", cwd=seed)

        init_repo(cls.checkout, "-b", "main", env=cls.env)
        cls.git("config", f"url.{remotes}.insteadOf", "https://github.com/", cwd=cls.checkout)
        cls.git("remote", "add", "origin", "https://github.com/acme/widgets.git", cwd=cls.checkout)

        cls.fake_bin = os.path.join(cls.root, "bin")
        os.mkdir(cls.fake_bin)
        fake_gh = os.path.join(cls.fake_bin, "gh")
        with open(fake_gh, "w", encoding="utf-8") as handle:
            handle.write(FAKE_GH.format(python=sys.executable))
        os.chmod(fake_gh, 0o755)

        cls.no_gh_bin = os.path.join(cls.root, "no-gh-bin")
        os.mkdir(cls.no_gh_bin)
        for tool in ("git", "tr", "paste"):
            os.symlink(shutil.which(tool), os.path.join(cls.no_gh_bin, tool))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    @classmethod
    def git(cls, *args, cwd=None) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, env=cls.env, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def run_script(self, *args, state: dict | None = None, path: str | None = None):
        state_path = os.path.join(self.root, f"state-{self.id()}.json")
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(state or {}, handle)
        env = dict(self.env)
        env["FAKE_GH_STATE"] = state_path
        env["PATH"] = path or self.fake_bin + os.pathsep + env.get("PATH", "")
        return subprocess.run(
            [shutil.which("bash"), VERIFY_SCRIPT, *args],
            cwd=self.checkout, env=env, capture_output=True, text=True,
        )

    def assertUnchecked(self, result):
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, EXIT_UNCHECKED, output)
        self.assertIn("UNCHECKED:", result.stderr)
        self.assertNotIn("OK:", output)
        self.assertNotIn("FAIL:", output)

    def test_the_script_refuses_a_call_with_no_pr_number(self):
        result = subprocess.run(["bash", VERIFY_SCRIPT], capture_output=True, text=True)
        self.assertEqual(result.returncode, EXIT_USAGE, result.stderr)
        self.assertIn("usage:", result.stderr)

    def test_a_malformed_repo_is_a_usage_error(self):
        result = self.run_script("--repo", "not-a-slug", "7")
        self.assertEqual(result.returncode, EXIT_USAGE, result.stderr)

    def test_the_script_parses_as_valid_bash(self):
        result = subprocess.run(["bash", "-n", VERIFY_SCRIPT], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ok_exits_zero_for_a_landed_pr(self):
        state = {"pulls": {"repos/acme/widgets/pulls/7": pull(True, "main", self.landed)}}
        result = self.run_script("--repo", "acme/widgets", "7", state=state)
        self.assertEqual(result.returncode, EXIT_OK, result.stdout + result.stderr)
        self.assertIn(f"OK: {self.landed} is an ancestor of origin/main", result.stdout)

    def test_ok_from_a_pr_url(self):
        state = {"pulls": {"repos/acme/widgets/pulls/7": pull(True, "main", self.landed)}}
        result = self.run_script("https://github.com/acme/widgets/pull/7", state=state)
        self.assertEqual(result.returncode, EXIT_OK, result.stdout + result.stderr)
        self.assertIn("repo=acme/widgets", result.stdout)

    def test_ok_from_a_bare_number_when_origin_is_the_resolved_repo(self):
        state = {
            "default_repo": "acme/widgets",
            "pulls": {"repos/acme/widgets/pulls/7": pull(True, "main", self.landed)},
        }
        result = self.run_script("7", state=state)
        self.assertEqual(result.returncode, EXIT_OK, result.stdout + result.stderr)

    def test_fail_exits_one_for_a_pr_merged_off_the_trunk(self):
        state = {"pulls": {"repos/acme/widgets/pulls/8": pull(True, "stack", self.stranded)}}
        result = self.run_script("--repo", "acme/widgets", "8", state=state)
        self.assertEqual(result.returncode, EXIT_FAIL, result.stdout + result.stderr)
        self.assertIn(f"FAIL: PR #8 in acme/widgets reports MERGED but {self.stranded} is not on origin/main", result.stderr)
        self.assertNotIn("OK:", result.stdout)

    def test_unchecked_when_the_pr_is_not_merged(self):
        state = {"pulls": {"repos/acme/widgets/pulls/9": pull(False, "main", self.landed)}}
        self.assertUnchecked(self.run_script("--repo", "acme/widgets", "9", state=state))

    def test_unchecked_when_there_is_no_merge_commit(self):
        state = {"pulls": {"repos/acme/widgets/pulls/9": pull(True, "main", None)}}
        self.assertUnchecked(self.run_script("--repo", "acme/widgets", "9", state=state))

    def test_unchecked_when_gh_is_unavailable(self):
        self.assertUnchecked(self.run_script("--repo", "acme/widgets", "7", path=self.no_gh_bin))

    def test_unchecked_when_the_api_call_errors(self):
        self.assertUnchecked(self.run_script("--repo", "acme/widgets", "7", state={"pulls": {}}))

    def test_unchecked_when_the_trunk_cannot_be_fetched(self):
        state = {"pulls": {"repos/acme/widgets/pulls/7": pull(True, "main", self.landed)}}
        self.assertUnchecked(
            self.run_script("--repo", "acme/widgets", "7", "no-such-trunk", state=state)
        )

    def test_unchecked_when_the_merge_commit_is_not_fetchable(self):
        state = {"pulls": {"repos/acme/widgets/pulls/7": pull(True, "main", "f" * 40)}}
        self.assertUnchecked(self.run_script("--repo", "acme/widgets", "7", state=state))

    def test_wrong_cwd_bare_number_is_unchecked_not_a_confident_answer(self):
        state = {
            "default_repo": "upstream-org/widgets",
            "pulls": {
                "repos/upstream-org/widgets/pulls/7": pull(False, "master", self.stranded),
                "repos/acme/widgets/pulls/7": pull(True, "stack", self.stranded),
            },
        }
        result = self.run_script("7", state=state)
        self.assertUnchecked(result)
        self.assertIn("upstream-org/widgets", result.stderr)
        self.assertIn("acme/widgets", result.stderr)

    def test_an_explicit_repo_that_is_not_this_checkouts_origin_is_unchecked(self):
        state = {"pulls": {
            "repos/other-org/gadgets/pulls/7": pull(True, "main", self.landed),
            "repos/acme/widgets/pulls/7": pull(True, "stack", self.stranded),
        }}
        result = self.run_script("--repo", "other-org/gadgets", "7", state=state)
        self.assertUnchecked(result)
        self.assertIn("other-org/gadgets", result.stderr)

    def test_a_url_contradicting_the_repo_flag_is_unchecked(self):
        state = {"pulls": {"repos/acme/widgets/pulls/7": pull(True, "main", self.landed)}}
        result = self.run_script(
            "--repo", "other-org/gadgets", "https://github.com/acme/widgets/pull/7", state=state
        )
        self.assertUnchecked(result)


if __name__ == "__main__":
    unittest.main()
