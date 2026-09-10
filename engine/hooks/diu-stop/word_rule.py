import re

WORD_LIMIT = 150

EXCLUSIONS = (
    ("fenced code blocks", re.compile(r"```.*?```", re.DOTALL)),
    ("table rows", re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)),
)


def word_count(message):
    for _, pattern in EXCLUSIONS:
        message = pattern.sub("", message)
    return len(message.split())


def describe():
    labels = [label for label, _ in EXCLUSIONS]
    return f"under {WORD_LIMIT} words ({' and '.join(labels)} don't count)"
