---
name: land-stack
description: >
  Land (queue/merge) a stacked pull request safely, on any repo using a
  PR-stacking workflow (Mergify, Graphite, or similar). Trigger when asked to
  land, merge, ship, or queue a PR or PR stack. Enforces that you act only on
  SHA-verified PR numbers — never a PR found by branch name.
---

# land-stack

Use this skill whenever the user asks to **land / merge / ship / queue** a PR or a PR stack.

Generalized from a real incident in a repo using Mergify Stacks — the specifics below (label names, `gh` commands) assume that tooling, but the discipline transfers to any stacking workflow: adapt the discovery/merge commands to whatever queue tool the repo actually uses.

## Hard rule

**Never identify the PR to land by branch name.** Two different PRs can share a
branch name (an auto-generated workflow branch PR and the intended stack
PR). You must land by **SHA-verified PR number**, and every PR must pass a
guard before any write (label, thread-resolve, queue, merge).

## Steps

1. **Resolve PR numbers, bottom of stack first.** If the user gives numbers or
   URLs, use those. If they do not, make a best-effort read-only discovery pass
   and suggest the numbers yourself:

   - Enumerate open PRs broadly, e.g. `gh pr list --state open --json number,baseRefName,headRefName,headRefOid,title --limit 100`.
   - Filter to the repo's actual stack-branch naming convention (e.g. `stack/`).
   - Prefer candidates whose `headRefOid` exists in the local clone, so the code
     is actually available for review.
   - Order the stack by base/head links: the bottom PR targets the trunk; each
     later PR targets the previous PR's head branch.
   - Detect whether two or more open candidates share the same `headRefName`.
     If they do, present the exact bottom-up PR numbers and ask the user to
     confirm them before landing. This is the only discovery case that requires
     confirmation.
   - If every candidate `headRefName` is unique, run the guard on the suggested
     sequence and, when it passes, land it without an additional confirmation.

   Never discover by branch name. Do not run `gh pr list --head <branch>` to
   decide what to land — that is the unsafe path this skill exists to prevent.

2. **Verify with a guard before any write.** Check, for each PR: head SHA exists
   in the local clone (it is the code you reviewed), head branch matches the
   repo's real stack-branch convention (rejects raw workflow/auto branches),
   the PRs form a proper stack (each base is the previous head; the bottom's
   base is the trunk), and all are OPEN. If any check fails, stop and resolve
   the mismatch with a fresh discovery pass — do not work around it. The check
   is `scripts/verify_stack.py` in this skill (see below); run it and paste
   its output rather than reasoning through the four checks by hand.

   ```sh
   python3 scripts/verify_stack.py --repo <owner/name> --trunk <trunk> --git-dir <local clone> <bottom> <next> ...
   python3 scripts/verify_stack.py --repo <owner/name> --discover     # suggest stacks; exit 3 = confirm with the user
   ```

   Exit 0 means every check passed for that exact order. Exit 1 lists the failing
   check per PR. The script never calls `gh pr list --head`.

3. **Land bottom-up.** Merge the bottom PR, wait for it to actually merge, then
   retarget the next PR's base onto the trunk before merging it. Repeat up the
   stack. A base change can report an unsettled/unknown mergeability state
   immediately after — wait briefly and re-check before merging, don't merge
   on a stale read.

4. **Never batch merges without checking each result.** A merge command can
   look silent on both success and some failure paths; a silent-looking run is
   not proof of a merge.

## Do not

- Do not bypass the guard by hand-adding a bypass label or merging directly to
  skip a broken check — if the queue is unhealthy, that's a different, riskier
  operation that needs its own explicit authorization, not this skill.
- Do not resolve review threads to unblock a merge unless the user has decided
  to defer those findings; record the deferral on the PR.
- Do not act on a PR whose head SHA is not in your local clone.

## Prove state before reporting it

Before telling the user a PR is merged, queued, blocked, or failing CI, re-run
the exact status query in that same turn — do not repeat a status you checked
earlier in the conversation. "Merging" is not "merged"; a queued PR can still
fail a re-run of the full suite.

## Why this exists

A raw workflow-branch PR shared a branch name with the intended stack PR.
Landing "the PR on this branch" by name queued the wrong PR. The guard makes
that mistake fail closed instead of merging silently.
