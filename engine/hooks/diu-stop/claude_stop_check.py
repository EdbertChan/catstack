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
real -- only that *something evidence-shaped* (a fenced block, inline code
that looks like output, or `UNVERIFIED:` itself) sits near the claim. See
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

# Evidence-shaped content next to the claim: a fenced block, or inline code
# that looks like command output.
# UNVERIFIED: is a whole-message escape hatch (checked separately). Presence
# doesn't prove the evidence is real -- only that something was shown.
EVIDENCE_MARKER_RE = re.compile(r"```|`[^`]+`|\bUNVERIFIED:", re.IGNORECASE)
FENCE_MARKER = "```"
FENCED_BODY_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
OUTPUT_SHAPE_RE = re.compile(
    r"^(?:\$ |> |\+\+\+ |--- |@@ |diff --git|commit [0-9a-f]{7,}|[0-9a-f]{7,10} )"
    r"|Traceback|^\s*at [\w.$<>]+ \(.*:\d+:\d+\)"
    r"|\b(?:Test Files|Tests:|Duration|Snapshots)\b\s+"
    r"|\b\d+ (?:passed|failed|skipped|passing|failing)\b"
    r"|^\s*[✓✗×√❯]\s"
    r"|\b(?:PASS|FAIL|ERROR|ENOENT|EACCES|npm ERR)\b|\b(?:error|Error|fatal|warning):"
    r"|\w+(?:Error|Exception|Warning)\b"
    r"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
    r"|^real\s+\d+m|^total \d+|^[-drwx]{10}\s"
    r"|\bexit(?: code|status)?[:= ]\s*\d"
    r"|^\s*[\{\[]\s*$"
    r"|\bHTTP/[12]|\bstatus[\"']?\s*[:=]\s*[\"']?\d{3}"
    r"|\bok\s*[:=]\s*(?:true|false)\b|\bRan \d+ tests?\b"
    r"|\bpid=\d+|\bPID \d+"
    r"|\b(?:OPEN|CLOSED|MERGED|SUCCESS|FAILURE|COMPLETED|QUEUED|BLOCKED|running|succeeded|failed|completed)\b"
    r"|^[\w.-]+\s+\|\s|\bnot (?:available|found|installed|permitted)\b"
    r"|\b\d+(?:\.\d+)?\s?(?:ms|s|MB|GB|KB)\b"
    r"|\b(?:true|false|null)\b\s*[,}]|=>|→|->"
    r"|No such file or directory|command not found|Permission denied|EISDIR|EEXIST"
    r"|FAILED \(|\bOK$|\breturns? \d|\bmerged\b|\bconflict\b",
    re.MULTILINE,
)
UNVERIFIED_RE = re.compile(r"\bUNVERIFIED:", re.IGNORECASE)

# Unhedged causal closer: "the UI is empty because send never executed"
# with no UNVERIFIED:/code. Same-turn evidence still passes.
CAUSAL_CLOSER_RE = re.compile(
    r"the cause is|\bbecause\b|\bso\b.{0,80}(?:never|skipped|didn't|did not)"
    r"|\broot cause\b|\bcaused by\b|\bthe (?:reason|cause) (?:is|was)\b"
    r"|\b(?:that's|that is|which is|this is) why\b"
    r"|\bthe (?:bug|issue|problem|failure) (?:is|was)\b|\bthe culprit\b",
    re.IGNORECASE | re.DOTALL,
)

HEDGE_CLAIM_RE = re.compile(
    r"\bi (?:think|believe|suspect)\b.{0,80}\b(?:happened|occurred|caused|is why|"
    r"was why|that's why|that is why|is the (?:reason|cause)|"
    r"was the (?:reason|cause))\b",
    re.IGNORECASE | re.DOTALL,
)

# A fenced block (code, logs, diffs, a generated YAML plan) is a deliberate
# artifact, not prose padding -- exclude it from the word-count gate so a
# legitimate long artifact doesn't get blocked outright. Requires a real
# closing fence: an unterminated ``` is treated as ordinary prose so it can't
# be used to dodge the gate. The unverified-claim check still scans the full,
# unstripped message.
FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
MARKDOWN_TABLE_ROW_RE = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)


def _word_count_excluding_fences(message):
    stripped = FENCED_BLOCK_RE.sub("", message)
    return len(MARKDOWN_TABLE_ROW_RE.sub("", stripped).split())


def _opening_word(message):
    stripped = message.lstrip()
    stripped = re.sub(r"^[*_\-#\s]+", "", stripped)
    match = re.match(r"[A-Za-z']+", stripped)
    return match.group(0).lower() if match else ""


def has_unresolved_unverified_marker(message):
    return bool(UNVERIFIED_RE.search(message))


def find_unverified_claim(message):
    """Return the offending phrase if a paragraph makes an unverified-shaped
    claim with no evidence marker in that same paragraph.

    `UNVERIFIED:` anywhere still silences the whole message. A fence only
    silences the paragraph it sits in -- not a later/earlier claim. Inline
    code silences its paragraph only when it looks like command output or
    the message carries a fenced block of output. This is a blunt proxy,
    not a truth check."""
    if UNVERIFIED_RE.search(message):
        return None
    fenced_output = any(OUTPUT_SHAPE_RE.search(body) for body in FENCED_BODY_RE.findall(message))
    for para in re.split(r"\n\s*\n", message):
        if FENCE_MARKER in para:
            continue
        inline = INLINE_CODE_RE.findall(para)
        if inline and (fenced_output or any(OUTPUT_SHAPE_RE.search(code) for code in inline)):
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
        hedge = HEDGE_CLAIM_RE.search(para)
        if hedge:
            return hedge.group(0)
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    if data.get("agent_id"):
        return
    if data.get("stop_hook_active"):
        # This block already fired once this turn and the agent has rewritten.
        # Let the rewrite through: a second block starts a shave-a-few-words
        # loop (observed: nine consecutive blocks on one 150-word message).
        return

    message = data.get("last_assistant_message") or ""

    word_count = _word_count_excluding_fences(message)
    over_limit = word_count > WORD_LIMIT
    claim = find_unverified_claim(message)
    unverified_marker = has_unresolved_unverified_marker(message)

    if not over_limit and not claim and not unverified_marker:
        return

    parts = []
    if claim:
        parts.append(
            f"This message makes an unverified-shaped claim (\"{claim}\") with no "
            "adjacent evidence (pasted command output, or an `UNVERIFIED:` "
            "prefix). A backticked name or command alone is not output. Per "
            "skills/prove-it/SKILL.md: either paste the output of what was "
            "actually run/checked, or prefix the claim with `UNVERIFIED:`."
        )
    if unverified_marker:
        parts.append(
            "This message contains an `UNVERIFIED:` claim. Per skills/prove-it/"
            "SKILL.md: attempt to verify it now (run the actual check) before "
            "finishing this turn, or tell the user explicitly what is blocking "
            "verification and why it can't happen right now."
        )
    if over_limit:
        parts.append(
            f"Apply diu: {word_count} words, over the {WORD_LIMIT}-word "
            f"guideline. Cut at least {word_count - WORD_LIMIT} words by "
            "dropping a whole section or list, not by trimming words. "
            "Unless this turn genuinely asked for full technical detail "
            "or a specific long format."
        )
    sys.stderr.write("\n".join(parts) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
