---
name: code-naming
description: >
  Code conventions for names, file layout, docstrings and the source of truth.
  Use when writing or reviewing code, when a review comment asks what a name
  means or why a thing exists, when a docstring or comment explains how the
  code works, when a helper sits outside its owning class, or when a value is
  parsed out of a string, read from a file, or taken from a built-in default
  instead of read from where it is stored.
---

# Code naming and layout

Four rules for code in any repo. Each one puts the meaning where the reader
looks first: the name, the file, the first line of the docstring, the stored
column.

## No short or cute names, ever

- A name is spelled out in full. A two-letter name is wrong; a three-letter
  name has to be a real word (`datadog_steps_loader` not `dd`, `config` not
  `cfg`, `query_params` not `q`, `trigger` not `trig`, `job_family_names`
  not `F`).
- A name carries the domain concept, so the reader never opens the body to
  learn what it holds: a class is named for the thing it models with its
  vendor or domain in the name (`GitlabCiYaml`, `PipelineDependencyGraph`,
  `RequestBudget`), never a generic private class (`_Loader`, `_Pool`); a
  function is a verb plus its object (`parse_yaml`, `run_git_checkout`).
- A route, page key or JSON key says what it returns, so a reader of the
  path alone knows the payload.
- A constant says why it exists, with its role in the name
  (`ERROR_FILE_UNREADABLE_REASON`, `STEP_DURATION_SECONDS`), never a bare
  value name.
- A legend that maps short names to their meanings at the top of a file is
  the sign that the long names belong in the code; rename instead of
  explaining.
- A review comment that asks what a name means is a rename request. Do the
  rename in the same pass, across the whole branch, and say so.

Grounding: John Ousterhout, *A Philosophy of Software Design*, 2018, ch. 14
"Choosing Names", https://web.stanford.edu/~ouster/cgi-bin/book.php.

## File equals class, helpers as methods

- A file holds one class and is named after it (`GitLabRawSource` lives in
  `gitlab_raw_source.py`).
- Every helper function is a method on the file's owning class; only
  `main()` and its argument parser stay at module level as the driver.
  Module-level constants and compiled patterns may stay.
- Test helpers follow the same rule: they live in the test class, not as
  loose functions beside it.
- A database schema (table and index creation) lives in its own file, not
  inline in the class that uses it.

## Docstrings: one idea, one line, what not how

- A docstring is one line that says what the thing is for.
- No docstring or comment describes how the code works. Retry counts, wait
  sequences, loop order and similar mechanics live in the code; a reader who
  needs them reads the code.
- No `#` inline comments and no multi-line block comments.
- The one exception is a class docstring that describes, one idea per line,
  the structure the class walks or models (the shape of a pipeline graph, the
  layers of a config file). It says what the structure is, not what the code
  does with it.

## Source of truth, never string parsing

- An identity field (a job kind, a family, a base name) is a stored column
  derived from the source when the row is written, never recovered later by
  regex or string splitting over another field.
- A layer above the source reads the database, not files; a path that
  bypasses the store to read a file is a layering bug. Dependencies point one
  way, toward the layer that owns the data. Grounding: Robert C. Martin,
  "The Clean Architecture", 2012, the Dependency Rule,
  https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html.
- No built-in host, project or window default in the code (no hardcoded
  GitLab host, no `DEFAULT_PROJECT`, no `_6h` baked into a name); every such
  value comes from configuration. Grounding: Adam Wiggins, *The Twelve-Factor
  App*, 2011, III. Config, https://12factor.net/config.
- Runtime data (databases, caches, fetched pages) lives in a per-user
  directory outside the checkout, so the repo's ignore rules never change to
  hide it.
