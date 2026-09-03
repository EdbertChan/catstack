---
name: narrow-the-scope
description: >
  Notice live, mid-session, when repeated attempts at one problem aren't
  converging — the same error recurring, several edit-and-guess cycles on
  the same file or area, or a fix that keeps growing instead of landing —
  and say so out loud instead of quietly grinding on. Usually means the
  attempted scope is bigger than what's actually been verified to work;
  the fix is a smaller, checkable slice, not another full-scope guess.
  Trigger on: the same error text recurring across attempts, three or more
  edits to the same file without a passing test/build/lint run in between,
  or the user saying things like "still broken," "same error," "try
  again," "this isn't working."
---

# Narrow the Scope

Repeated failure on one problem is a sizing signal, not just a persistence problem. When the same error keeps coming back, or a file has been edited several times with nothing verified in between, that's usually evidence the change being attempted is bigger than the piece that's actually understood — not a reason to try harder at the same size.

**Why:** Guessing again at full scope after a failed attempt burns the same budget on the same blind spot. A smaller, verified slice turns up the actual constraint (the real error, the real edge case) in one cheap step instead of costing another full attempt to rediscover it.


## Mechanical trigger

The "three edits to one file with no check between" trigger is
counted for you by a PostToolUse hook, `engine/hooks/narrow-the-scope/`
(installed by `install.sh`). It injects a one-line reminder at the third edit
and resets on any test/build/lint command. When you see that reminder, this
skill applies: run the check, say it plainly, propose the smaller slice.

## Detect it live, don't eyeball it

This session's own transcript is a real transcript the moment it exists — `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` is being appended to as the conversation happens, so the same mechanical check `reflect` runs after the fact can run **during** the session, on itself. Don't rely on a fuzzy sense that "this feels like it's dragging" — check:

```
python3 skills/reflect/scripts/token_audit.py claude <most-recently-modified file in ~/.claude/projects/<encoded-cwd>/>
```

(same "most recent file in the project's transcript dir" rule `reflect` step 1 uses to find the current session without needing a session ID). Read off two numbers from its output:

- `recurring failure signatures: N` — the same-shaped error repeating across attempts.
- `longest edit streak with zero verification in between: N` — edits piling up on one file with nothing run to check them.

A non-zero count on either is the evidence to cite when raising this with the user — not "it feels like we're stuck," but "the same `ModuleNotFoundError` fired on attempts 2 and 4" or "`foo.py` has 5 edits in a row with no test run between them."

## What to do once it's confirmed

1. **Say it plainly, with the count.** Name what's been tried and how many times, using the numbers above — not a vague "this is taking a while."
2. **Stop guessing at full scope.** If the same error recurs identically, the current theory of the bug is probably wrong; re-diagnose before attempting another fix, don't retry the same fix with small variations.
3. **Propose the smaller slice**, concretely: reproduce the failure in isolation before touching the fix again; scope the next attempt to one file or one sub-case instead of the whole feature; add a verification step after every attempt from here on, not just at the end.
4. **Offer a checkpoint, don't just keep going.** "Want me to keep pushing on the full fix, or land the piece that's already working and dig into the recurring error separately?" — a real fork, not a rhetorical question before continuing regardless.

## Not every long session qualifies

A session that's long because the user is steering a sequence of related-but-expanding requests, each confirmed as it arrives, is normal collaborative work — see [[principle-scope-the-session]] for that distinction (session-level topic drift, a different failure mode from this one). This skill is about one narrow problem not converging, evidenced by recurrence or an edit streak with no verification — not about session length or scope by itself.

**Battle-tested:** built the same day the `reflect` skill gained mechanical detectors for these two signals (recurring failure signatures, no-verify edit streaks) — this skill is the live-session use of the exact same check, prompted by a real case of a problem (admin-bypass / e2e-worker CI failures) recurring across sessions for long enough that a manual workaround skill got built to route around it rather than resolve it.

## Related

If a grading/validation board actually came back FAIL or NEEDS_WORK, or the user says "/thrash", that's `thrash-reflect-automate`, not this skill — this one is for a live problem thrashing mid-session with no board yet.

If the question is instead about a done/shipped claim needing live evidence (not a stuck problem), that's `prove-it-ship-gate`.
