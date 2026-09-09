# playbook-router

Fail-open Claude Code `UserPromptSubmit` injector, shaped like
`cat-mode-default`. No LLM, network calls, denial, or output on a non-match.
`install.sh` links the hook and merges its settings fragment idempotently.

## Discovery convention

Registration means a file exists in a conventional location, not an entry
in a router-owned registry. Each prompt discovers:

- Installed `~/.claude/skills/*/SKILL.md` entry files.
- The session repository's `.claude/skills/*/SKILL.md` and
  `{engine,corpus,product}/skills/*/SKILL.md` entry files.
- Standalone `<session repository>/playbooks/*.md` files.

The repository is the nearest ancestor of the payload's `cwd` with a `.git`
file or directory; absent `cwd`, the process directory is used. Symlinks
are followed and identical resolved paths count once.

A procedure has a `## Steps` section containing top-level numbered items,
consecutively numbered from 1. Its name comes from the skill directory or
standalone filename. Names use lowercase letters, digits, and hyphens.
No frontmatter or router-specific declaration is required. Add a new file
under these roots and the next prompt discovers it without a router edit
or reinstall.

Nested `skills/*/playbooks/*.md` files are reference material, outside this
convention. The two existing split-scope playbooks remain untouched and
cannot route, even if a reference acquires a `## Steps` section.

## Matching and output

The prompt must start with the full name, `/name`, or its space-separated
form, optionally preceded by `please` and `run`, `use`, or `follow` (and
`the` after those verbs). Matching ignores case. Examples for `land-stack`:

- `Please run land-stack for PRs 12 and 13.` routes.
- `land stack` and `/land-stack` route.
- `Explain land-stack`, `Do not land-stack`, and `land-stack-extra` do not.
- `Merge those PRs` does not route: no synonym inference or fuzzy matching.

A playbook may optionally replace its default phrase with one literal
frontmatter value: `playbook-trigger: "repair the broken widget"`. The value
is either unquoted text or a JSON-quoted string, with at least two words
containing only letters, digits, spaces, or hyphens. `/name` remains an
explicit invocation. Regex triggers and trigger lists are unsupported.

Exactly one matching procedure injects its source path and verbatim steps,
preserving nested bullets, code fences, and their order. Injection instructs
the agent to read the full source for constraints outside the steps.
Multiple matches stay silent; there is no arbitrary priority winner.

Malformed input, unreadable files, invalid numbering or trigger metadata,
and detector errors fail open. Unreadable or invalid candidates contribute
no match. Missing sections and unclosed fences also contribute no match.
The hook intentionally produces no diagnostics, matching the precedent.

## Verification

`python3 -m unittest discover -s engine/hooks/playbook-router/tests -v`
exercises the real entrypoint in an isolated home and repository. JSON
fixtures cover routing with ordered steps and unrelated-prompt silence.
This clone lacks `ship-a-detector`, so the positive fixture uses the
existing `product/skills/land-stack/SKILL.md` procedure.

Additional tests cover discovery after adding a file, installed symlinks,
reference exclusion, ambiguity, conservative matching, malformed input,
optional triggers, and installer idempotence. `tests/test_install.py` runs
the installed settings command and checks its positive and negative output.

## Files

- `detect.py`: discovery, procedure parsing, and matching.
- `claude_prompt_submit.py`: fail-open JSON entrypoint.
- `claude.prompt.hook.json`: Claude settings fragment.
- `install_claude_hook.py`: settings merge.
- `tests/test_hooks.py` and `tests/fixtures/*.json`: executable checks.
