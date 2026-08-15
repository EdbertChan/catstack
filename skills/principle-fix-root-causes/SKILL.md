---
name: principle-fix-root-causes
description: "Apply when debugging. Trace each symptom to its root cause and fix it there; reproduce first, ask why until you reach it, resist nil-check guards that silence crashes."
disable-model-invocation: true
---

# Fix Root Causes

When debugging, do not paper over symptoms. Trace every problem to its root cause and fix it there.

**Why:** Symptom fixes accumulate. Each workaround makes the system harder to reason about, and the real bug remains. Root-cause fixes are slower upfront but reduce total debugging time.

**Pattern:**
- Reproduce first (if you can't reproduce it, you can't verify your fix)
- Ask "why" until you hit the root cause
- Resist the urge to add guards (adding a nil check to silence a crash is a symptom fix)
- If a workaround needs a paragraph-long comment to justify it, the code is wrong (fix the code, not the comment)
- Check for the pattern, not just the instance (grep for the same pattern, fix all instances)
- When stuck, instrument. Don't guess (add logging, read the actual error)
- Trust the real command's exit code, not a pipeline's: `cmd | tail` returns `tail`'s exit status, silently masking `cmd`'s failure. Check the actual command's exit code (or `$PIPESTATUS`) directly, especially before an irreversible action like a force-push
- Read the commit history before re-deriving from scratch: `git log -p --follow -- <file>` or `git blame` on the affected lines often shows *why* the code looks the way it does — a prior fix for this exact bug, a deliberate workaround, or a past commit (your own, if it's `Co-Authored-By: Claude`) that introduced the problem. History that already explains the "why" is cheaper evidence than re-guessing it
- A decision you already made isn't automatically right for the next case that looks like it: re-derive the justification, don't just cite the shape. "Same approach as [the earlier instance]" is not itself a reason — check whether the specific thing that made the earlier call okay (or not) actually still holds here

**Restart bugs: suspect state before code**

Code doesn't change between runs. State does. When something "fails after restart," suspect stale persistent state first: config files, caches, lock files, serialized state. If clearing a state file restores behavior, prioritize state validation as the fix.

**When the root-cause fix isn't shippable in one slice:** don't block on it. A worker-starvation bug's real fix might be a 5-part migration you can only land one part of today. Surface the gap explicitly, offer a bounded stopgap (stagger, backoff, rate-limit) that buys safe time, and label it "interim" or "mitigation" in the plan doc — not "fixed" — so it isn't mistaken for done and the remaining parts don't silently vanish.

**Battle-tested:** a corpus retrospective found a session where `git rebase | tail` swallowed the rebase's real exit code — the pipe reported `tail`'s success, not the rebase's failure on a leftover conflicted index — and the session force-pushed on top of it. Caught on the very next status check and rebuilt the branch via cherry-pick before anything bad reached the shared branch, but it was a real near-miss, not a hypothetical one: the actual command's exit status, not its pipeline's, was the root cause the whole time.

**Battle-tested (precedent without re-derivation):** while building a stop-hook feature for a repo whose own install script says "same command on every machine," a script's path got hardcoded to this machine's real absolute path, justified in the moment as "it's fine since this whole install is per-machine anyway" — true of a different, untracked config file, not of the git-tracked script actually being written. Minutes later, a second file needed the same kind of path; the entire justification for reusing the identical hardcoded-path pattern was "same approach already used for [the first file]" — no re-check of whether the original reasoning (already wrong) still applied. The user caught the second instance before it was committed; the first had already reached git history. The root cause wasn't "typing a path" twice — it was letting "I did this already" stand in for "this was correct," both times.
