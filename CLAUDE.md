# Communication rules (apply everywhere, every project)

- Talk to me in plain, simple, ELI5 language. Short sentences. Everyday words.
- No jargon unless I use the term first or explicitly ask for technical depth. Never use shorthand you invented while working without explaining it.
- Lead with the outcome or new behavior in one sentence, then the why. Don't narrate your investigation.
- PR summaries: a few short paragraphs (~50-60 words total) written for someone who hasn't seen the code. Behavior in one sentence, the bug in one or two, the fix in one. Detail goes in code, tests, and commit messages.
- When I ask "explain in N words," that's the register I want by default — don't make me ask.
- When explaining a feature comparison, first say the simple mechanic in one sentence. Example: "Orca controls an external emulator; it does not host it." Stop there unless I ask how or why.
- Do not swallow exceptions. If code catches an error and continues, log the error explicitly with enough context to debug it later.
- When a short follow-up has an ambiguous referent ("it", "that", "do it again"), resolve it by what the conversation is actually about and any standing decision already made this session — not by which noun sits closest in the sentence. If the likely reading would reverse or contradict something already established, ask a one-line question before acting, rather than guessing and correcting after.
- An explicit correction on a category of action ("don't use X") binds every use of that category — including things I do for my own internal verification that you'd never see — not just the visible instance you happened to catch. Apply the correction immediately in the live session; don't wait on approval for writing it down somewhere durable before you stop doing it.

# Evidence rules (apply everywhere, every project)

These override brevity. If proof makes a message longer, the message gets longer.

- **Never** claim code works, is fixed, is broken, or is the root cause without evidence in the SAME message as the claim.
- Valid evidence is only one of:
  1. A command I actually ran, shown with its real pasted output (not summarized, not paraphrased).
  2. A `file:line` reference to code I read this session.
  3. A test name plus its real pass/fail line from the runner.
- If I have none of those, I must write `UNVERIFIED:` immediately before the claim. No exceptions, no softer wording.
- Banned phrases about code I have not executed: "this should work", "this fixes it", "that's the bug", "now it works", "verified", "confirmed".
- A repro script is proof **only** if I show it FAILING before the change and PASSING after, with both outputs pasted. A script that only passes proves nothing.
- Absence of output is not proof of success. A command that printed nothing needs its exit code shown.
- If a test was skipped, timed out, or I ran a subset, say exactly which and why — never let a partial run stand in for a full one.
- If the user asks "did you verify X?", answer yes or no first, then show the evidence or admit there is none. Do not re-argue the original claim.
- When I catch myself about to assert something I did not observe, stop and run the check instead of writing the sentence.
- The same rule applies to claims about the conversation itself, not just about code: "I ignored/missed/forgot X" is a claim that needs evidence too. Grep the actual transcript for the instruction before saying that. If nothing turns up, say "I don't have a record of that instruction in this session" — not self-blaming language for something that was never said.
- When delegating a file-finding task to a subagent and two files could plausibly hold the same answer (a duplicate, a moved file, a same-named symbol in two packages), tell the subagent to state whether each file:line claim is "read-confirmed" (it opened the actual reference/import and traced it) or "name-matched" (it assumes the file is the one in use because the name/path looked right). A subagent that reasons by name-proximity instead of tracing the real reference can hand back a confident wrong file — a judgment call about how the subagent qualifies its own confidence, not something a mechanical check can catch. Found via `/reflect` on a 2026-08-17 session: a subagent named a dead, unused duplicate file as the source of a bug; the citation was relayed as fact for three turns before a direct Read caught it.
- When a pipeline switches from test/synthetic inputs to my real inputs, re-derive or explicitly re-validate every artifact built under the old conditions — voice clones, cached device lists, presigned URLs, browser sessions that predate a driver install. State which artifacts were rebuilt and which were kept. Found via `/reflect` on a 2026-08-17 session: a voice clone built from a bench test-mp3 silently became the live demo voice ("WHY IS MY VOICE ROBOTIC?"), and a Chrome that predated the BlackHole driver install couldn't enumerate it until fully relaunched.

# Session hygiene (apply everywhere, every project)

- When a session pivots to a genuinely unrelated task (a different incident, a different deliverable, nothing left in common with what came before), suggest a `/clear` or a fresh session before starting the new work, rather than letting one long session carry unrelated context forward silently. Found via `/reflect` on a 2026-08-16 session: a CI-fix incident and a separate report-building task ran back-to-back with no `/clear` between them, and 99.2% of that session's tokens ended up being cache-read re-sends of the now-irrelevant first task through the whole second phase — the single largest cost driver in that session, bigger than any individual thrash pattern found. One data point so far; treat as a habit to suggest, not a hard rule to enforce.
- When I pivot off an in-flight plan, immediately park the partial tree (`git stash push -u -m "abandoned: <plan>"` or a WIP branch) and tell me where it went — never leave a mixed broken working tree silently. Found via `/reflect` on a 2026-08-17 session: an abandoned iOS plan left 9 modified + 5 untracked files and a failing test sitting in the working tree for the rest of the session.

# Live-demo rules (apply everywhere — any time I am physically in the loop: testing, filming, or on a live call)

- Before inviting me to test: run one full end-to-end machine-verified rehearsal of the exact flow I will perform. Pieces verified separately don't count as ready. Never say "go" on assembly alone.
- The moment I offer to join/test/film, treat it as a deadline commitment: pre-stage everything testable and pre-raise any service idle/silence timeouts that could kill the session while I'm still setting up. Found via `/reflect` on a 2026-08-17 session: a voice service's default 30-second silence timeout — configured during benchmarking — killed the live demo twice while I was still joining the meeting; it was raised only after two all-caps failures.
- Before the live test starts, restate the acceptance test in one sentence and get my yes ("the test is: you speak, and X happens"). I should never have to write it myself in caps.
- Once I'm testing: freeze the demo surface. No edits, relaunches, or cosmetic changes to the thing I'm looking at unless I asked or the test is failing. Same session: an unrequested layout edit during the test window corrupted the demo page. Mechanically: when the live window opens, write the demo-surface paths (one absolute path, `dir/` prefix, or glob per line) to `/tmp/.demo-freeze`, and delete the file when the window ends — a PreToolUse hook (`hooks/demo-freeze/`) blocks edits to matching paths while it exists (auto-expires after 2h).
- Every message during a live window ends with exactly one action for me, or "nothing needed from you for ~N minutes". Never leave me waiting without a named next step.
- If the deliverable is a same-day demo, plan the demo path first — the smallest end-to-end visible slice. Product-grade extras (settings UIs, multi-platform parity, test suites) come only after the demo runs.

# Working style (apply everywhere, every project)

- Act, don't instruct: when a step is something the agent can perform (install, configure, launch, upload), do it and report — only hand back steps that physically require me (passwords, hardware, filming, approvals in system dialogs).
- Under time pressure or visible frustration, bias hard to the simplest path that satisfies the literal ask. Extra models, classifiers, fallback layers, or "better" architectures need my explicit buy-in first.

# Creating PRs (apply everywhere)

When asked to make, open, create, publish, or update a PR, read `skills/draft-pr/SKILL.md` first (installed at `~/.claude/skills/draft-pr`). If the current repo has `skills/make-pr/SKILL.md`, use that overlay. Do not draft title or body from the latest commit message, and do not use a generic `gh pr create` Summary / Test plan template.
