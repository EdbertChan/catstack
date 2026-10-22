# docstring-shape

PreToolUse hook (Edit|Write|MultiEdit, Python files only): block an edit that
leaves a module or function docstring multi-line or over 120 characters. The
proposed edit is applied to the file text in memory (Write: the new content;
Edit: `old_string` replaced by `new_string`, every occurrence with
`replace_all`; MultiEdit: each edit in order), the result is parsed, and only
docstrings whose lines overlap an edited line are measured. Exit 2 names each
docstring with its kind, name and line.

Fires on:

- a function or module docstring whose stripped text contains a newline;
- a function or module docstring whose stripped text is longer than 120
  characters.

Silent on:

- a class docstring, which may run several lines (one idea per line) and has
  no length cap here;
- a docstring the edit does not touch, even when it already breaks the rule;
- a multi-line string that is not a docstring (a query constant, a fixture);
- files that are not `.py`, and tools other than Edit, Write and MultiEdit.

Block message: `docstring-shape: this edit leaves N docstring(s) in <path>
multi-line or over 120 characters. ...` followed by one line per docstring.

Fail direction: three outcomes, not two. A result that does not parse, a file
that does not exist for an Edit, an `old_string` that is not in the file, a
file over 2,000,000 bytes, or a file that is not UTF-8 is reported as
**unchecked** (rule `docstring-shape.unchecked`): the edit is allowed, the
reason is printed to stderr, and the event row records `unchecked` rather than
clean. Garbage on stdin fails open through the SDK with no output.

The rule this enforces is the cat-mode prose rule "A docstring is one line that
says what the thing is for" in
`corpus/skills/cat-mode/references/prose-and-scope.md`.

Tests: `python3 -m unittest discover -s engine/hooks/docstring-shape/tests -v`
