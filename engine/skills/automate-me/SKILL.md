---
name: automate-me
description: Mine session history for durable working-style preferences and turn them into one personal "<handle>-mode" skill agents will follow. Use when the user says "automate me," asks to capture how they work into a skill, wants an existing mode skill updated or refreshed, or when reflect surfaces a recurring personal-preference pattern (not a code lesson) across sessions. Must invoke — do not wait — when the user had to restate a named constraint, keep iterating, or change product direction because the agent missed it, or when the same complaint type appears twice.
disable-model-invocation: true
---

# Automate me

Mine your own session history for durable working-style preferences, then turn the real ones into one personal `<handle>-mode` skill — never silently.

Adapted from `pstack`'s `automate-me` (cursor/plugins), rewritten for Claude Code the same way `reflect` was: transcripts live under `~/.claude/projects/`, mining fan-out uses the `Agent` tool, and there's no `AskQuestion` / `create-skill` / `unslop` built-in to lean on — `AskUserQuestion` replaces the first, the parent writes the skill file directly in place of the second, and catstack's own `principle-minimize-reader-load` / `principle-subtract-before-you-add` stand in for the third (no `unslop` equivalent exists in this stack).

This skill doesn't invent new mining machinery — it reuses `reflect`'s transcript lookup and corpus-scan tooling, which is already built and hardened.

## When to invoke

- The user says "automate me" or asks to capture how they work into a skill.
- The user asks to update or refresh an existing `<handle>-mode` skill.
- `reflect` (single-session or corpus mode) surfaces a finding about the user's working style or preferences, not a code lesson — that gets routed here instead of an inline skill edit (see `reflect`'s synthesis step).
- A session, or a corpus-scan bucket, shows heavy user involvement — many corrections, clarifying answers typed out by hand, repeated manual confirmations — over a short span. That is the trigger, not a style note: the user stayed in the loop because the agent missed a named constraint. **Must invoke this skill** — do not wait for the user to say "automate me."
- `token_audit.py` flagged `intervention-must-automate: yes`, or the same *type* of complaint appeared twice (session or corpus): ignored named verb, skipped repro-then-fix, skipped UI/`visual-proof` before done, claimed pass without e2e/test. Must invoke. Genuine mind-change after new facts is not this class. Product-blame ("the UI is messed up") is not agent-blame.

## 0. Check for an existing mode skill

Look for `corpus/skills/<handle>-mode/SKILL.md` in this repo (catstack is the canonical home for this user's own skills — see README) and, as a fallback, `~/.claude/corpus/skills/<handle>-mode/SKILL.md` in case one was ever created ad hoc outside catstack. If one exists, confirm intent with `AskUserQuestion` unless the user already said "update my skill" or similar:

- Update the existing skill (default for repeat runs)
- Start fresh (rare; ask why before doing it)

Update mode changes the rest of the flow:
- Step 1 mines only history since the skill was last edited (`git log -1 --format=%cI -- corpus/skills/<handle>-mode/SKILL.md`).
- Step 2 asks what's changed or missing, not what to capture from zero.
- Step 4 edits the existing file in place: preserve sections the user hasn't contradicted, revise ones with new evidence, add new sections only for genuinely new rules.

## 1. Mine their history

Reuse `reflect`'s tooling instead of rebuilding it:

- **Single-project scope**: `reflect`'s step-1 lookup rule (`~/.claude/projects/<encoded-cwd>/*.jsonl`, most recent file, or every file since the mode skill's last edit in update mode).
- **Cross-session, cross-machine scope** ("based on all our sessions"): `engine/skills/reflect/scripts/corpus_scan.py` in time-windowed mode — e.g. `python3 engine/skills/reflect/scripts/corpus_scan.py ".*" --hours 168` for a week-wide sweep, or a narrower keyword when the user names a topic. This is the one piece upstream `automate-me` didn't have; it only ever saw one Cursor workspace. Add `--include-remote` per `reflect`'s existing remote-scan policy (show the exact command once, only scan after explicit confirmation) if other machines should count too.

Run parallel `Agent` mining passes over slices of the results (e.g. by time window) rather than one pass over everything. Each slice agent reads its assigned transcripts and returns a short structured list of patterns with evidence pointers — a quote, a `file:line`, a session path — not a pre-digested "here's what's interesting" summary; priming narrows what gets found to what was already suspected. Default signals to hunt, same as upstream:

- Response preferences (length, tone, format, "dumb it down" corrections)
- Delegation habits (subagents, models, specialized workflows, parallelism)
- Verification posture (what "done" means; tests vs. live repro; reviewers)
- Code and prose discipline (style, principles cited, lint/format tools)
- Process conventions (worktrees, commits, PRs, review/merge tooling).
  Especially: after shippable verified work, does the user keep saying
  "make a pr" / "make a pr stack" because the agent stopped at commit/push?
  That is a Process default to codify (auto-run `make-pr`/`draft-pr`), not
  a one-off reminder.
