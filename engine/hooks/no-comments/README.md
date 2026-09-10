# no-comments

PreToolUse hook (Edit|Write|MultiEdit): block an edit that adds comment lines
to a code file. Exit 2 with the offending lines. Comments are banned because
they rot; the commit message and git blame carry the story.

Allowed: shebangs, encoding lines, and machine directives (`noqa`, `type:`,
`pragma`, `pylint`, `mypy`, `ruff`, `eslint`, `prettier`, `@ts-ignore`,
`istanbul`, `nosec`, license and SPDX headers). Out of scope: docstrings,
markdown, JSON, YAML, TOML, and any file not in `detect.CODE_SUFFIXES`.

A line starting with `*` is a comment only while a `/* ... */` block is
open. Outside one it is code, such as the CSS universal selector `* {` or
quoted text in HTML. When an edit starts partway through a block comment,
a `*/` with no opener before it marks the lines above it as inside. An
edit made only of `*` lines, with neither `/*` nor `*/`, is treated as
outside and passes.

`scripts/check_no_new_comments.py` is the CI twin: it fails when a diff
against the base adds comment lines to code, using the same detector.

Tests: `python3 -m unittest discover -s engine/hooks/no-comments/tests -v`
