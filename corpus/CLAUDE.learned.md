Rules mined by reflect.
Engine-only install drops this file; reflect Accepted global rules land here.

# Evidence rules (apply everywhere, every project)

- Absence of a field in a projection (CLI, MCP, or API output) is not proof of absent state. Say "not projected" and find the emitter before retrying, resubmitting, or switching agents.
- When delegating a file-finding task to a subagent and two files could plausibly hold the same answer (a duplicate, a moved file, a same-named symbol in two packages), tell the subagent to state whether each file:line claim is "read-confirmed" (it opened the actual reference/import and traced it) or "name-matched" (it assumes the file is the one in use because the name/path looked right). A subagent that reasons by name-proximity instead of tracing the real reference can hand back a confident wrong file — a judgment call about how the subagent qualifies its own confidence, not something a mechanical check can catch.
- A `file:line` citation, mine or a subagent's, also names the ref it was read at: working tree, `HEAD`, `origin/<base>`, or the installed bundle. A working-tree read in a checkout with untracked or modified files under the cited path is name-matched, not read-confirmed, until the same line is shown at the ref the change will actually run on. Subagent prompts that ask for read-confirmed vs name-matched must also ask for the ref.
- When a pipeline switches from test/synthetic inputs to my real inputs, re-derive or explicitly re-validate every artifact built under the old conditions — voice clones, cached device lists, presigned URLs, browser sessions that predate a driver install. State which artifacts were rebuilt and which were kept.

# Session hygiene (apply everywhere, every project)

- When a session pivots to a genuinely unrelated task (a different incident, a different deliverable, nothing left in common with what came before), suggest a `/clear` or a fresh session before starting the new work, rather than letting one long session carry unrelated context forward silently.
- When I pivot off an in-flight plan, immediately park the partial tree (`git stash push -u -m "abandoned: <plan>"` or a WIP branch) and tell me where it went — never leave a mixed broken working tree silently.

# Live-demo rules (apply everywhere — any time I am physically in the loop: testing, filming, or on a live call)

- The moment I offer to join/test/film, treat it as a deadline commitment: pre-stage everything testable and pre-raise any service idle/silence timeouts that could kill the session while I'm still setting up.

# Named constraints (apply everywhere)

- A typed `/name` reported "not available" is unverified, not proof of absence. `disable-model-invocation: true` removes a skill from that turn's available-skills listing entirely — including explicit `/name` invocation, not just auto-trigger — so the Skill tool has nothing to match and reports it missing even though the skill is real. Before concluding a typed `/name` doesn't exist: check `~/.claude/skills/<name>/SKILL.md` on disk (or `~/.claude/commands/`) and, if found, read and apply it directly instead of the Skill tool. This rule must live in an always-loaded surface, never inside the skill it protects — a skill's own SKILL.md is exactly what's unreadable when this bug fires, so a fix written only there can never self-rescue.

# Working style (apply everywhere, every project)

- After an audit that names existing scorers, rankers, or weight formulas, the next plan picks among those named gaps. Bind "real classifier" / "these weights are arbitrary" onto a named scorer before proposing a new model or library. If I say I'm not comfortable with ML, teach the existing named scorers first and offer a no-library path before sklearn.
- When a permission classifier or sandbox denies a tool call, treat the first denial as categorical for that target — don't retry the same blocked action through a different tool (Bash → Edit → a different Bash invocation). Switch strategy immediately.
- When handing off a blocked action for me to run myself, always write it to a small script file and hand back exactly one `! bash <path>` / `! python3 <path>` line — never paste inline multi-line, multi-flag, or `&&`/`&`-backgrounded shell text into chat for me to copy. This applies on the very first handoff, not after I complain about copy-paste pain.
