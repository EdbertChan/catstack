#!/usr/bin/env python3
"""Claude Code Stop hook: deterministic (no LLM) diu word-count + unverified-
claim check.

Replaces the earlier `type: "prompt"` version. That one repeatedly ignored
the "output ONLY JSON" instruction and dumped its raw reasoning into the
transcript as "Stop hook feedback" -- including on turns it decided to
allow. This script can't judge nuance the way the LLM version tried to (a
response that's long because the user explicitly asked for a PR summary or
technical depth will still get flagged), but it can't malform its own
output either. Trade-off: fewer false "logs shown" surprises, more
false-positive blocks on legitimately long answers. Raise WORD_LIMIT if
that gets annoying.

The unverified-claim check exists because a real session let three
different unverified claims reach the user before self-correcting or being
corrected: "someone snuck code into master" (a deliberately built feature,
not an incident), "Confirmed... a severe crash loop" (normal per-invocation
log volume, not a crash loop), and "the fix... never pushed" (it had
pushed; a downstream fetch just hadn't caught up yet). All three had the
same shape: a bare declarative claim opening the message, no adjacent
evidence and no `UNVERIFIED:` prefix. This can't verify the evidence is
real -- only that *something evidence-shaped* (a code block, a command,
inline code, or `UNVERIFIED:` itself) sits near the claim. See
skills/prove-it/SKILL.md in the Invoker repo for the full discipline this
mechanically nudges toward.
"""
import json
import re
import sys

WORD_LIMIT = 150

# Phrases banned outright (from this user's global CLAUDE.md evidence
# rules) -- rarely legitimate even mid-sentence, so no opener restriction.
BANNED_PHRASES_UNCONDITIONAL = [
    "this should work",
    "this fixes it",
    "that's the bug",
    "now it works",
]

# "confirmed"/"verified" are ordinary words with many legitimate mid-sentence
# uses ("I verified this against the API response below"). Only flag them
# as a bare declarative opener -- the actual pattern from the real incident
# ("Confirmed, with a complete timeline...", "**Confirmed** -- ...").
BANNED_OPENERS = ["confirmed", "verified"]

# Evidence-shaped content next to the claim: a fenced/inline code block.
# UNVERIFIED: is a whole-message escape hatch (checked separately). Presence
# doesn't prove the evidence is real -- only that something was shown.
EVIDENCE_MARKER_RE = re.compile(r"```|`[^`]+`|\bUNVERIFIED:", re.IGNORECASE)
CODE_MARKER_RE = re.compile(r"```|`[^`]+`")
UNVERIFIED_RE = re.compile(r"\bUNVERIFIED:", re.IGNORECASE)

# Unhedged causal closer: "the UI is empty because send never executed"
# with no UNVERIFIED:/code. Same-turn evidence still passes.
CAUSAL_CLOSER_RE = re.compile(
    r"the cause is|\bbecause\b|\bso\b.{0,80}(?:never|skipped|didn't|did not)",
    re.IGNORECASE | re.DOTALL,
)

# A fenced block (code, logs, diffs, a generated YAML plan) is a deliberate
# artifact, not prose padding -- exclude it from the word-count gate so a
# legitimate long artifact doesn't get blocked outright. Requires a real
# closing fence: an unterminated ``` is treated as ordinary prose so it can't
# be used to dodge the gate. The unverified-claim check still scans the full,
# unstripped message.
FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _word_count_excluding_fences(message):
    return len(FENCED_BLOCK_RE.sub("", message).split())


def _opening_word(message):
    stripped = message.lstrip()
    stripped = re.sub(r"^[*_\-#\s]+", "", stripped)
    match = re.match(r"[A-Za-z']+", stripped)
    return match.group(0).lower() if match else ""


def find_unverified_claim(message):
    """Return the offending phrase if a paragraph makes an unverified-shaped
    claim with no evidence marker in that same paragraph.

    `UNVERIFIED:` anywhere still silences the whole message. A backtick or
    fence only silences the paragraph it sits in -- not a later/earlier
    claim. This is a blunt proxy, not a truth check."""
    if UNVERIFIED_RE.search(message):
        return None
    for para in re.split(r"\n\s*\n", message):
        if CODE_MARKER_RE.search(para):
            continue
        lowered = para.lower()
        for phrase in BANNED_PHRASES_UNCONDITIONAL:
            if phrase in lowered:
                return phrase
        opener = _opening_word(para)
        if opener in BANNED_OPENERS:
            return opener
        causal = CAUSAL_CLOSER_RE.search(para)
        if causal:
            return causal.group(0)
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    message = data.get("last_assistant_message") or ""

    word_count = _word_count_excluding_fences(message)
    over_limit = word_count > WORD_LIMIT
    claim = find_unverified_claim(message)

    if not over_limit and not claim:
        return

    parts = []
    if claim:
        parts.append(
            f"This message makes an unverified-shaped claim (\"{claim}\") with no "
            "adjacent evidence (a command, output, code reference, or an "
            "`UNVERIFIED:` prefix). Per skills/prove-it/SKILL.md: either show what "
            "was actually run/checked, or prefix the claim with `UNVERIFIED:`."
        )
    if over_limit:
        parts.append(
            f"Apply diu: {word_count} words, over the {WORD_LIMIT}-word "
            "guideline. Rewrite shorter and in plain language, unless "
            "this turn genuinely asked for full technical detail or a "
            "specific long format."
        )
    sys.stderr.write("\n".join(parts) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
