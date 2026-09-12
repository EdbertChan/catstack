"""Find prose that still tells an author to write the retired escape hatch.

Every evidence hook clears on `{{CAT-UNVERIFIED: <claim> -- cannot verify:
<reason>}}` and nothing else. A rule or skill that still says "write
`UNVERIFIED:`" sends an agent straight into a block, so the instruction and
the hooks have to agree.

A line counts when it carries a bare `UNVERIFIED:` (not the `CAT-` tag) and
does not describe it as retired. Other uses of the word without a colon --
"UNVERIFIED schema", "UNVERIFIED end-to-end" -- are not the marker.
"""
from __future__ import annotations

import os
import re

BARE_MARKER_RE = re.compile(r"(?<!CAT-)\bUNVERIFIED:", re.IGNORECASE)
RETIRED_RE = re.compile(r"\b(?:retired|no longer)\b", re.IGNORECASE)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def instructs_retired_marker(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if BARE_MARKER_RE.search(line) and not RETIRED_RE.search(line)
    ]


def instructional_files() -> list[str]:
    fixed = [
        "engine/CLAUDE.core.md",
        "corpus/CLAUDE.learned.md",
        "README.md",
        "docs/hooks-gap-analysis.md",
    ]
    found = [os.path.join(REPO_ROOT, rel) for rel in fixed]
    for top in ("always-on", "engine", "corpus", "product"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(REPO_ROOT, top)):
            dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__", "node_modules")]
            for name in filenames:
                if name == "SKILL.md" or name == "README.md" or name.endswith(".mdc") \
                        or (name.endswith(".md") and os.path.basename(dirpath) in ("references", "always-on")):
                    found.append(os.path.join(dirpath, name))
    return sorted(set(p for p in found if os.path.isfile(p)))
