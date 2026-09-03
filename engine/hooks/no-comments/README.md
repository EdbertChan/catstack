# no-comments

PreToolUse hook (Edit|Write|MultiEdit): block an edit that adds comment lines
to a code file. Exit 2 with the offending lines. Comments are banned because
they rot; the commit message and git blame carry the story.

Allowed: shebangs, encoding lines, and machine directives (`noqa`, `type:`,
`pragma`, `pylint`, `mypy`, `ruff`, `eslint`, `prettier`, `@ts-ignore`,
`istanbul`, `nosec`, license and SPDX headers). Out of scope: docstrings,
markdown, JSON, YAML, TOML, and any file not in `detect.CODE_SUFFIXES`.

`scripts/check_no_new_comments.py` is the CI twin: it fails when a diff
against the base adds comment lines to code, using the same detector.

Tests: `python3 -m unittest discover -s engine/hooks/no-comments/tests -v`
