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

`stop_hook_active` marks a rewrite after some Stop hook blocked this turn --
not necessarily this one. It used to return before every check, which made
the first block of a turn a free pass for whatever the rewrite said next -- a
brand-new claim, never checked. Then it skipped the word-count check after
any hook's block, so a long reply rewritten for a different hook went out
unchecked. The word check now reads the transcript to see whose block it
was. It skips only after its own word-limit block, which is the one that
actually loops: trimming words reveals more words to trim, and nine
consecutive blocks on one 150-word message were observed. A ceiling the
user set this turn (`< N words`, `eli5`, `/diu`) is checked once more on the
rewrite, because writing fresh under it always ends the turn. The evidence
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
RULE_UNIVERSAL_CLAIM = "diu-stop.universal-claim"

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
FILE_BASENAME = r"[\w-]+(?:\.[\w-]+)*\.[A-Za-z]\w*"
FILE_LINE_RE = re.compile(
    r"(?<![\w/.-])(?:[\w.-]+/)*" + FILE_BASENAME + r"(?::\d+\b|#L\d+\b)")
CITATION_REF_RE = re.compile(
    r"(?<![\w/.-])(?:[\w.-]+/)*" + FILE_BASENAME + r"(?::\d+\b|#L\d+\b)\s*@\s*\S+")
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
    r"|FAILED \(|\bOK$|\breturns? \d|\bmerged\b|\bconflict\b"
    r"|^\s*\{?\s*\"[\w.:-]+\"\s*:\s*(?:\"[^\"\n]*\"|true\b|false\b|null\b|-?\d|\[|\{)",
    re.MULTILINE,
)
UNVERIFIED_RE = re.compile(r"\bUNVERIFIED:", re.IGNORECASE)
UNIVERSAL_RE = re.compile(
    r"\b(?:only|every|each|both|all|none|never|no\s+other|"
    r"\d+\s+of\s+(?:the\s+)?\d+)\b",
    re.IGNORECASE,
)
UNIVERSAL_BENIGN_RE = re.compile(
    r"\beach\s+other\b|\bonly\s+(?:then|partly|if|when)\b|\bnot\s+only\b", re.IGNORECASE
)
UNIVERSAL_REPORTED_RE = re.compile(
    r"\b(?:I\s+(?:read|checked|looked\s+at|opened|said)|so\s+far|"
    r"that\s+I\s+(?:read|checked|found)|"
    r"(?:the\s+page|the\s+doc|it|you|we)\s+(?:said|claimed|wrote|stated)|"
    r"last\s+turn|earlier\s+I)\b",
    re.IGNORECASE,
)
UNIVERSAL_QUOTE_RE = re.compile(r"\u201c[^\u201d]*\u201d|\"[^\"\n]*\"")
SEARCH_COMMAND_RE = re.compile(
    r"\bgit\s+(?:grep|ls-files)\b|(?<![\w-])rg\s|\bgrep\s+(?:-\w+\s+)*-\w*[rR]"
    r"|\bfind\s+\S+\s+-(?:name|iname|type|path|wholename)\b",
    re.IGNORECASE,
)
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+|\n")

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

