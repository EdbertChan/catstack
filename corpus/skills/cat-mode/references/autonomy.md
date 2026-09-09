# Autonomy

cat-mode's SKILL.md carries the standing rule. These are the rest of its
autonomy defaults.

- **Prefer the obvious existing mechanism before designing a new one.** If a
  command or workflow already performs the requested action, run it first and
  report the actual result. Redesign only when explicitly requested or after it
  fails.
- **Do not kill/restart a live Invoker `owner-serve` as the default lever**
  for config, PATH, autofix, or env tweaks; use IPC mutations against the
  running owner. Restart only when it is already dead or the user asked.
  Before claiming "owner crashed," prove spontaneous exit (exit code/signal
  from a wait-wrapper) vs an agent `kill` from this session; stale-lock
  reclaim lines are successor symptoms, not crash proof.
- For a genuinely ambiguous or large ask, ask clarifying questions up front
  rather than guessing and redoing ("ask me questions about ambiguity and
  edge cases" before building).
- **Answering the opening question is a stopping point.** When a result
  answers a numbered item from the original ask, say which item it answered
  and ask whether to continue before launching further work. Absent that,
  work expands to fill the time available rather than terminating on the
  answer.
- **An auto-merge label is a live trigger, not an annotation.** A label such as
  `admin-bypass` is wired to a merge automation, so applying it to a PR whose
  branch is still being worked on lands that work half-finished the instant CI
  goes green, with no human in the loop. Tag at the end of the work on that
  branch — never to mark intent partway through, and never on a branch another
  agent or loop is still pushing to. No known prior art.
