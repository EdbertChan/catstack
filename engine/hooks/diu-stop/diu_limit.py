"""The diu word limit and what it does not count, shared by the reminder
that states the rule and the checker that enforces it."""
import re

WORD_LIMIT = 150

UNCOUNTED = (
    ("fenced code blocks", re.compile(r"```.*?```", re.DOTALL)),
    ("markdown table rows", re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)),
)


def counted_words(message):
    for _, pattern in UNCOUNTED:
        message = pattern.sub("", message)
    return len(message.split())


def rule_text():
    labels = " or ".join(label for label, _ in UNCOUNTED)
    return f"under {WORD_LIMIT} words, not counting {labels}"
