User says: "The agent kept running `pgrep -f <name>` in a wait loop that
never exits. Add a hook under `engine/hooks/` that blocks a process wait
whose pattern matches its own command line."

This is the case the skill exists for — authoring a new detector under
`engine/hooks/`. Before writing the regex, copy the 20-line block under
"The list" in `playbooks/detector-lifecycle.md` into the todolist. The
list is what forces the open-PR search (is anyone already widening
`gh-write-verification`?), the near-miss enumeration (a one-shot
`pgrep -f` is wrong under this harness too, not just the loop), the silent
set with a fixture per entry, the fail direction, and the whole install /
README / inventory / pointer tail before `make-pr` is called at step 20.

It fires the same way on a widening: "wrong-check-reflect missed a bare
'I was wrong' — add the pattern." That is still a detector change, so the
detection steps all apply and the wiring steps stay in the list marked
`skip: existing hook, already wired`.
