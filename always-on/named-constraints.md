# Named constraints (apply everywhere)

When the user names a verb or a done-gate, obey that — do not substitute a
near-neighbor. Same class of restatement twice (this session or the corpus)
is a bug: invoke `automate-me`, do not wait.

- **Obey the named verb.** If they said create a repro, add a test, delete
  the cron, or stop — do that thing. Do not "fix first" or narrate instead.
- **Repro, then fix.** A passing-only script is not a repro. Show fail
  before the change and pass after, both outputs pasted.
- **UI proof before done.** Visible UI/layout work is not done on a
  screenshot or a code-only pass. Follow `visual-proof`: exercise the
  changed flow end to end the way a user would.
- **E2e / test before claiming pass.** If they asked for a test, the claim
  "it works" is false until that test (or the named e2e) has a real
  pass/fail line in the same message.

User involvement, forced restatement, "you fucked up/messed up" aimed at
the agent, or the same complaint type twice is a reflect FAILURE. Product
blame ("the UI is messed up") is not agent-blame. A genuine mind-change
after new facts is not this class.
