# short-name

PreToolUse hook (Edit|Write|MultiEdit): block an edit that introduces an
abbreviated or one- or two-letter name. Python files are parsed; for any file
that `Write` creates, the file stem is checked too. The proposed edit is
applied to the file text in memory (the same way `docstring-shape` does it,
through `engine/hooks/_sdk/proposed_edit.py`) and only names on edited lines
are judged, so a short name already in the file stays out of scope until a
line that defines it is touched. Exit 2 names each hit with its kind, name
and line.

Names in scope: `def` and `class` names, parameters (positional, keyword-only,
`*args`, `**kwargs`), attribute assignments (`self.x = ...`, including tuple
targets and annotated or augmented forms), class-body fields (`name: int`),
and the stem of a new file. Out of scope: loop variables, comprehension
targets, lambda parameters, plain local assignments, and dunder names such as
`__eq__`.

How a name is judged: strip leading underscores, split on underscores, and
look at each part.

- A part in `DENIED_ABBREVIATIONS` (`preds`, `topo`, `recs`, `resp`, `proj`,
  `iid`, `dur`, `nid`, `cfg`, `dd`, `gl`, `cnt`, `idx`, `tmp`, `buf`, `msg`,
  `msgs`, `params`) fails whatever its length.
- A part in `ACCEPTED_SHORT_WORDS` (`id`, `db`, `url`, `api`, `cli`, `csv`,
  `sql`, `git`, `run`, `add`, `get`, `set`, `key`, `max`, `min`, `end`, `row`,
  `col`, `tag`, `ref`, `sha`, `cls`, `app`, `pid`, `iso`, `out`, `err`, `log`,
  `top`, `low`, `raw`, `hop`, `job`, `gap`, `seq`, `pct`, `sum`, `ago`, `now`,
  `new`, `old`, `lhs`, `rhs`) or in `ENGLISH_SHORT_WORDS` (`is`, `to`, `in`,
  `on`, `by`, `as`, `at`, `of`, `or`, `no`, `up`, `do`, `if`, `go`, `ok`,
  `an`, `be`, `it`, `so`, `we`, `and`, `any`, `all`, `for`, `has`, `not`,
  `one`, `per`, `two`, `use`, `via`, `own`, `the`, `off`, `map`, `can`, `how`,
  `who`, `why`, `was`, `are`, `few`, `bit`, `day`, `its`) passes.
- A part made only of digits (`120` in `over_120_characters`) is skipped.
- Any other part of one or two letters fails; any other part of three
  letters fails. `args` is four letters and passes.

Both tuples live at the top of `detect.py`; widen them there, with a test.

Block message: `short-name: this edit introduces N abbreviated or short
name(s) in <path>. Names are spelled out (datadog not dd, config not cfg,
epoch_seconds not ts); ...` followed by one line per hit, for example
`function ts (line 1) 'ts' is 2 letter(s); spell the name out`.

Fail direction: three outcomes, not two. A result that does not parse, a
missing file for an Edit, an `old_string` not in the file, a file over the
size cap, or a file that is not UTF-8 is reported as **unchecked** (rule
`short-name.unchecked`): the names are not judged, the reason is printed to
stderr, and the event row records `unchecked`. A new file with a bad stem
still blocks even when its body does not parse. Garbage on stdin fails open
through the SDK with no output.

The rule this enforces is the cat-mode prose rule "Names are never
abbreviated or diminutive" in
`corpus/skills/cat-mode/references/prose-and-scope.md`.

Tests: `python3 -m unittest discover -s engine/hooks/short-name/tests -v`
