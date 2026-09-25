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
- **A "yes" authorizes the actions it named, not the ones found afterwards.**
  When work turns up a destructive or production-mutating step the approval
  did not name (cancelling a live workflow, killing a process, deleting a
  branch), put the evidence that makes the step right in the same message,
  then ask one short confirmation before acting. Undoing a side effect this
  session itself created is the exception: state the evidence and proceed.
  This is least privilege applied to consent: an approval grants what was
  asked for and nothing wider — Jerome H. Saltzer and Michael D. Schroeder,
  "The Protection of Information in Computer Systems", 1975,
  https://web.mit.edu/Saltzer/www/publications/protection/Basic.html.
- **A health question covers what the thing serves, not only whether it runs.**
  For example, when the user asks whether workers, babysitters, or loops are
  running, report the target repo's default-branch CI state and the date of its last
  green run in the same answer, without being asked. A worker can be healthy
  while the branch it feeds stays red, and a liveness answer alone leaves the
  user to find that out by pasting a CI link. Keeping the mainline green and
  its state visible to everyone is continuous integration's own rule —
  Martin Fowler, "Continuous Integration", 2006,
  https://martinfowler.com/articles/continuousIntegration.html.
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
- **Asked for a phone alert? Send a test push right away.** When the user
  asks to be alerted on their phone, send one test push as soon as the alert
  is set up and report whether it reached the phone. If the result says it
  did not (for example "Mobile push not sent (Remote Control inactive)"),
  tell the user then, with what would fix it, not at the end when the real
  alert fails to arrive. An alert path nobody tested is unchecked, not
  working. This is the opposite case from the rule above: there the user is
  at the terminal and "not delivered" is normal; here the user asked for
  the phone because they will not be. No known prior art.
