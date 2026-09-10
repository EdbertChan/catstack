#!/usr/bin/env python3
"""Single source of truth for the diu word limit and what the count excludes.

Every file in this hook that states the limit to the model or enforces it
imports from here, so the reminder the model reads before writing and the
check that fires afterwards cannot describe different thresholds.
"""
import re

WORD_LIMIT = 150

FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
MARKDOWN_TABLE_ROW_RE = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)

EXCLUSIONS = ("fenced code blocks", "markdown tables")


def word_count(message):
    stripped = FENCED_BLOCK_RE.sub("", message)
    return len(MARKDOWN_TABLE_ROW_RE.sub("", stripped).split())


def limit_clause():
    return (
        f"ELI5 under {WORD_LIMIT} words unless this turn needs technical "
        f"depth ({' and '.join(EXCLUSIONS)} don't count)"
    )