ABSENCE_CLAIM_RE = re.compile(
    r"\b(?:has|have|had) no\b|\bthere (?:is|are|was|were) no\b|\bno single\b"
    r"|\bno such (?:call|api|endpoint|function|way)\b|\b(?:can't|cannot|can not) be done\b",
    re.IGNORECASE,
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
    for pattern in (CAUSAL_CLOSER_RE, HEDGE_CLAIM_RE, ABSENCE_CLAIM_RE):
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


LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
FENCED_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def block_shows_evidence(block, read_blob):
    """Whether a list or code block carries output or a backed citation."""
    if any(OUTPUT_SHAPE_RE.search(body) for body in FENCED_BLOCK_RE.findall(block)):
        return True
    if any(OUTPUT_SHAPE_RE.search(code) for code in INLINE_CODE_RE.findall(block)):
        return True
    exempt, _unchecked = citation_earns_silence(block, read_blob)
    return exempt


def introduces_evidence(para, following, read_blob):
    """A paragraph ending in a colon, followed by a list or code block that
    shows evidence, is one unit: the colon hands the claim to that block.

    A sentence such as "I checked three places:" followed by pasted output
    puts the proof one blank line below the claim. Read paragraph by
    paragraph, the claim looked bare. Only a block that starts right after
    the colon counts, and it still has to show output or a citation that
    carries its ref; a plain list of words is not evidence.
    """
    if FENCE_MARKER in para or not para.rstrip().endswith(":"):
        return False
    first_line = following.lstrip("\n").split("\n", 1)[0]
    if not (first_line.lstrip().startswith(FENCE_MARKER) or LIST_ITEM_RE.match(first_line)):
        return False
    return block_shows_evidence(following, read_blob)


def drop_prose_introducing_output(para):
    """`para` without any prose that ends in a colon right before an
    output-shaped fence in the same paragraph. Prose after the fence stays."""
    pieces = []
    cursor = 0
    for match in FENCED_BLOCK_RE.finditer(para):
        before = para[cursor:match.start()]
        if before.rstrip().endswith(":") and OUTPUT_SHAPE_RE.search(match.group(1)):
            before = ""
        pieces.append(before)
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(para[cursor:])
    return "".join(pieces)


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
    paragraphs = re.split(r"\n\s*\n", message)
    for index, raw in enumerate(paragraphs):
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
        if introduces_evidence(raw, following, read_blob):
            continue
        para = drop_prose_introducing_output(raw)
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


def universal_claims(message):
    """Sentences making an only/every/each/both/all/none/never or N-of-M claim
    in a paragraph whose only evidence is file:line citations.

    A paragraph with a fenced block or a search command is not checked: the
    search over all of them is the evidence. Inline code and quoted text are
    not claims. Questions and reported speech are skipped.
    """
    found = []
    for para in re.split(r"\n\s*\n", message or ""):
        if not FILE_LINE_RE.search(para) or FENCE_MARKER in para:
            continue
        if SEARCH_COMMAND_RE.search(para):
            continue
        prose = "\n".join(
            line for line in para.split("\n") if not line.lstrip().startswith(">")
        )
        prose = UNIVERSAL_QUOTE_RE.sub(" ", INLINE_CODE_RE.sub(" ", prose))
        for sentence in SENTENCE_BREAK_RE.split(prose):
            sentence = " ".join(sentence.split())
            if not sentence or sentence.endswith("?"):
                continue
            if not UNIVERSAL_RE.search(UNIVERSAL_BENIGN_RE.sub(" ", sentence)):
                continue
            if UNIVERSAL_REPORTED_RE.search(sentence):
                continue
            found.append(sentence[:SENTENCE_LIMIT - 3] + "..." if len(sentence) > SENTENCE_LIMIT else sentence)
    return found


UNIVERSAL_CLAIM_MESSAGE = (
    "A file:line read backs only that line, not a claim about all of them. "
    "Each flagged sentence makes an only/every/each/both/all/none/never or "
    "N-of-M claim, and its paragraph cites nothing but file:line. For each one, "
    "paste a search over all of them (git grep or rg output in a fenced block, "
    "in the same paragraph), or narrow the claim to what the cited lines show."
)


WORD_LIMIT_MARK = "Apply diu:"
REWRITE_LIMIT = 40
SHORT_QUESTION_WORDS = 40
WORD_CAP_RE = re.compile(r"<\s*(\d+)\s*words?\b", re.IGNORECASE)
BREVITY_ASK_RE = re.compile(r"(?:^|[\s>(])/diu\b|\beli ?5\b", re.IGNORECASE)
DEPTH_ASK_RE = re.compile(
    r"\bin (?:full )?detail\b|\bdetailed\b|\bdeep[- ]dive\b|\bthorough(?:ly)?\b"
    r"|\bstep[- ]by[- ]step\b|\bwalk me through\b|\bfull (?:technical )?detail\b"
    r"|\btechnical depth\b|\bexplain (?:fully|everything)\b|\bwrite[- ]?up\b"
    r"|\bpr (?:summary|description|body)\b|\breport\b|\bthe whole story\b",
    re.IGNORECASE,
)
FEEDBACK_SEGMENT_RE = re.compile(r"\[([^\]\n]*)\]:\s(.*?)(?=\n\[[^\]\n]*\]:\s|\Z)", re.DOTALL)


def user_word_cap(prompt):
    """The word ceiling the user set in this turn's message, or None.

    `< N words` sets N. `eli5`, `eli 5` and an inline `/diu` ask for the
    diu rewrite, which is under 40 words. The smallest one wins."""
    caps = [int(number) for number in WORD_CAP_RE.findall(prompt or "") if int(number) > 0]
    if BREVITY_ASK_RE.search(prompt or ""):
        caps.append(REWRITE_LIMIT)
    return min(caps) if caps else None


def is_short_question(prompt):
    """A short message that asks for no depth."""
    text = prompt or ""
    return 0 < len(text.split()) <= SHORT_QUESTION_WORDS and not DEPTH_ASK_RE.search(text)


def _entry_text(entry):
    inner = entry.get("message")
    content = inner.get("content") if isinstance(inner, dict) else entry.get("content")
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return "", False
    texts = []
    tool_result = False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            tool_result = True
        elif block.get("type") == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
    return "\n".join(texts), tool_result


def own_word_blocks(text):
    """How many diu-stop word-limit blocks one feedback row carries."""
    if "Stop hook feedback" not in text:
        return 0
    return sum(
        1 for command, body in FEEDBACK_SEGMENT_RE.findall(text)
        if "diu-stop/" in command and WORD_LIMIT_MARK in body)


def read_turn(event):
    """(user prompt, own word-limit blocks so far) for this turn, or None.

    The turn starts at the last message a person typed. Hook feedback rows
    after it say which hook blocked. None means no transcript could be read,
    so neither is known."""
    path = event.get("transcript_path") if isinstance(event, dict) else None
    if not isinstance(path, str) or not path:
        return None
    prompt, blocks = "", 0
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
                if not isinstance(entry, dict) or entry.get("type") != "user":
                    continue
                text, tool_result = _entry_text(entry)
                if entry.get("isMeta"):
                    blocks += own_word_blocks(text)
                elif text.startswith("Stop hook feedback"):
                    blocks += own_word_blocks(text)
                elif text.strip() and not tool_result:
                    prompt, blocks = text, 0
    except (OSError, UnicodeError) as exc:
        print(
            f"catstack-hook-error diu-stop: cannot read {path}, so this turn's "
            f"word ceiling and earlier blocks are unchecked: {exc}",
            file=sys.stderr,
        )
        return None
    return prompt, blocks


def word_limit_finding(message, event, retry):
    """The word-limit block message for this reply, or None.

    Which ceiling applies: the user's own cap from this turn; else 150, with
    a 40-word rewrite asked for when a short question with no depth request
    got more than 150 words. A rewrite after this hook's own word block is
    checked again only against a ceiling the turn itself set, and only once,
    so trimming cannot loop. A rewrite after a different hook's block is
    checked like any reply.
    """
    word_count = counted_words(message)
    turn = read_turn(event)
    if turn is None:
        if retry:
            if word_count > WORD_LIMIT:
                print(
                    "diu-stop: word count on this rewrite is unchecked: no "
                    "transcript to tell which hook blocked first.",
                    file=sys.stderr,
                )
            return None
        prompt, own_blocks = "", 0
    else:
        prompt, own_blocks = turn
    cap = user_word_cap(prompt)
    short = cap is None and word_count > WORD_LIMIT and is_short_question(prompt)
    if own_blocks >= 2 or (own_blocks == 1 and cap is None and not short):
        return None
    if cap is not None:
        if word_count <= cap:
            return None
        return (
            f"{WORD_LIMIT_MARK} {word_count} words, over the {cap}-word cap "
            f"the user set this turn. Rewrite under {cap} words, lead with the "
            "answer to the user's literal question, and drop everything else."
        )
    if own_blocks == 1 and short:
        if word_count <= REWRITE_LIMIT:
            return None
        return (
            f"{WORD_LIMIT_MARK} {word_count} words. The rewrite is still over "
            f"{REWRITE_LIMIT}: rewrite under {REWRITE_LIMIT} words, lead with the answer."
        )
    if word_count <= WORD_LIMIT:
        return None
    if short:
        return (
            f"{WORD_LIMIT_MARK} {word_count} words on a short question that "
            f"asked for no depth: rewrite under {REWRITE_LIMIT} words, lead with "
            "the answer. Do not trim this draft; write the answer fresh."
        )
    return (
        f"{WORD_LIMIT_MARK} {word_count} words, over the {WORD_LIMIT}-word "
        f"guideline. Cut at least {word_count - WORD_LIMIT} words by "
        "dropping a whole section or list, not by trimming words. "
        "Keep the part that answers the user's literal question; cut "
        "a different section. Unless this turn genuinely asked for "
        "full technical detail or a specific long format."
    )


def detect(event):
    if event.get("agent_id"):
        return []
    retry = bool(event.get("stop_hook_active"))

    message = event.get("last_assistant_message") or ""

    plain_words_note = try_check_reply(event)

    over_message = word_limit_finding(message, event, retry)
    universal = universal_claims(message)
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
            "bare file:line. Per skills/prove-it/SKILL.md: for each one, first "
            "run the check now (Bash/Read/Grep/WebFetch) and paste its output in "
            "its paragraph, or cite it as `path:line @ <ref>`; or tag it last. A "
            "tag is only for a check that was attempted and could not settle the "
            "claim, and it names the blocker."
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
    if universal:
        numbered = "\n".join(f"{n}. \"{sentence}\"" for n, sentence in enumerate(universal, 1))
        universal_message = f"{UNIVERSAL_CLAIM_MESSAGE}\nFlagged sentences ({len(universal)}):\n{numbered}"
        findings.append(Finding(
            rule_id=RULE_UNIVERSAL_CLAIM,
            subject=universal_message,
            message=universal_message,
            evidence=universal_message,
        ))
    if over_message:
        findings.append(Finding(rule_id=RULE_WORD_LIMIT, subject=message, message=over_message, evidence=over_message))
    return findings


def main():
    run_hook("diu-stop", "claude", detect, "Stop")


if __name__ == "__main__":
    main()
