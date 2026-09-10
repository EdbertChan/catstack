#!/usr/bin/env python3
"""Decide whether a reflect fan-out returned enough to apply its findings.

Step 5 of reflect applies Accepted findings. It may start only when every
reviewer lens from step 3 reported. A lens that died -- rate limit, crashed
worktree, killed agent -- is not a lens that passed, so a pass missing one is
partial and says so rather than applying what the survivors happened to find.

Three outcomes, because a check that could not run is not a pass:

    complete    every expected lens returned; apply is allowed
    incomplete  at least one expected lens did not return; apply is refused
    unchecked   the expected set is unknown, so completeness cannot be judged

`unchecked` is not `complete`. It exits non-zero like `incomplete`, because a
fan-out nobody can account for is exactly the case this exists to catch.

    python3 fanout_complete.py --expected a b c --returned a b
    python3 fanout_complete.py --manifest run.json
    python3 fanout_complete.py --expected a b --returned a b --json
"""
from __future__ import annotations

import argparse
import json
import sys

COMPLETE = "complete"
INCOMPLETE = "incomplete"
UNCHECKED = "unchecked"

EXIT = {COMPLETE: 0, INCOMPLETE: 1, UNCHECKED: 2}


def verdict(expected, returned):
    """Outcome plus the lenses missing from this fan-out.

    An empty or absent expected set is `unchecked`: nothing pins what the pass
    was supposed to cover, so a returned set cannot be called complete. A
    returned lens outside the expected set does not make the pass complete and
    is reported so a mislabelled lens is visible rather than silently counted.
    """
    if not expected:
        return UNCHECKED, [], []
    missing = sorted(set(expected) - set(returned))
    unexpected = sorted(set(returned) - set(expected))
    return (COMPLETE if not missing else INCOMPLETE), missing, unexpected


def _from_manifest(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data.get("expected") or [], data.get("returned") or []


def render(outcome, missing, unexpected):
    lines = []
    if outcome == COMPLETE:
        lines.append("complete  every expected lens returned; apply may proceed")
    elif outcome == INCOMPLETE:
        lines.append(f"incomplete  {len(missing)} lens(es) did not return: {', '.join(missing)}")
        lines.append("            re-run them, or report the pass as partial and name them.")
    else:
        lines.append("unchecked  no expected lens set given; completeness cannot be judged")
        lines.append("            name the lenses step 3 launched, then re-run this.")
    if unexpected:
        lines.append(f"            returned but not expected: {', '.join(unexpected)}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected", nargs="*", default=None, help="lens names step 3 launched")
    ap.add_argument("--returned", nargs="*", default=None, help="lens names that reported")
    ap.add_argument("--manifest", help="JSON object with 'expected' and 'returned' lists")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    args = ap.parse_args(argv)

    if args.manifest:
        expected, returned = _from_manifest(args.manifest)
    else:
        expected, returned = args.expected or [], args.returned or []

    outcome, missing, unexpected = verdict(expected, returned)
    if args.json:
        print(json.dumps({
            "outcome": outcome, "missing": missing,
            "unexpected": unexpected, "expected": sorted(set(expected)),
            "returned": sorted(set(returned)),
        }, indent=2))
    else:
        print(render(outcome, missing, unexpected))
    return EXIT[outcome]


if __name__ == "__main__":
    sys.exit(main())
