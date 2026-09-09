"""A heredoc that writes the blocked string is not a command that runs it."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from detect import find_blocked_command, strip_heredoc_bodies  # noqa: E402

TOKEN = "gh" + " pr" + " create"
NL = "\n"


def payload(command: str) -> str:
    """Approximate the raw hook payload, where newlines arrive JSON-escaped."""
    return '{"tool_name":"Bash","tool_input":{"command":"' + command.replace(NL, "\\n") + '"}}'


class TestStaysSilentOnWrites(unittest.TestCase):
    def test_plain_heredoc_body(self):
        cmd = "cat > f.py <<EOF" + NL + 'X = "' + TOKEN + '"' + NL + "EOF"
        self.assertIsNone(find_blocked_command(payload(cmd)))

    def test_quoted_delimiter(self):
        cmd = "cat > f.py <<'EOF'" + NL + 'X = "' + TOKEN + '"' + NL + "EOF"
        self.assertIsNone(find_blocked_command(payload(cmd)))

    def test_indented_delimiter(self):
        cmd = "cat > f.py <<-EOF" + NL + '\tX = "' + TOKEN + '"' + NL + "\tEOF"
        self.assertIsNone(find_blocked_command(payload(cmd)))

    def test_custom_delimiter_name(self):
        cmd = "cat > f.py <<PYEOF" + NL + 'X = "' + TOKEN + '"' + NL + "PYEOF"
        self.assertIsNone(find_blocked_command(payload(cmd)))


class TestStillFiresOnExecution(unittest.TestCase):
    def test_bare_execution(self):
        self.assertIsNotNone(find_blocked_command(payload(TOKEN + " --title x")))

    def test_execution_after_a_heredoc(self):
        cmd = ("cat > f.py <<EOF" + NL + "x = 1" + NL + "EOF" + NL
               + TOKEN + " --title y")
        self.assertIsNotNone(find_blocked_command(payload(cmd)))

    def test_unterminated_heredoc_still_blocks(self):
        cmd = "cat > f.py <<EOF" + NL + 'X = "' + TOKEN + '"'
        self.assertIsNotNone(find_blocked_command(payload(cmd)))


class TestStripper(unittest.TestCase):
    def test_keeps_the_opening_line(self):
        cmd = "cat > f.py <<EOF" + NL + "secret" + NL + "EOF"
        out = strip_heredoc_bodies(cmd)
        self.assertIn("cat > f.py <<EOF", out)
        self.assertNotIn("secret", out)

    def test_empty_and_none_safe(self):
        self.assertEqual(strip_heredoc_bodies(""), "")
        self.assertEqual(strip_heredoc_bodies(None), "")


if __name__ == "__main__":
    unittest.main()
