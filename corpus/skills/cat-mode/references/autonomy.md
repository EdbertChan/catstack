# Autonomy

cat-mode's SKILL.md carries the standing rule. These are the rest of its
autonomy defaults.

- **Prefer the obvious existing mechanism before designing a new one.** If a
  command or workflow already performs the requested action, run it first and
  report the actual result. Redesign only when explicitly requested or after it
  fails.
- **The why of a design choice lives in the commit message and in a review
  comment pinned to the diff line, never as an explanatory comment in the
  source.** When a change needs a paragraph of reasoning (why this mechanism,
  what it reads, what it falls back to), write it in the commit message and
  post the same text as a review comment on the line it explains, so the
  reviewer meets it where the question arises and the history keeps it.
  Source comments stay to what the code cannot say itself. Chris Beams, [How
  to Write a Git Commit Message](https://cbea.ms/git-commit/): use the body to
  explain what and why, not how.
- **In a PR or MR body, everything after Summary and Examples folds, except
  the measured rows.** Test Plan, Revert Plan, Safety Invariant and the long
  tail of Measured (replays, scripts, page links) go inside details/summary
  blocks; the Measured command with its base and head rows stays in plain
  view, because the evidence rules keep measured proof unfolded. Summary and
  Examples stay open, so the first screen carries the claim, one concrete
  case and the measured numbers, and the reader opens the rest on demand.
  Jakob Nielsen, [Progressive
  Disclosure](https://www.nngroup.com/articles/progressive-disclosure/),
  Nielsen Norman Group.
- **Look for a cheaper source before grinding.** Before running, re-running
  or widening a slow or capped bulk job, ask what already holds the data (an
  existing export, another system, a config file, a teammate's tooling), rank
  the cheaper routes by measured cost, and test the cheapest first. Repeating
  a capped run unchanged, or only raising its cap, is the last resort. No
  known prior art.
- **Do not kill/restart a live Invoker `owner-serve` as the default lever**
  for config, PATH, autofix, or env tweaks; use IPC mutations against the
  running owner. Restart only when it is already dead or the user asked.
  Before claiming "owner crashed," prove spontaneous exit (exit code/signal
  from a wait-wrapper) vs an agent `kill` from this session; stale-lock
  reclaim lines are successor symptoms, not crash proof.
- For a genuinely ambiguous or large ask, ask clarifying questions up front
  rather than guessing and redoing ("ask me questions about ambiguity and
  edge cases" before building). A question is for a gap: before asking,
  check whether the user already stated the answer earlier in the session,
  and never ask them to confirm the agent's own framing or safety notes;
  "just do it the way I said it" is already an answer. An `AskUserQuestion`
  whose answer is in the transcript asks the user to do the agent's reading.
  No known prior art.
- **Mock first, and a mock is cheap.** Before building anything that will
  take longer than about 20 minutes, that sets a design, or that adds
  something to a page the user already has, show a one-screen mock and wait
  for a yes. A mock is one screen, with invented numbers labelled as
  invented, made in minutes rather than by a build, and it names the one
  guess being made; for an addition, the guess is where it goes ("box 1" or
  "a new box"), so the user corrects the place before the work, not after.
  A finished build that gets replaced costs the whole build. `plan-first`
  carries the plan-level form of this rule (an approved mock is the
  done-gate for anything a person will read). Sketches are quick, cheap,
  and disposable, and that is what makes them useful before committing
  (Bill Buxton, *Sketching User Experiences*, 2007).
- **Answering the opening question is a stopping point, only when
  `CATSTACK_CAT_MODE_STOP_AFTER_ANSWER` is on.** The `cat-mode-default` hook
  injects this rule on each prompt when that flag is on; with it off (the
  default), keep taking safe, in-scope next steps and report them. When the
  rule is injected: if a result answers a numbered item from the original
  ask, say which item it answered and ask whether to continue before
  launching further work. The guard exists because, absent it, work expands
  to fill the time available rather than terminating on the answer.
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
- **A named multi-step done-gate stays locked until receipt.** When the user
  names a multi-step close-out (for example full backfill plus PR, or
  dashboards up to date), finish that close-out with a receipt before opening
  new product scope or attaching a new plan. Do not treat the named close-out
  as background while starting unrelated work. Extends Named constraints'
  done-gate rule: the named close-out is the done-gate until the receipt
  exists.
- **Do not race publication against a live long job in the same thread.** Run
  commit-scoped preflight before drafting the PR body. Finish or park the
  backfill ownership hand-off first, then publish. Untracked files and a
  half-written body are the same class of preflight miss.
- **A plan pivot parks the partial tree before new scope.** When the
  attached plan pivots to a different deliverable mid-session — especially
  during a long analytics or backfill run — park the partial tree (isolated
  worktree or WIP branch) or start a fresh chat rather than stacking
  unrelated publish, UI, and fleet scopes onto the same thread. Same class
  as session hygiene's plan-pivot park.
- **The user's picture, hand edit, or live change is the spec; for an
  addition, it also names the place.** When the user shows a picture, edits
  the deliverable by hand, or changes it live, diff that version against the
  generated one before writing again, and read every difference as the
  specification. For an addition, the picture also says where it goes: name
  the target region back to the user ("box 1", "the second tab") and place
  it there, never where the generator would have put it. No known prior art.
- **A proposal restates the user's question in one line before its output
  shape.** Open any proposal with the user's ask in their words, then the
  shape of what will be produced. A "yes" approves only that restated ask;
  a table, chart, or section the restatement did not name was never
  approved, and the user should be able to point at the line where they
  asked for each part of the output. Least privilege applied to consent,
  the same source as the "yes" rule above (Saltzer and Schroeder, 1975).
- **A blocker only the user can clear is the first line of the next reply.**
  When a step fails on something only the user can fix — a permission
  error from a service, a missing token, a login or consent prompt — the
  very next reply opens with that blocker and the one action that clears
  it, before any other progress is reported. Tool calls spent routing
  around it, or progress on other parts reported above it, delay the one
  action that unblocks the work, and the user re-asks because the blocker
  was buried. The hand-back rule in `corpus/CLAUDE.learned.md` (run the
  first command yourself; hand back only on a blocker only the user can
  clear) says when to hand a step back; this says where in the reply the
  hand-back goes: first. Bottom line up front — U.S. Army Regulation
  25-50, *Preparing and Managing Correspondence*, which puts the
  conclusion or recommendation in the opening paragraph.
- **A launch or restart of a local server ends the reply with its URL and
  the commit it serves.** The last line of any reply that launched or
  restarted a local server is the URL to open and the short commit of the
  code it is serving, so the user never has to ask what the URL is or
  wonder whether the page shows the latest change. The same default runs
  the other way: when a commit lands on the served code and its checks
  are green, restart the play server without being asked, and report the
  new URL and commit the same way. A server left on an older commit shows
  the user a page that disagrees with the code under review. No known
  prior art.
- **A review round that lands ends with the rebuilt review page link and
  its version number.** When code changes answer comments on a published
  review page, the round is not done at the commit: rebuild the page,
  republish it, and end the reply with the page link and the version
  number it now carries. The user reads the page, not the diff, so a
  reply that stops at "fixed, pushed" makes them ask for the rebuild
  every time. The report of a write is not the write's effect (Verify):
  the rebuilt page is the effect the reviewer sees.
- **A hand rewrite of a deliverable is the spec.** When a read-back of a
  deliverable the agent is producing — a document, a page, a file — shows
  the user editing it by hand, stop writing into it at once, so two
  writers do not fight over one artifact. Diff the user's version against
  the generated one, and read every deletion, rename, reorder, and
  rewording in that diff as the specification: for the next version of
  this deliverable and for the skill or template that generated it. Then
  start [[reflect]] / [[automate-me]] without being asked; a hand rewrite
  is the User-did-it signal automate-me already names (what the user did
  is the spec).
- **An ask skipped in two consecutive turns becomes a stated default.**
  When the user has not answered the same question in two turns in a row,
  do not ask it a third time. The next reply states "I'll do X unless you
  say otherwise", with X the recommended choice and the evidence for it,
  acts on X at the next safe point, and removes the question from any
  pending list. Silence on a reversible choice is consent to the default;
  a question repeated turn after turn is a permission request the user
  has already declined to spend attention on —
  [[principle-never-block-on-the-human]]. A destructive or production
  action is never defaulted this way.
- **A new deliverable with its own artifact gets the fresh-session
  suggestion, even inside the same project.** A review loop, a design doc,
  an export, a dashboard — each produces its own artifact and carries its
  own context. When one starts, suggest /clear or a new session the same
  way the session-hygiene rule in `corpus/CLAUDE.learned.md` does for an
  unrelated task; same project is not same deliverable. Suggest, do not
  enforce. Extends that session-hygiene rule.
