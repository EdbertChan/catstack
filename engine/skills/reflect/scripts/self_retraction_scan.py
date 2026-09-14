"""Offline scan for first-person wrong-check admissions.

Used only by the reflect miner over whole transcripts. The wrong-check-reflect
hook no longer decides from phrasings; it asks the background judge. This copy
stays text-only so mining historical transcripts needs no model calls.
"""
from __future__ import annotations

import re
from typing import Iterable

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
DOUBLE_QUOTE_RE = re.compile(r'"[^"]*"', re.DOTALL)
BACKTICK_RE = re.compile(r"`[^`]*`", re.DOTALL)

FIRST_PERSON_RE = re.compile(r"(?i)\b(?:i|i'?m|i'?ve|i'?d|my|mine)\b")
PRIOR_STATEMENT_RE = re.compile(
    r"(?i)\b(?:earlier|previously|prior|before|already|above|last\s+turn|"
    r"told\s+you|said|stated|reported|claimed|cited|wrote|answered|called\s+it|"
    r"claim|check|citation|statement|answer|assessment|verdict|summary|report|"
    r"read|grep|assumption|number|count)\b"
)
WRONGNESS_RE = re.compile(
    r"(?i)\b(?:wrong|incorrect|inaccurate|false(?![- ](?:positives?|negatives?|alarms?))|untrue|not\s+true|mistaken|"
    r"misread|mis-read|misstated|overstated|vacuous|premature|bogus|"
    r"retract(?:ing|ed)?|take\s+(?:that|it)\s+back|"
    r"does(?:n'?t|\s+not)\s+hold|did(?:n'?t|\s+not)\s+hold)\b"
)
WINDOW_BEFORE = 260
WINDOW_AFTER = 140

ADMISSION_RES = [
    re.compile(
        r"(?i)\bmy\s+(earlier|previous|prior)\s+"
        r"(check|grep|read|assumption|claim|citation)\s+was\s+wrong\b"
    ),
    re.compile(
        r"(?i)\byou'?re\s+right,?\s+i\s+(misread|mis-read|misunderstood)\b"
    ),
    re.compile(
        r"(?i)\bi\s+incorrectly\s+assumed\b"
    ),
    re.compile(
        r"(?i)\bthe\s+file\s+i\s+(cited|named|pointed\s+to)\s+was\s+(a\s+)?duplicate\b"
    ),
    re.compile(
        r"(?i)\bgood\s+catch\b.{0,80}\bmy\s+(earlier|previous|prior)\s+"
        r"(check|grep|read|assumption|claim)\s+was\s+wrong\b",
        re.DOTALL,
    ),
    re.compile(
        r"(?i)\bi\s+(was\s+wrong|got\s+it\s+wrong)\s+(about|on)\s+"
        r"(the\s+)?(file|path|source|check|assumption)\b"
    ),
    re.compile(
        r"(?i)\bi\s+(?:was\s+wrong|got\s+(?:it|that|this)\s+wrong)\b"
    ),
    re.compile(
        r"(?i)\bi\s+(read|got|took|marked|logged|noted)\s+(that|this|it)\s+wrong\s+"
        r"in\s+my\s+(earlier|previous|prior)\s+\w+"
    ),
    re.compile(
        r"(?i)\bi\s+.{0,120}\b(labeled|marked|claimed|described|reported)\b"
        r".{0,100}\bwithout\s+(actually\s+)?(verifying|checking|confirming)\b"
        r".{0,80}\bat\s+the\s+time\b",
        re.DOTALL,
    ),
    re.compile(
        r"(?i)\bmy\s+mistake\b"
    ),
    re.compile(
        r"(?i)\bi\s+(?:misread|mis-read|misunderstood|mixed\s+up)\b"
    ),
    re.compile(
        r"(?i)^\s*[*_#\s>-]*(?:you[’']?re|you\s+are)\s+right[*_]*\s*[.!:—–]"
    ),
    re.compile(
        r"(?i)\byour\s+(?:instinct|hunch|gut|suspicion|read)\s+(?:was|were)\s+right\b"
    ),
    re.compile(
        r"(?i)^\s*[*_#\s>-]*(?:you'?re\s+right|you\s+are\s+right|good\s+catch)\b"
        r".{0,200}?(?:verifying\s+(?:it\s+|that\s+)?now|checking\s+(?:it\s+|that\s+)?now|"
        r"i\s+hadn'?t\b|i\s+had\s+not\b|i\s+didn'?t\b|i\s+did\s+not\b|"
        r"i\s+should\s+have\b|instead\s+of\s+(?:labeling|labelling|assuming|guessing)|"
        r"i\s+never\s+(?:ran|checked|read|verified))",
        re.DOTALL,
    ),
]

NEGATIVE_RES = [
    re.compile(r"(?i)\bif\s+my\s+(earlier|previous|prior)\s+check\s+was\s+wrong\b"),
    re.compile(
        r"(?i)\bif\s+i\s+(read|got|took|marked|logged|noted)\s+(that|this|it)\s+wrong\b"
    ),
    re.compile(r"(?i)\bthe\s+(test|ui|build|product|code)\s+was\s+wrong\b"),
    re.compile(r"(?i)\bif\b.{0,40}\bmy\s+mistake\b"),
    re.compile(
        r"(?i)\b(?:if|unless|whether|in\s+case|suppose|assuming)\s+i\s+"
        r"(?:misread|mis-read|misunderstood|mixed\s+up)\b"
    ),
    re.compile(
        r"(?i)\b(?:if|unless|whether|in\s+case|suppose|assuming)\s+i\s+"
        r"(?:was|were)\s+wrong\b"
    ),
    re.compile(
        r"(?i)\b(?:says?|said|thinks?|thought|claims?|claimed|argued|insisted|"
        r"told\s+me|telling\s+me)\s+(?:that\s+)?i\s+(?:was|were)\s+wrong\b"
    ),
]

def strip_fences(text: str) -> str:
    return FENCE_RE.sub("", text or "")


def strip_quoted_spans(text: str) -> str:
    cleaned = DOUBLE_QUOTE_RE.sub("", text or "")
    return BACKTICK_RE.sub("", cleaned)


def structural_admission(cleaned: str) -> str | None:
    for hit in WRONGNESS_RE.finditer(cleaned):
        start = max(0, hit.start() - WINDOW_BEFORE)
        window = cleaned[start:hit.end() + WINDOW_AFTER]
        if FIRST_PERSON_RE.search(window) and PRIOR_STATEMENT_RE.search(window):
            return hit.group(0)
    return None


def find_admission(text: str) -> str | None:
    cleaned = strip_quoted_spans(strip_fences(text))
    if not cleaned.strip():
        return None
    for pattern in NEGATIVE_RES:
        if pattern.search(cleaned):
            return None
    for pattern in ADMISSION_RES:
        match = pattern.search(cleaned)
        if match:
            return match.group(0)
    return structural_admission(cleaned)


def scan_assistant_texts(texts: Iterable[str]) -> list[str]:
    hits = []
    for text in texts:
        match = find_admission(text or "")
        if match:
            hits.append(match)
    return hits