- Meta preferences (fixing skills mid-task, proposing new ones)
- **Heavy-involvement moments** — turns where the user answered several clarifying questions in a row, corrected the same kind of mistake more than once, or manually did something an agent could have inferred. Same-type twice is already a must-invoke; mine it into a named rule, not a one-off apology. Each one is a candidate preference to capture, not a candidate script — that's `reflect`'s Tooling lens's job, not this skill's.

Cross-check across slices before elevating a signal. A pattern seen in 2+ slices (or 2+ sessions in corpus mode) is high-confidence; a lone signal is weak and usually gets dropped.

## 2. Ask the user directly

Mining misses intent that hasn't come up yet. Use `AskUserQuestion` (structured multi-choice, up to 4 questions per call, `multiSelect: true` for category questions) rather than asking the user to type from scratch — lower cognitive load, higher hit rate.

Shape: one or two rounds of grouped questions, then one open-ended question in plain chat to catch anything the options missed. Don't dump every possible option; two structured rounds plus one open question is usually enough.

## 3. Cluster findings

Group the combined signals (mined + asked) into sections. Use only what applies — don't force symmetry:

- **Response style**: length, tone, format.
- **Autonomy**: how much to do without asking; tool use.
- **Understand first**: which skills to reach for when scoping or investigating a change.
- **Subagents**: default, parallelism, model-to-task, specialized workflows.
- **Prose / code discipline**: principles, lint tools, style guides.
- **Review and verify**: repro posture, verification skills, live-testing tools.
- **Process**: worktrees, commits, PRs, review/merge tooling.
- **Skills**: skill-authoring habits, fix-the-skill-first, proposing new skills.

## 4. Draft the skill

No `create-skill` built-in here — write `corpus/skills/<handle>-mode/SKILL.md` directly, following the same trivial-vs-substantive distinction `reflect` uses for its own edits: a corrected fact or tightened sentence gets edited in place; a new section or genuinely new rule gets written out in full and shown as a diff before it's considered done.

- Path: `corpus/skills/<handle>-mode/SKILL.md` in this repo, so `install.sh` symlinks it out like every other skill.
- Handle: the user's first name or chosen identifier.
- Frontmatter `description`: trigger on their name + "work in their style," not generic keywords like "write code" or "review PR."
- Frontmatter `disable-model-invocation: true` by default — mode skills are heavy and opinionated; they should apply only when explicitly invoked, not auto-trigger on description matching. Opt out only if the user explicitly wants it applied on every turn.
- This skill, and its produced `<handle>-mode` skill, depend on `~/.claude/projects/` transcript layout and Claude-specific tools — both are Claude-only, like `reflect`, and belong in `install.sh`'s `CLAUDE_ONLY_SKILLS` list.

## 5. Iterate on prose

No `unslop` skill exists in this stack. In its place, apply catstack's own `principle-minimize-reader-load` and `principle-subtract-before-you-add` to every line — cut anything that isn't an operational, non-default rule. "Communicate clearly" is not a section; "Short paragraphs, tables when comparing options, bullets only when items are genuinely parallel" is.

Show the draft to the user and take feedback. Expect multiple iterations. Cut ruthlessly — a mode skill is not a manual.

## 6. Land it

Commit and open a PR so the user reviews the diff before it's live everywhere `install.sh` has run.

## Guardrails

- **Don't overfit to one conversation.** A preference stated once and contradicted another time is noise. Require multiple instances before codifying it.
- **Don't be clever.** Restating other skills' contents, inventing metaphors, or writing "poetic" prose for an agent reader is cost without benefit. Keep it operational.
- **Reference, don't inline.** Other skills the user relies on (e.g. `diu`, `land-stack`, the `principle-*` set) should appear as path references, not pasted excerpts.
- **Keep sections minimal.** Sparse is fine; bloated is not.
- **Name conventions generic.** Use "the user" in imperatives inside the produced skill, not the person's first name — others may read or adopt it.
- **Don't force symmetry.** If the user has no process rules worth writing down, skip the Process section entirely.
- **No dates or incident narrative in the produced rule text.** Mining evidence (a quote, a `file:line`, a session path, a calendar date) earns a signal the right to be cross-checked and elevated — it does not earn a place in the shipped skill. Write the rule as a standing, dateless instruction only; drop "Found via `/reflect` on <date>: <story>" and similar provenance clauses entirely, including from an existing mode skill being updated. If the user wants provenance kept somewhere, that's a separate log file, not the rule text agents load every turn.

## Evaluation

A `-mode` skill is subjective output — there's no automated benchmark for it. Vibe-check with the user: does it read like them? Did it miss anything? Then ship. Only chase description-trigger accuracy if it turns out to misfire in practice.

## When not to use

- The user wants a task-specific skill, not working conventions — write that skill directly, no mining needed.
- The user wants to capture one narrow workflow (e.g. "how I write commit messages") — that's a regular skill, not a mode skill.
- The user wants a one-off learning applied right now — that's plain `reflect`, not this.
