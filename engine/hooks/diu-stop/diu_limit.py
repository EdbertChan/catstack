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


COMMENT_WORD_LIMIT = 40
ACKNOWLEDGEMENT_WORD_LIMIT = 50
ACKNOWLEDGEMENT_OPENERS = re.compile(r"^\s*(?:on it|got it|working on it|will do|looking into it)\b", re.IGNORECASE)

COMMENT_PROMPT_PREFIX = "[Artifact comment sent to Claude]"

COMMENT_UNCOUNTED = (
    ("fenced code blocks", re.compile(r"```.*?```", re.DOTALL)),
    ("URLs", re.compile(r"https?://\S+")),
)


def comment_words(text):
    for _, pattern in COMMENT_UNCOUNTED:
        text = pattern.sub(" ", text)
    return len(text.split())


def is_acknowledgement(text):
    return bool(ACKNOWLEDGEMENT_OPENERS.match(text))


def comment_limit(text):
    return ACKNOWLEDGEMENT_WORD_LIMIT if is_acknowledgement(text) else COMMENT_WORD_LIMIT


def comment_rule_text(acknowledgement=False):
    labels = " or ".join(label for label, _ in COMMENT_UNCOUNTED)
    limit = ACKNOWLEDGEMENT_WORD_LIMIT if acknowledgement else COMMENT_WORD_LIMIT
    return f"under {limit} words, not counting {labels}"


def is_comment_prompt(prompt):
    return prompt.lstrip().startswith(COMMENT_PROMPT_PREFIX)
