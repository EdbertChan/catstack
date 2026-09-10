#!/usr/bin/env python3
"""One definition of the diu brevity gate: the word limit, what the count
leaves out, and the sentence describing both.

claude_prompt_reminder.py states the rule to the model before it writes and
claude_stop_check.py enforces it after; both read this module, so the
threshold the model aims at is the threshold that fires. Anything that
states the limit in words imports LIMIT_PHRASE rather than spelling the
number out, so there is nothing to keep in sync by hand.

A fenced block (code, logs, diffs, a generated YAML plan) and a markdown
table row are deliberate artifacts, not prose padding, so word_count drops
them. An unterminated ``` counts as ordinary prose and cannot be used to
hide words from the gate.
"""
import re

WORD_LIMIT = 150

FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
MARKDOWN_TABLE_ROW_RE = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)

EXCLUSIONS = ("fenced blocks", "table rows")

LIMIT_PHRASE = f"under {WORD_LIMIT} words ({' and '.join(EXCLUSIONS)} don't count)"


def word_count(message):
    stripped = FENCED_BLOCK_RE.sub("", message)
    return len(MARKDOWN_TABLE_ROW_RE.sub("", stripped).split())
