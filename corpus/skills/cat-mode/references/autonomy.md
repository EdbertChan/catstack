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
- **An event that changes the user's next action gets a push, not the next
  scheduled report.** A gate gone red, a long job finished, a decision now
  blocked on them — send it when it lands. A scheduled report makes the user
  the scheduler: they have to come back and check, which is the poll the ETA
  was supposed to replace. The ETA covers the quiet case, not the case where
  something actually happened. Routine progress ticks earn nothing; the
  discriminator is whether it changes their next action, not whether it is
  new information. `PushNotification` no-ops by design while the user is
  active at the terminal, so "not delivered" is a normal result and never a
  reason to skip the call. This is [[principle-push-not-poll]] applied to the
  human channel rather than the machine one, and the alerting rule that
  every page be actionable while everything else waits on a dashboard the
  reader consults themselves — Rob Ewaschuk, Monitoring Distributed Systems,
  in Beyer, Jones, Petoff & Murphy, *Site Reliability Engineering*, O'Reilly
  2016, https://sre.google/sre-book/monitoring-distributed-systems/.
