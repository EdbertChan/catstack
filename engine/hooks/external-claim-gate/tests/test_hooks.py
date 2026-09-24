from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

TAGGED = "{{CAT-UNVERIFIED: the cause -- cannot verify: the log host is offline}}"

import detect  # noqa: E402
from detect import block_message, evaluate  # noqa: E402

HOOK = os.path.join(HOOK_DIR, "claude_pretooluse.py")
DIU_STOP = os.path.realpath(os.path.join(HOOK_DIR, "..", "diu-stop", "claude_stop_check.py"))

CAUSE = "The worker crashes because the cache is never invalidated."
RESOLUTION = "Verified, the upload succeeds after the retry change."


def outcomes(command: str, cwd: str | None = None) -> list[str]:
    return [f.outcome for f in evaluate(command, cwd)]


def run_hook(payload) -> subprocess.CompletedProcess:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, HOOK], input=stdin, capture_output=True, text=True, timeout=10)


def bash_payload(command: str, cwd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


class TestBlocksPerDestination(unittest.TestCase):
    def test_blocks_issue_create_cause(self):
        self.assertEqual(outcomes(f"gh issue create --repo o/r --title Crash --body '{CAUSE}'"), ["hit"])

    def test_blocks_issue_comment_resolution(self):
        self.assertEqual(outcomes(f"gh issue comment 12 --repo o/r --body '{RESOLUTION}'"), ["hit"])

    def test_blocks_pr_comment(self):
        self.assertEqual(outcomes(f'gh pr comment 7 -b "{CAUSE}"'), ["hit"])

    def test_blocks_release_create_notes(self):
        self.assertEqual(outcomes(f"gh release create v1.2.0 --title v1.2.0 --notes '{CAUSE}'"), ["hit"])

    def test_blocks_api_post_body_field(self):
        self.assertEqual(outcomes(f"gh api repos/o/r/issues -f title=Crash -f body='{CAUSE}'"), ["hit"])

    def test_blocks_api_patch_body_field(self):
        self.assertEqual(outcomes(f"gh api -X PATCH repos/o/r/issues/comments/9 -f 'body={RESOLUTION}'"), ["hit"])

    def test_blocks_api_input_json_carrying_body(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "payload.json").write_text(json.dumps({"body": CAUSE}))
            self.assertEqual(outcomes("gh api repos/o/r/issues/3/comments --input payload.json", d), ["hit"])

    def test_blocks_claim_read_from_body_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text(f"## What happened\n\n{CAUSE}\n")
            self.assertEqual(outcomes("gh issue create --title Crash --body-file b.md", d), ["hit"])

    def test_blocks_body_file_after_cd(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text(CAUSE)
            self.assertEqual(outcomes(f"cd {d} && gh issue comment 1 -F b.md", "/"), ["hit"])

    def test_blocks_inside_bash_dash_c(self):
        self.assertEqual(outcomes(f"bash -lc \"gh issue comment 1 --body '{CAUSE}'\""), ["hit"])

    def test_block_message_names_claim_missing_evidence_and_both_exits(self):
        message = block_message(evaluate(f"gh issue create --title Crash --body '{CAUSE}'"))
        self.assertIn("gh issue create", message)
        self.assertIn('claim: "because"', message)
        self.assertIn("no fenced block, no file:line reference, no pasted command output", message)
        self.assertIn("Add the evidence to the body", message)
        self.assertIn("CAT-UNVERIFIED", message)


class TestSilentWhenEvidenceOrNoClaim(unittest.TestCase):
    def test_silent_with_fenced_block(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text(f"{CAUSE}\n\n```\nKeyError: 'session'\n```\n")
            self.assertEqual(outcomes("gh issue create --title Crash --body-file b.md", d), [])

    def test_silent_with_file_line_reference(self):
        body = CAUSE + " The TTL is never read at src/cache/store.py:88 either."
        self.assertEqual(outcomes(f"gh issue comment 4 --body '{body}'"), [])

    def test_silent_with_pasted_command_output(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text(f"{CAUSE}\n\n$ python3 -m worker --once\nKeyError: 'session'\n")
            self.assertEqual(outcomes("gh pr comment 7 --body-file b.md", d), [])

    def test_silent_with_unverified_marker(self):
        self.assertEqual(outcomes(f"gh release create v2 --notes '{CAUSE} {TAGGED}'"), [])

    def test_silent_feature_request(self):
        body = "Feature request: add a --json flag to the status command."
        self.assertEqual(outcomes(f"gh issue create --title 'Add --json' --body '{body}'"), [])

    def test_silent_question(self):
        body = "Does the importer accept CSV files that start with a byte-order mark?"
        self.assertEqual(outcomes(f"gh issue comment 5 --body '{body}'"), [])

    def test_silent_status_note(self):
        body = "Status: the rollout is paused until the review lands. Next update tomorrow."
        self.assertEqual(outcomes(f"gh api -X PATCH repos/o/r/issues/comments/2 -f body='{body}'"), [])

    def test_silent_for_commands_that_publish_nothing(self):
        self.assertEqual(outcomes(f"git commit -m '{CAUSE}'"), [])
        self.assertEqual(outcomes(f"echo gh issue create --body '{CAUSE}'"), [])
        self.assertEqual(outcomes("gh issue list --search 'because'"), [])
        self.assertEqual(outcomes("gh api repos/o/r/issues"), [])
        self.assertEqual(outcomes("gh api -X POST repos/o/r/labels -f name=bug"), [])
        self.assertEqual(outcomes("gh release create v3 --generate-notes"), [])

    def test_silent_single_quoted_dollar_is_read_as_literal_text(self):
        self.assertEqual(outcomes("gh issue comment 1 --body 'Costs $5 a month; question: keep it?'"), [])


class TestUncheckedBlocksInsteadOfPassing(unittest.TestCase):
    def test_unchecked_heredoc_into_body_file_stdin(self):
        command = "gh issue create --title Note --body-file - <<'EOF'\nFeature request: add dark mode.\nEOF"
        self.assertEqual(outcomes(command), ["unchecked"])
        self.assertIn("a heredoc", evaluate(command)[0].detail)

    def test_unchecked_command_substitution_heredoc(self):
        command = 'gh issue comment 3 --body "$(cat <<\'EOF\'\nsome text\nEOF\n)"'
        self.assertEqual(outcomes(command), ["unchecked"])

    def test_unchecked_unreadable_body_file_path(self):
        with tempfile.TemporaryDirectory() as d:
            command = "gh issue create --title X --body-file missing.md"
            self.assertEqual(outcomes(command, d), ["unchecked"])
            self.assertIn("cannot be read", evaluate(command, d)[0].detail)

    def test_unchecked_shell_variable_body(self):
        self.assertEqual(outcomes('gh pr comment 9 --body "$BODY"'), ["unchecked"])

    def test_unchecked_api_body_field_from_variable(self):
        self.assertEqual(outcomes('gh api repos/o/r/issues/1/comments -f body="$MSG"'), ["unchecked"])

    def test_unchecked_body_piped_on_stdin(self):
        self.assertEqual(outcomes("cat notes.md | gh release create v1 --notes-file -"), ["unchecked"])

    def test_unchecked_api_input_from_stdin(self):
        self.assertEqual(outcomes("gh api repos/o/r/issues --input - < payload.json"), ["unchecked"])

    def test_unchecked_unparseable_command(self):
        self.assertEqual(outcomes("gh issue comment 1 --body 'unterminated"), ["unchecked"])

    def test_unchecked_body_file_over_read_cap(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "big.md").write_text("x" * (detect.READ_CAP_BYTES + 1))
            self.assertEqual(outcomes("gh issue create --title X --body-file big.md", d), ["unchecked"])

    def test_unchecked_body_file_rewritten_earlier_in_the_same_command(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text("Feature request: add dark mode.")
            command = f"cat > b.md <<'EOF'\n{CAUSE}\nEOF\ngh issue create --title X --body-file b.md"
            self.assertEqual(outcomes(command, d), ["unchecked"])
            self.assertIn("written earlier in this same command", evaluate(command, d)[0].detail)
            self.assertEqual(outcomes("printf x | tee b.md && gh issue comment 1 -F b.md", d), ["unchecked"])
            self.assertEqual(outcomes("bash -c 'echo x > b.md'; gh pr comment 2 -F b.md", d), ["unchecked"])

    def test_silent_when_the_same_command_writes_only_other_files(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text("Feature request: add dark mode.")
            command = "ls 2>/dev/null > listing.txt; gh issue comment 1 --body-file b.md > /dev/null 2>&1"
            self.assertEqual(outcomes(command, d), [])

    def test_unchecked_message_says_unchecked_and_how_to_make_it_readable(self):
        message = block_message(evaluate('gh pr comment 9 --body "$BODY"'))
        self.assertIn("UNCHECKED", message)
        self.assertIn("could not be read", message)
        self.assertIn("CAT-UNVERIFIED", message)


class TestReusesTheDiuStopMatcher(unittest.TestCase):
    def test_claim_shapes_come_from_diu_stop_not_a_copy(self):
        matcher = detect._matcher()
        self.assertEqual(matcher.__name__, "find_unverified_claim")
        self.assertEqual(os.path.realpath(inspect.getsourcefile(matcher)), DIU_STOP)

    def test_detect_defines_no_claim_regex_of_its_own(self):
        source = Path(HOOK_DIR, "detect.py").read_text()
        for name in ("CAUSAL_CLOSER_RE", "HEDGE_CLAIM_RE", "BANNED_PHRASES", "BANNED_OPENERS"):
            self.assertNotIn(name, source)


class TestHookProcess(unittest.TestCase):
    def test_hook_blocks_claim_with_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_hook(bash_payload(f"gh issue create --title Crash --body '{CAUSE}'", d))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("external-claim-gate", result.stderr)

    def test_hook_blocks_unchecked_body_with_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_hook(bash_payload("gh issue create --title X --body-file nope.md", d))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("UNCHECKED", result.stderr)

    def test_hook_allows_evidenced_body_with_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_hook(bash_payload(f"gh issue create --title X --body '{CAUSE} {TAGGED}'", d))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_hook_never_fires_on_non_bash_tools(self):
        payload = {"tool_name": "Write", "tool_input": {"content": f"gh issue create --body '{CAUSE}'"}}
        self.assertEqual(run_hook(payload).returncode, 0)

    def test_hook_refuses_malformed_payload_naming_a_gh_write(self):
        result = run_hook('{"tool_input": {"command": "gh issue create --body x"')
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNCHECKED", result.stderr)

    def test_hook_allows_malformed_payload_without_a_gh_write(self):
        result = run_hook("not json at all")
        self.assertEqual(result.returncode, 0)
        self.assertIn("allowing", result.stderr)


if __name__ == "__main__":
    unittest.main()
