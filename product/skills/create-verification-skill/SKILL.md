---
name: create-verification-skill
description: >-
  Generate a project-local verification skill that drives the repo's real app
  the way a user does (web, CLI/TUI, desktop, API) and captures proof. Use for
  /create-verification-skill, "make a control skill for this repo", "how do I
  prove this UI/CLI/service works", or when a project has no scripted way to
  launch the app and show a feature working.
---

# Create a verification skill

Adapted from `create-verification-skill` in the `pstack` plugin of
[cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack/skills/create-verification-skill)
(MIT, Lauren Tan). Changes: the output is linked into all four harnesses (not
Cursor only), the skill can be invoked by description, and the evidence
standard adds catstack's fail-before/pass-after and three-outcome rules.

Every serious project needs a scripted way to drive the real app and prove
behavior: launch it, use a feature the way a user would, and capture evidence.
This skill generates that as a project-local skill, `verify-<app>`, tailored to
the repo. The reader is the next agent, who arrives cold, mid-task, having
never seen the app.

## 1. Interview the repo, not the user

Answer these from the codebase. Ask the user only what you cannot observe.

- **Surface:** what does a user touch? A web UI, a CLI/TUI, a desktop app, an
  API, a mobile app, a library? A repo can have several; pick the primary one
  and note the rest.
- **Run:** how does the app start locally? Use the repo's own documented
  command (package scripts, Makefile, README quickstart). Note ports, env
  vars, seed data, auth.
- **Drive:** how can an agent interact with it? Existing harnesses first
  (Playwright/Cypress specs, expect scripts, PTY helpers, curl-able
  endpoints, a debug port). Then a generic recipe: browser/CDP for web and
  Electron, a tmux/PTY harness for CLI/TUI, plain HTTP for services.
- **Observe:** what evidence can be captured? Screenshots, terminal
  transcripts, response bodies, logs, exit codes, database state.
- **Isolate:** can two instances run side by side (ports, data dirs,
  profiles)? If not, say so in the generated skill. Refusing to double-drive a
  shared instance beats corrupting the user's session.

If the checkout does not build or start as-is, fix that first or report it
precisely before generating. A skill written against a broken base teaches
wrong steps. When an irrelevant missing asset blocks startup (a static dir the
API never serves, a sample config), the generated skill may create it, marked
as verification scaffolding, and remove it in cleanup.

## 2. Generate the skill

Write `<repo>/.cursor/skills/verify-<app>/SKILL.md` with YAML frontmatter
(`name: verify-<app>` and a `description` naming the app, the surface, and when
to reach for it; without frontmatter the skill never registers). Do not add
`disable-model-invocation`. Sections, each grounded in what the interview
found, with no placeholders left:

- **Launch:** the exact command that starts the app for verification, and how
  to tell it is ready (a log line, a prompt). Launch must reach a usable state
  from an empty data dir, including migrations and seed data. Ready means
  usable, not just that a process answers: a database health check can pass
  while its init scripts still run. Include teardown. A short-lived CLI or TUI
  has no server to keep alive: launch means build the binary (or install deps)
  once, then start each drive in its own isolated PTY or tmux session.
- **Doctor:** one read-only check that answers "is this instance worth
  driving?": process up, right version or build, port owned by us, auth valid.
  An agent runs this first whenever anything looks off.
- **Drive:** the harness recipe with real selectors and commands from this
  repo, not examples. Prefer stable handles (ARIA labels, data attributes,
  prompt strings, route paths) over coordinates and tab order.
- **Evidence:** what to capture and where it goes. Proof standards:
  - Exercise the real user path, not internal setters or test-only endpoints.
  - Capture the action and the resulting state, not just the final screen.
  - Verify side effects (files written, rows inserted, messages sent) next to
    what is visible.
  - Mock only where a production boundary already isolates the external
    system.
  - When the safe path is a dry run or test mode, observe what it actually
    skips (files, network, git refs) instead of trusting its name.
  - For a bug fix, show the journey FAILING before the change and PASSING
    after, both outputs saved. A journey that only passes proves nothing.
  - Give every check three outcomes: pass, fail, unchecked. A step that could
    not run (missing precondition, unreadable output, errored probe) reports
    unchecked with the reason. It never reports pass.
- **Cleanup:** how to tear down instances the run created. Never kill by
  process name; kill what you started. Cleanup removes instances and scratch
  state, never the evidence: proof artifacts survive teardown, in a location
  the skill names.
- **Helpers:** any script the skill ships is executable and its invocation is
  shown in the skill body. A helper the reader must reverse-engineer is not a
  helper.

## 3. Seed the feature map

Create `<repo>/.cursor/skills/verify-<app>/features/README.md` plus one file
per user-facing feature you can find (start with the top 3-5, from routes,
commands, menus, or docs). Follow the shape in
[`references/fixtures/feature-map-example/`](references/fixtures/feature-map-example/): a README
index and one file per feature. Each feature file answers, from the user's
point of view: what the feature is, how to reach it, how to drive it with the
harness, and what end state proves it works. Its four H2s are `Sub-features`,
`How to get to it (user POV)`, `Driving it with <harness>`, and `Gotchas`.

If the seed data lacks a precondition a journey needs, the journey reports a
failure (or unchecked) and the reason goes in that feature's `Gotchas`. Never
weaken the journey to make it pass. The map is the repo's maintained
verification source; a proof that drives one convenient entry point is
incomplete when the map lists others.

## 4. Prove the generated skill before handing it over

Run its own instructions end to end once: launch, doctor, drive ONE mapped
feature, capture evidence, clean up. After cleanup, confirm the evidence still
exists at the named location. A cleanup that eats the proof fails this step.
Fix what fails, and run the generated cleanup after every failed attempt so
broken attempts do not strand processes and ports. A generated skill that was
never executed is a draft, not a deliverable.

If you proved it in a stand-in for the real target (a container in place of a
fresh VM, a local stack in place of a remote one), list every setup step the
stand-in did that the target will not. Those steps stay unverified until a run
on the real target covers them.

## 5. Install it for every harness

The generated skill lives in the project. Link it into all four personal
skill roots in one step, never into one or two:

```bash
bash scripts/install/link_skill_three_harnesses.sh <repo>/.cursor/skills/verify-<app>
```

Run that from the catstack checkout. Then run
`python3 scripts/ci/check_skills_three_harnesses.py --home` there and read the
result.

## 6. Keep the map honest

Tell the user the feature map goes stale as the app changes, and offer to
re-run steps 1-4 against the current repo when they say it has. Suggest a
cadence only if they ask.
