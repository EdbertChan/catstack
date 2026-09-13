#!/usr/bin/env python3
"""Check the incidence-needs-repetition README's judge-based guidance."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "engine/hooks/incidence-needs-repetition/README.md"
FORBIDDEN = ("INCIDENCE_RE", "REPETITION_EVIDENCE_RE", "incidence_claims")
REQUIRED = (
    "hands the last reply to the background judge",
    "engine/hooks/llm-judge/phrases/incidence-needs-repetition.json",
    "The answer arrives on a later turn",
    '"could not judge"',
    "same Bash command already ran twice in the turn",
    "add the real text of any miss to `match`",
    "real text of any false alarm to `not_match`",
    "Do not add a pattern",
)


def main() -> int:
    text = README.read_text(encoding="utf-8")
    errors = [f"missing required guidance: {phrase}" for phrase in REQUIRED if phrase not in text]
    errors.extend(f"forbidden pattern name present: {name}" for name in FORBIDDEN if name in text)
    if errors:
        for error in errors:
            print(f"fail\t{error}", file=sys.stderr)
        return 1
    print(f"ok\t{README.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
