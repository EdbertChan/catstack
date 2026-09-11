"""A heredoc that writes a PR command is file content, not a command that runs it."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from detect import classify_pr_text_write  # noqa: E402
from shell_model import ShellCall, parse_commands  # noqa: E402

TOKEN = "gh" + " pr" + " create"
NL = "\n"


def writes(script: str) -> list:
    commands = parse_commands(ShellCall(script, None), "/s")
    return [w for w in (classify_pr_text_write(c) for c in commands) if w is not None]


class TestStaysSilentOnWrites(unittest.TestCase):
    def test_plain_heredoc_body(self):
        self.assertEqual(writes("cat > f.py <<EOF" + NL + TOKEN + " --title x" + NL + "EOF"), [])

    def test_quoted_delimiter(self):
        self.assertEqual(writes("cat > f.py <<'EOF'" + NL + TOKEN + " --title x" + NL + "EOF"), [])

    def test_indented_delimiter(self):
        self.assertEqual(writes("cat > f.py <<-EOF" + NL + "\t" + TOKEN + " --title x" + NL + "\tEOF"), [])

    def test_custom_delimiter_name(self):
        self.assertEqual(writes("cat > f.py <<PYEOF" + NL + TOKEN + " --title x" + NL + "PYEOF"), [])


class TestStillFiresOnExecution(unittest.TestCase):
    def test_bare_execution(self):
        self.assertEqual(len(writes(TOKEN + " --title x")), 1)

    def test_execution_after_a_heredoc(self):
        script = "cat > f.py <<EOF" + NL + "x = 1" + NL + "EOF" + NL + TOKEN + " --title y"
        self.assertEqual(len(writes(script)), 1)

    def test_execution_on_a_continued_line(self):
        self.assertEqual(len(writes(TOKEN + " \\" + NL + "  --title y")), 1)

    def test_unterminated_heredoc_swallows_the_rest_of_the_script_like_bash(self):
        self.assertEqual(writes("cat > f.py <<EOF" + NL + TOKEN + " --title x"), [])

    def test_unbalanced_quote_is_unparseable_not_empty(self):
        self.assertIsNone(parse_commands(ShellCall("echo 'oops", None), "/s"))


if __name__ == "__main__":
    unittest.main()
