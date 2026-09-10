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

A procedure's name comes from the skill directory or standalone filename.
Names use lowercase letters, digits, and hyphens. No frontmatter or
router-specific declaration is required. Add a new file under these roots
and the next prompt discovers it without a router edit or reinstall.

Steps are read in one of two shapes, each numbered consecutively from 1:

- A `## Steps` section of top-level numbered items. This is the only shape
  a `SKILL.md` can use, so a skill's numbered document sections never route.
- `## 1. Title` … `## N. Title` headings, accepted only in a file inside a
  `playbooks/` directory. Only the heading lines are injected.

A skill whose `SKILL.md` has no `## Steps` section may keep its procedure in
its own `playbooks/` directory. It routes under the skill's name when
exactly one file there parses as a procedure; that file's own name never
routes. `ship-a-detector` works this way through
`playbooks/detector-lifecycle.md`. `split-scope`'s two playbooks have
neither shape, so they stay reference material and `split scope` injects
nothing, with no edit to split-scope. If any file in a skill's `playbooks/`
cannot be read, the skill contributes no procedure: an unread file might be
a second procedure.

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

When copies with the same name match, the session repository's copy wins
over the installed one, so a checkout other than the one `install.sh`
linked still routes to its own files. Exactly one remaining procedure
injects its source paths and steps. List-shaped steps keep nested bullets,
code fences, and their order. Injection instructs the agent to read the
full source for constraints outside the steps. Two same-named copies in one
scope, or different names matching one prompt, stay silent; there is no
arbitrary priority winner.

Malformed input, unreadable files, invalid numbering or trigger metadata,
and detector errors fail open. Unreadable or invalid candidates contribute
no match. Missing sections and unclosed fences also contribute no match.
The hook intentionally produces no diagnostics, matching the precedent.

## Verification

`python3 -m unittest discover -s engine/hooks/playbook-router/tests -v`
exercises the real entrypoint in an isolated home and repository. JSON
fixtures install real skills by symlink, as `install.sh` does:
`fires_ship_a_detector.json` routes a prompt to `ship-a-detector` and pins
all 20 steps in order, `fires_land_stack.json` covers list-shaped steps,
`silent_unrelated.json` injects nothing with both installed,
`silent_ship_a_detector_neighbours.json` keeps near-miss prompts silent,
and `silent_reference_playbooks.json` keeps `split-scope` silent.

Additional tests cover discovery after adding a file, nested and standalone
heading playbooks, repository shadowing, reference exclusion, ambiguity,
conservative matching, malformed and unreadable input, optional triggers,
and installer idempotence. `tests/test_install.py` runs the installed
settings command and checks its positive and negative output.

## Files

- `detect.py`: discovery, procedure parsing, and matching.
- `claude_prompt_submit.py`: fail-open JSON entrypoint.
- `claude.prompt.hook.json`: Claude settings fragment.
- `install_claude_hook.py`: settings merge.
- `tests/test_hooks.py` and `tests/fixtures/*.json`: executable checks.
