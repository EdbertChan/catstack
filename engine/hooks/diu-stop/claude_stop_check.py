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
evidence and no escape-hatch marker. This can't verify the evidence is
real -- only that *something evidence-shaped* (a fenced block, inline code
that looks like output, or the marker itself) sits near the claim. See
skills/prove-it/SKILL.md in the Invoker repo for the full discipline this
mechanically nudges toward.

The marker is `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}`, and
it excuses the paragraph it sits in, the way a fence does. Bare
`UNVERIFIED:` used to excuse the whole message and no longer excuses
anything: it was reachable by typing four characters, which made it the
cheapest way to end a turn, and it was used that way. A tag that names no
blocker is the same move wearing the new syntax, so it does not excuse
either.

`stop_hook_active` marks a rewrite after this hook already fired once this
turn. It used to return before every check, which made the first block of a
turn a free pass for whatever the rewrite said next -- a brand-new claim,
never checked. It now skips only the word-count check, which is the one
that actually loops: trimming words reveals more words to trim, and nine
consecutive blocks on one 150-word message were observed. The evidence
checks cannot loop that way, because a well-formed
{{CAT-UNVERIFIED: ... -- cannot verify: <reason>}} always passes and every
block message names it. There is always a legal move that ends the turn.
Every block names every flagged sentence, so one rewrite that fixes them
all gets through.
"""
import json
import os
import re
import sys

from diu_limit import WORD_LIMIT, counted_words
from plain_words import try_check_reply

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_markers"))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

import markers  # noqa: E402
from finding import Finding  # noqa: E402
from runtime import run_hook  # noqa: E402

RULE_WORD_LIMIT = "diu-stop.word-limit"
RULE_UNVERIFIED_CLAIM = "diu-stop.unverified-claim"
RULE_MALFORMED_MARKER_TAG = "diu-stop.malformed-marker-tag"
RULE_LEGACY_MARKER = "diu-stop.legacy-marker"
RULE_PLAIN_WORDS = "diu-stop.plain-words"

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
FENCE_MARKER = "```"
FENCED_BODY_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
FILE_LINE_RE = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)*[\w-]+\.[A-Za-z]\w*(?::\d+\b|#L\d+\b)")
CITATION_REF_RE = re.compile(
    r"(?<![\w/.-])(?:[\w.-]+/)*[\w-]+\.[A-Za-z]\w*(?::\d+\b|#L\d+\b)\s*@\s*\S+")
LINE_SUFFIX_RE = re.compile(r":\d+\b|#L\d+\b")
OUTPUT_SHAPE_RE = re.compile(
    r"^(?:\$ |> |\+\+\+ |--- |@@ |diff --git|commit [0-9a-f]{7,}|[0-9a-f]{7,10} )"
    r"|Traceback|^\s*at [\w.$<>]+ \(.*:\d+:\d+\)"
    r"|\b(?:Test Files|Tests:|Duration|Snapshots)\b\s+"
    r"|\b\d+ (?:passed|failed|skipped|passing|failing)\b"
    r"|^\s*[✓✗×√❯]\s"
    r"|\b(?:PASS|FAIL|ERROR|error:|Error:|fatal:|warning:|ENOENT|EACCES|npm ERR)\b"
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

SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
SENTENCE_LIMIT = 120


def _opening_word(message):
    stripped = message.lstrip()
    stripped = re.sub(r"^[*_\-#\s]+", "", stripped)
    stripped = markers.LEGACY_RE.sub("", stripped, count=1).lstrip()
    match = re.match(r"[A-Za-z']+", stripped)
    return match.group(0).lower() if match else ""


def prose_only(message):
    """`message` with fenced blocks and inline code removed.

    A marker inside a fence or a pair of backticks is being shown, not used:
    explaining the tag, quoting the rule that defines it, or pasting a gate's
    own message back to the user all put the token on screen without claiming
    anything. `find_unverified_claims` has stripped both for a while; the
    marker check read the raw message, so the gate fired on the sentence that
    taught the reader how not to trip it.

    An unterminated fence leaves a `\u0060\u0060\u0060` behind after the
    substitution. Everything from that marker on is inside a code block that
    never closed, so it is dropped too.
    """
    prose = INLINE_CODE_RE.sub("", FENCED_BODY_RE.sub("", message or ""))
    if FENCE_MARKER in prose:
        prose = prose[:prose.rindex(FENCE_MARKER)]
    return prose


def find_marker_problems(message):
    """Return the marker complaints this message earns, in report order.

    A tag that names no blocker, and the retired bare `UNVERIFIED:`, each
    draw their own message. Both can be present at once. Only prose counts --
    see `prose_only`."""
    prose = prose_only(message)
    problems = []
    if markers.malformed_tags(prose):
        problems.append(markers.MALFORMED_TAG_MESSAGE)
    if markers.has_legacy_marker(prose):
        problems.append(markers.LEGACY_MARKER_MESSAGE)
    return problems


def _sentence_at(para, pos):
    """The sentence of `para` that contains offset `pos`, on one line and
    cut to SENTENCE_LIMIT characters so a block quoting it stays short."""
    start, end = 0, len(para)
    for boundary in SENTENCE_END_RE.finditer(para):
        if boundary.end() <= pos:
            start = boundary.end()
        elif boundary.start() >= pos:
            end = boundary.start()
            break
    sentence = " ".join(para[start:end].split())
    if len(sentence) > SENTENCE_LIMIT:
        sentence = sentence[:SENTENCE_LIMIT - 3] + "..."
    return sentence


def _paragraph_claim(para):
    """(trigger phrase, offset) for the first claim in `para`, or None."""
    lowered = para.lower()
    for phrase in BANNED_PHRASES_UNCONDITIONAL:
        if phrase in lowered:
            return phrase, lowered.index(phrase)
    opener = _opening_word(para)
    if opener in BANNED_OPENERS:
        return opener, 0
    for pattern in (CAUSAL_CLOSER_RE, HEDGE_CLAIM_RE):
        match = pattern.search(para)
        if match:
            return match.group(0), match.start()
    return None


def cited_paths(text):
    """The path part of every file:line in `text`, longest first."""
    seen = []
    for match in FILE_LINE_RE.finditer(text):
        path = LINE_SUFFIX_RE.split(match.group(0))[0]
        if path and path not in seen:
            seen.append(path)
    return sorted(seen, key=len, reverse=True)


def read_evidence(event):
    """Everything this session handed a tool, as one string, or None.

    None means the check could not run -- no transcript to read, or the file
    would not open. That is a third outcome, not a clean one: a citation whose
    read cannot be checked does not buy silence, and the finding says why.
    """
    path = event.get("transcript_path") if isinstance(event, dict) else None
    if not isinstance(path, str) or not path:
        return None
    parts = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                inner = entry.get("message")
                content = inner.get("content") if isinstance(inner, dict) else entry.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        parts.append(json.dumps(block.get("input"), default=str))
    except (OSError, UnicodeError) as exc:
        print(
            f"catstack-hook-error diu-stop: cannot read {path}, so which files "
            f"were read this session is unchecked: {exc}",
            file=sys.stderr,
        )
        return None
    return "\n".join(parts)


def citation_earns_silence(para, read_blob):
    """(exempt, unchecked) for the file:line citations in one paragraph.

    A bare `file.ts:99` used to silence a paragraph on its own, with no check
    that the file exists, that anyone read it, or at what ref. A fabricated
    path silenced the gate exactly as well as a real one. It now has to carry
    the ref it was read at (`path:line @ origin/main`), which is what
    corpus/CLAUDE.learned.md already asks for in prose, or the session has to
    show a tool call that named that path.
    """
    if not FILE_LINE_RE.search(para):
        return False, False
    if CITATION_REF_RE.search(para):
        return True, False
    if read_blob is None:
        return False, True
    return any(path in read_blob for path in cited_paths(para)), False


def find_unverified_claims(message, read_blob=None):
    """Return one (trigger phrase, sentence) pair for every paragraph that
    makes an unverified-shaped claim with no evidence marker in that same
    paragraph, in message order.

    A well-formed `{{CAT-UNVERIFIED}}` tag silences the paragraph it sits
    in, exactly like a fence -- not a later/earlier claim. Inline code
    silences its paragraph only when it looks like command output or the
    message carries a fenced block of output. This is a blunt proxy, not a
    truth check."""
    fenced_output = any(OUTPUT_SHAPE_RE.search(body) for body in FENCED_BODY_RE.findall(message))
    claims = []
    for para in re.split(r"\n\s*\n", message):
        para = FENCED_BODY_RE.sub("", para)
        if not para.strip():
            continue
        if FENCE_MARKER in para:
            continue
        if markers.excuses_paragraph(para):
            continue
        exempt, _unchecked = citation_earns_silence(para, read_blob)
        if exempt:
            continue
        inline = INLINE_CODE_RE.findall(para)
        if inline and (fenced_output or any(OUTPUT_SHAPE_RE.search(code) for code in inline)):
            continue
        hit = _paragraph_claim(para)
        if hit:
            phrase, pos = hit
            claims.append((phrase, _sentence_at(para, pos)))
    return claims


def find_unverified_claim(message, read_blob=None):
    """Return the first offending phrase find_unverified_claims reports, or
    None."""
    claims = find_unverified_claims(message, read_blob)
    return claims[0][0] if claims else None


def unchecked_citations(message, read_blob):
    """Paths cited in a flagged paragraph whose read could not be checked."""
    if read_blob is not None:
        return []
    found = []
    for para in re.split(r"\n\s*\n", message):
        para = FENCED_BODY_RE.sub("", para)
        _exempt, unchecked = citation_earns_silence(para, read_blob)
        if unchecked:
            found.extend(path for path in cited_paths(para) if path not in found)
    return found


def detect(event):
    if event.get("agent_id"):
        return []
    retry = bool(event.get("stop_hook_active"))

    message = event.get("last_assistant_message") or ""

    plain_words_note = try_check_reply(event)

    word_count = counted_words(message)
    over_limit = word_count > WORD_LIMIT and not retry
    read_blob = read_evidence(event)
    claims = find_unverified_claims(message, read_blob)
    marker_problems = find_marker_problems(message)

    findings = []
    if plain_words_note:
        findings.append(Finding(
            rule_id=RULE_PLAIN_WORDS,
            subject=message,
            message=plain_words_note,
            evidence=plain_words_note,
        ))
    if claims:
        lines = [
            "This message makes an unverified-shaped claim with no adjacent "
            "evidence (pasted command output, or a "
            f"`{markers.TAG_TEMPLATE}` tag) in the same paragraph. Every "
            f"flagged sentence ({len(claims)}):"
        ]
        for number, (phrase, sentence) in enumerate(claims, 1):
            lines.append(f"{number}. \"{sentence}\" (trigger: \"{' '.join(phrase.split())}\")")
        lines.append(
            "A backticked name or command alone is not output, and neither is a "
            "bare file:line. Per skills/prove-it/SKILL.md: for each one, either "
            "paste the output of what was actually run/checked in its paragraph, "
            "cite it as `path:line @ <ref>`, or -- only if the check cannot run "
            "-- tag the claim there and say why."
        )
        unchecked = unchecked_citations(message, read_blob)
        if unchecked:
            lines.append(
                "This turn's transcript could not be read, so whether "
                f"{', '.join(unchecked)} was read this session is UNCHECKED, not "
                "clear. Add the ref it was read at to the citation.")
        claim_message = "\n".join(lines)
        findings.append(Finding(
            rule_id=RULE_UNVERIFIED_CLAIM,
            subject=claim_message,
            message=claim_message,
            evidence=claim_message,
        ))
    for problem in marker_problems:
        rule_id = RULE_MALFORMED_MARKER_TAG if problem == markers.MALFORMED_TAG_MESSAGE else RULE_LEGACY_MARKER
        findings.append(Finding(rule_id=rule_id, subject=message, message=problem, evidence=problem))
    if over_limit:
        over_message = (
            f"Apply diu: {word_count} words, over the {WORD_LIMIT}-word "
            f"guideline. Cut at least {word_count - WORD_LIMIT} words by "
            "dropping a whole section or list, not by trimming words. "
            "Keep the part that answers the user's literal question; cut "
            "a different section. Unless this turn genuinely asked for "
            "full technical detail or a specific long format."
        )
        findings.append(Finding(rule_id=RULE_WORD_LIMIT, subject=message, message=over_message, evidence=over_message))
    return findings


def main():
    run_hook("diu-stop", "claude", detect, "Stop")


if __name__ == "__main__":
    main()
