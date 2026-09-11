#!/usr/bin/env python3
"""One definition of the escape-hatch marker, shared by every evidence hook.

`{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}` is the only marker
that excuses a claim. It excuses the paragraph it sits in, and only when it
names a blocker after `cannot verify:`. A tag that names nothing does not
excuse anything -- that shape is the one an author reaches for to end a turn
without checking, which is what the marker exists to prevent.

Bare `UNVERIFIED:` is ordinary prose. It used to be the escape hatch, so a
message still carrying it gets `legacy_marker` set and is told which tag to
use instead, rather than silently losing the suppression it expected.

Why a module and not a regex copied into each hook: six hooks read this
marker. Two classifiers over the same input drift apart silently -- the
reason clause landed in hedge-runs-prove-it and never reached diu-stop.

Hooks are installed as sibling symlinks under $HOME/.claude/hooks/, so a
hook reaches this module by its own parent directory:

    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_markers"))

Two dirnames, not a "..": the hook's own directory is a symlink, so the OS
resolves it before applying "..", landing beside the checkout instead of
beside the other hooks. Stripping two segments textually cannot do that, and
abspath (never realpath) is what keeps the installed path in place.
"""
from __future__ import annotations

import re

TAG_RE = re.compile(r"\{\{\s*CAT-UNVERIFIED\b(?P<body>[^}]*)\}\}", re.IGNORECASE)
REASON_RE = re.compile(r"cannot\s+verify\s*:\s*(?P<reason>\S.*)", re.IGNORECASE | re.DOTALL)
LEGACY_RE = re.compile(r"(?<!CAT-)\bUNVERIFIED:", re.IGNORECASE)

TAG_TEMPLATE = "{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}"

MALFORMED_TAG_MESSAGE = (
    "A `{{CAT-UNVERIFIED}}` tag here names no blocker. Per "
    "skills/prove-it/SKILL.md the tag is for a check that cannot run, and it "
    f"has to say why: `{TAG_TEMPLATE}`. If the check can run, run it and paste "
    "the output instead."
)

LEGACY_MARKER_MESSAGE = (
    "`UNVERIFIED:` is no longer an escape hatch -- it reads as ordinary prose "
    "and the claim beside it is judged on its own. Per skills/prove-it/SKILL.md: "
    "run the check and paste its output. Only if the check genuinely cannot run, "
    f"write `{TAG_TEMPLATE}`."
)


def _names_a_blocker(body: str) -> bool:
    match = REASON_RE.search(body)
    if not match:
        return False
    return bool(match.group("reason").strip(" -_.:\t\r\n"))


def well_formed_tags(text: str) -> list[str]:
    """Every `{{CAT-UNVERIFIED: ...}}` in `text` that names a blocker."""
    return [m.group(0) for m in TAG_RE.finditer(text) if _names_a_blocker(m.group("body"))]


def malformed_tags(text: str) -> list[str]:
    """Every `{{CAT-UNVERIFIED: ...}}` in `text` that names no blocker."""
    return [m.group(0) for m in TAG_RE.finditer(text) if not _names_a_blocker(m.group("body"))]


def excuses_paragraph(paragraph: str) -> bool:
    """True when this paragraph carries a tag that names a blocker."""
    return bool(well_formed_tags(paragraph))


def has_legacy_marker(text: str) -> bool:
    """True when `text` still uses the retired bare `UNVERIFIED:` marker."""
    return bool(LEGACY_RE.search(text))
