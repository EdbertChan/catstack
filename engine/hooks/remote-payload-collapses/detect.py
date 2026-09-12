"""remote-payload-collapses: `sudo -i` re-parses the command you already quoted.

`sudo -i` starts the target user's login shell, and that shell parses the
remaining arguments a second time. The quoting consumed by the first parse
is gone by then, so a quoted command string is re-split on whitespace and
its first word becomes the whole command.

Reproduced on a real host, one variable apart:

    ssh host 'sudo -u demo -H    bash -lc '"'"'set -u\\necho one\\necho two'"'"''
        -> one / two
    ssh host 'sudo -u demo -H -i bash -lc '"'"'set -u\\necho one\\necho two'"'"''
        -> bash: line 1: set: -c: invalid option

Newlines are not the trigger; the second parse is. A script copied to the
host and run by path has nothing left to re-parse. Heredoc bodies are
stripped first: text written into a file, or piped to a remote shell on
stdin, is data rather than an argument.
"""
from __future__ import annotations

import re

LOGIN_SHELL_RE = re.compile(
    r"(?:^|[\s;|&('\"])(?:sudo\b[^\n|;]*?\s-\w*i\b|su\s+-(?:\s|$)|su\s+-l\b)"
)
CARRIES_COMMAND_RE = re.compile(r"-[a-z]*c\b|\bbash\b|\bsh\b|\bzsh\b|\bpython3?\b|\bnode\b")
QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\1\s*$", re.DOTALL | re.MULTILINE)

MESSAGE = (
    "remote-payload-collapses: this command hands a quoted command string to "
    "`sudo -i`, whose login shell parses the arguments a second time. The quoting "
    "the first parse consumed is gone by then, so the string is re-split and its "
    "first word becomes the whole command. Reproduced on a real host, one variable "
    "apart: `sudo -u demo -H bash -lc '<body>'` prints the body's output, while the "
    "same line with `-i` gives `bash: line 1: set: -c: invalid option`.\n"
    "Drop `-i`, or write the payload to a file and run it by path:\n"
    "  scp payload.sh host:/tmp/payload.sh\n"
    "  ssh host 'sudo -u demo -H bash /tmp/payload.sh'"
)


def collapse_risk(command):
    """Describe the re-parsing shape in this command, or '' when there is none."""
    text = HEREDOC_RE.sub("<<HEREDOC", command or "")
    match = LOGIN_SHELL_RE.search(text)
    if not match:
        return ""
    tail = text[match.end():]
    if not CARRIES_COMMAND_RE.search(tail):
        return ""
    if not QUOTED_RE.search(tail):
        return ""
    return "a quoted command string passed through a login shell (`sudo -i` / `su -`)"


def decide(payload):
    """Blocking feedback for a PreToolUse Bash call, or None to allow it."""
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not collapse_risk(command):
        return None
    return MESSAGE
