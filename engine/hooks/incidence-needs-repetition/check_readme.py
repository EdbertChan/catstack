from pathlib import Path


README = Path(__file__).with_name("README.md")
text = README.read_text(encoding="utf-8")

required = (
    "phrases/incidence-needs-repetition.json",
    "background judge",
    "carries the dictionary's `on_hit` text",
    '"could not judge"',
    "the same Bash command already ran twice",
    "add the real text of any miss",
    "real text of any false alarm to `not_match`",
    "Do not add a pattern",
)
for phrase in required:
    if phrase not in text:
        raise SystemExit(f"missing README phrase: {phrase}")

for forbidden in ("INCIDENCE_RE", "REPETITION_EVIDENCE_RE", "incidence_claims"):
    if forbidden in text:
        raise SystemExit(f"forbidden README phrase: {forbidden}")

print("incidence-needs-repetition README check: PASS")
