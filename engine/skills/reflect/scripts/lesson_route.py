#!/usr/bin/env python3
"""Route a reflect finding to a lesson bucket before synthesis sorts it.

Step 4 of reflect used to treat every restated existing rule as automate-me
evidence. That writes a new preference for a skill the agent already skipped.
This script's bucket wins over the model's sort: a restated rule whose skill
already states it is Rejected as already-covered, not a new lesson.

Buckets:

    already-covered   skill already states the rule, or the assistant admitted
                      the skip ("It is; I skipped it"). Route Rejected.
                      Do not call automate-me.
    skill-not-used    transcript never opened the named skill. Rejected unless
                      missed_trigger is set (then action is tune-description).
    automate-me       working preference, and no existing skill states it.
    accepted          durable, decision-changing, not session-specific.
                      Frustration / intervention-must-automate does not select
                      this bucket.

    python3 lesson_route.py --quote "..." --assistant-reply "It is; I skipped it."
    python3 lesson_route.py --from-transcript fixtures/restated_rule/fires.jsonl
    python3 lesson_route.py --kind preference --quote "always open a PR after green"
    python3 lesson_route.py --skill-used no --skill-path engine/skills/foo/SKILL.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys

ALREADY_COVERED = "already-covered"
SKILL_NOT_USED = "skill-not-used"
AUTOMATE_ME = "automate-me"
ACCEPTED = "accepted"

BUCKETS = (ALREADY_COVERED, SKILL_NOT_USED, AUTOMATE_ME, ACCEPTED)

SKIP_ADMISSION = re.compile(
    r"\bi skipped (it|that|the skill|the rule)\b"
    r"|\bit is;?\s*i skipped\b"
    r"|\bi should have (followed|read|used)\b"
    r"|\bi (already )?(knew|know) (that|about)\b.*\b(skipped|didn't follow|did not follow)\b",
    re.I,
)

RESTATED_RULE_SHAPE = re.compile(
    r"\bi thought that was a skill\b"
    r"|\bisn'?t there already a (rule|skill)\b"
    r"|\bwe already decided\b"
    r"|\bthe \w[\w-]* skill says\b"
    r"|\b(a|the) skill\s+that we enforce\b"
    r"|\bdid you not read (it|the)\b",
    re.I,
)

PREFERENCE_SHAPE = re.compile(
    r"\b(always|never|from now on|by default|don'?t ask)\b"
    r"|\bwe don'?t have a rule for this yet\b"
    r"|\bcan you (add|capture|automate)\b"
    r"|\bi (prefer|want|like) (you )?to\b",
    re.I,
)

SESSION_SPECIFIC = re.compile(
    r"\b[0-9a-f]{7,40}\b"
    r"|/(?:Users|home|tmp)/[^\s]+"
    r"|\b(?:ticker|case|pr)\s*#?\d+\b",
    re.I,
)


def _truthy(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _skill_states_rule(skill_text, quote):
    """The shared words that make the target skill read as already carrying
    the restated rule; empty when it does not.

    Looks for shared content words of length >= 4 between the quote and the
    skill body (minus stopwords). A short overlap is enough: the restated-rule
    checker already decided a rule exists; this only confirms the named skill
    is a home for it. The words are returned so the rationale can show what
    matched.
    """
    if not skill_text or not quote:
        return []
    stop = {
        "that", "this", "with", "from", "have", "were", "been", "when",
        "what", "which", "there", "their", "about", "should", "would",
        "could", "think", "thought", "skill", "skills", "rule", "rules",
        "enforce", "already", "doing", "these", "those", "into", "just",
    }
    words = {
        w for w in re.findall(r"[a-z]{4,}", quote.lower())
        if w not in stop
    }
    body = skill_text.lower()
    hits = sorted(w for w in words if w in body)
    if len(hits) >= 2:
        return hits
    if "worktree" in body and "worktree" in quote.lower():
        return ["worktree"]
    return []


def route(
    *,
    quote="",
    assistant_reply="",
    skill_text=None,
    skill_used=None,
    kind="",
    missed_trigger=False,
    durable=True,
    decision_changing=True,
):
    """Pick the lesson bucket for one finding.

    Frustration signals and intervention-must-automate may order the pass;
    they do not select ``accepted`` or ``automate-me`` by themselves.
    """
    quote = quote or ""
    assistant_reply = assistant_reply or ""
    kind = (kind or "").strip().lower().replace("_", "-")
    reasons = []

    admitted_skip = bool(SKIP_ADMISSION.search(assistant_reply))  # text-match-decision-warn: allow
    restated = kind in ("restated-rule", "restated") or bool(
        RESTATED_RULE_SHAPE.search(quote)  # text-match-decision-warn: allow
    )
    shared_words = _skill_states_rule(skill_text, quote) if skill_text else []
    skill_covers = bool(shared_words)

    if admitted_skip or restated or (skill_covers and not _truthy_preference(kind, quote)):
        if admitted_skip:
            reasons.append("assistant admitted the skill/rule exists and was skipped")
        if restated:
            reasons.append("utterance restates a rule that already exists")
        if skill_covers:
            reasons.append(
                "target skill already states the rule (shared words: " + ", ".join(shared_words) + ")"
            )
        if kind in ("restated-rule", "restated"):
            reasons.append("kind=restated-rule means the rule already exists")
        if not reasons:
            reasons.append("target skill already states the rule; issue is execution, not the skill")
        return {
            "bucket": ALREADY_COVERED,
            "action": "reject",
            "rationale": "; ".join(reasons) + "; do not route to automate-me",
        }

    if skill_used is False:
        if missed_trigger:
            return {
                "bucket": SKILL_NOT_USED,
                "action": "tune-description",
                "rationale": "skill was visible but did not trigger; tune its description",
            }
        return {
            "bucket": SKILL_NOT_USED,
            "action": "reject",
            "rationale": "transcript never opened the named skill; reject as skill-not-used",
        }

    if _truthy_preference(kind, quote) and not skill_covers:
        return {
            "bucket": AUTOMATE_ME,
            "action": "automate-me",
            "rationale": "working preference with no existing skill stating it",
        }

    session_specific = bool(SESSION_SPECIFIC.search(quote))
    if durable and decision_changing and not session_specific:
        return {
            "bucket": ACCEPTED,
            "action": "accept",
            "rationale": "durable and decision-changing; frustration did not select this bucket",
        }

    reasons = []
    if not durable:
        reasons.append("not durable across path/SHA/tool drift")
    if not decision_changing:
        reasons.append("would not change a future agent action")
    if session_specific:
        reasons.append("session-specific paths/SHAs/case names")
    return {
        "bucket": ALREADY_COVERED if skill_covers else SKILL_NOT_USED,
        "action": "reject",
        "rationale": "; ".join(reasons) or "not accepted",
    }


def _truthy_preference(kind, quote):
    if kind in ("preference", "working-style", "working-preference", "automate-me"):
        return True
    if RESTATED_RULE_SHAPE.search(quote or ""):
        return False
    return bool(PREFERENCE_SHAPE.search(quote or ""))


def _claude_text_blocks(row):
    msg = row.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
        elif isinstance(block, dict) and block.get("type") == "tool_result":
            continue
    return "\n".join(parts)


def findings_from_transcript(path):
    """Pull (quote, assistant_reply) pairs from a Claude-shaped JSONL session.

    Used by the fires.jsonl repro: a restated-rule human turn followed by an
    assistant admission of skip becomes an already-covered finding.
    """
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    pairs = []
    pending_quote = None
    for row in rows:
        msg = row.get("message") or {}
        role = msg.get("role") or row.get("type")
        text = _claude_text_blocks(row).strip()
        if not text:
            continue
        if role == "user":
            if text.startswith("[Request interrupted"):
                continue
            if RESTATED_RULE_SHAPE.search(text) or PREFERENCE_SHAPE.search(text):  # text-match-decision-warn: allow
                pending_quote = text
            continue
        if role == "assistant" and pending_quote is not None:
            pairs.append({"quote": pending_quote, "assistant_reply": text})
            pending_quote = None
    if pending_quote is not None:
        pairs.append({"quote": pending_quote, "assistant_reply": ""})
    return pairs


def route_transcript(path, **kwargs):
    """Route every restated/preference pair in a transcript; return the strictest."""
    pairs = findings_from_transcript(path)
    if not pairs:
        return {
            "bucket": ACCEPTED,
            "action": "accept",
            "rationale": "no restated-rule or preference utterance found",
            "findings": [],
        }
    findings = []
    for pair in pairs:
        kind = kwargs.get("kind") or (
            "restated-rule" if RESTATED_RULE_SHAPE.search(pair["quote"]) else "preference"
        )
        result = route(
            quote=pair["quote"],
            assistant_reply=pair["assistant_reply"],
            skill_text=kwargs.get("skill_text"),
            skill_used=kwargs.get("skill_used"),
            kind=kind,
            missed_trigger=kwargs.get("missed_trigger", False),
            durable=kwargs.get("durable", True),
            decision_changing=kwargs.get("decision_changing", True),
        )
        findings.append({**pair, **result})

    rank = {ALREADY_COVERED: 0, SKILL_NOT_USED: 1, AUTOMATE_ME: 2, ACCEPTED: 3}
    best = min(findings, key=lambda f: rank.get(f["bucket"], 99))
    return {
        "bucket": best["bucket"],
        "action": best["action"],
        "rationale": best["rationale"],
        "findings": findings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--quote", default="", help="incident human utterance")
    ap.add_argument("--assistant-reply", default="", help="assistant text after the quote")
    ap.add_argument("--skill-text", default=None, help="body of the target skill")
    ap.add_argument("--skill-path", default=None, help="read skill text from this path")
    ap.add_argument(
        "--skill-used",
        default=None,
        help="yes/no: whether the transcript opened the skill",
    )
    ap.add_argument(
        "--kind",
        default="",
        help="restated-rule | preference | durable-lesson",
    )
    ap.add_argument(
        "--missed-trigger",
        action="store_true",
        help="skill was catalog-visible but did not fire",
    )
    ap.add_argument(
        "--not-durable",
        action="store_true",
        help="proposal depends on session paths/SHAs/case names",
    )
    ap.add_argument(
        "--not-decision-changing",
        action="store_true",
        help="proposal would not change a future agent action",
    )
    ap.add_argument(
        "--from-transcript",
        default=None,
        help="Claude-shaped JSONL; route restated/preference pairs inside it",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    args = ap.parse_args(argv)

    skill_text = args.skill_text
    if args.skill_path:
        with open(args.skill_path, encoding="utf-8") as handle:
            skill_text = handle.read()

    skill_used = _truthy(args.skill_used) if args.skill_used is not None else None
    kwargs = dict(
        skill_text=skill_text,
        skill_used=skill_used,
        kind=args.kind,
        missed_trigger=args.missed_trigger,
        durable=not args.not_durable,
        decision_changing=not args.not_decision_changing,
    )

    if args.from_transcript:
        result = route_transcript(args.from_transcript, **kwargs)
    else:
        result = route(
            quote=args.quote,
            assistant_reply=args.assistant_reply,
            **kwargs,
        )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["bucket"])
        print(result["rationale"])
        if result.get("action") and result["action"] != result["bucket"]:
            print(f"action: {result['action']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
