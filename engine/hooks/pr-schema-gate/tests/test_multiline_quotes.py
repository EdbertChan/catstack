"""A quoted argument that spans lines is one word, not an unparseable command.

The payload is the real command that drew a false "could not parse" advisory:
a heredoc, then a `git commit -am "<subject>\n\n<trailers>"` whose message spans
three lines.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import claude_pretooluse  # noqa: E402
import detect  # noqa: E402
from shell_model import ShellCall, parse_commands  # noqa: E402

MESSAGE = (
    "principle-explicit-errors: drop an unobserved count from the example\n\n"
    "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>\n"
    "Claude-Session: https://claude.ai/code/session_01WSVNdBBo7dFqoR8Tx521EJ"
)
REAL_COMMAND = (
    "cd /work && python3 - <<'EOF'\n"
    "p = \"tests/fires_example.md\"\n"
    "open(p, \"w\").write(\"x\")\n"
    "EOF\n"
    "grep -n \"rewords\" tests/fires_example.md && git commit -q -am \"" + MESSAGE + "\" && git log --oneline -2"
)


class TestMultilineQuotedArguments(unittest.TestCase):
    def test_real_multiline_commit_message_parses(self):
        commands = parse_commands(ShellCall(REAL_COMMAND, None), "/s")
        self.assertIsNotNone(commands)
        argvs = [c.argv for c in commands]
        self.assertIn(("git", "commit", "-q", "-am", MESSAGE), argvs)
        self.assertIn(("git", "log", "--oneline", "-2"), argvs)
        self.assertIn(("grep", "-n", "rewords", "tests/fires_example.md"), argvs)

    def test_single_quoted_multiline_argument_parses(self):
        commands = parse_commands(ShellCall("echo 'one\ntwo'\necho three", None), "/s")
        self.assertEqual([c.argv for c in commands], [("echo", "one\ntwo"), ("echo", "three")])

    def test_quote_never_closed_is_still_unparseable(self):
        self.assertIsNone(parse_commands(ShellCall("echo 'one\ntwo\nthree", None), "/s"))

    def test_unclosed_quote_ending_in_a_backslash_is_unparseable_not_an_error(self):
        self.assertIsNone(parse_commands(ShellCall('echo "a\\', None), "/s"))

    def test_trailing_backslash_outside_quotes_is_a_line_continuation(self):
        commands = parse_commands(ShellCall("echo done \\", None), "/s")
        self.assertEqual([c.argv for c in commands], [("echo", "done")])

    def test_hook_is_silent_on_the_real_command_in_scope(self):
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, "scripts"))
            os.makedirs(os.path.join(repo, ".git"))
            open(os.path.join(repo, "scripts", "create-pr.mjs"), "w").close()
            state = tempfile.TemporaryDirectory()
            self.addCleanup(state.cleanup)
            os.environ[detect.STATE_DIR_ENV] = state.name
            self.addCleanup(os.environ.pop, detect.STATE_DIR_ENV, None)
            payload = {"tool_name": "Bash", "tool_input": {"command": REAL_COMMAND}, "cwd": repo}
            err, out = io.StringIO(), io.StringIO()
            old = sys.stdin
            sys.stdin = io.StringIO(json.dumps(payload))
            try:
                with redirect_stderr(err), redirect_stdout(out):
                    claude_pretooluse.main()
            finally:
                sys.stdin = old
            self.assertEqual((err.getvalue(), out.getvalue()), ("", ""))


if __name__ == "__main__":
    unittest.main()
