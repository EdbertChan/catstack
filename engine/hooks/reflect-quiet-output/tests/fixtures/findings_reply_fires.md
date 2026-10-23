Lens fan-out was run inline by me, not as separate lens agents, so this is a partial pass by the skill's own rule. Nothing was applied or edited. Every quote and count below is read-confirmed against the session transcript. I read the session transcript and the audit JSON at the working-tree/installed ref (no git ref applies). Hook file paths are name-matched, because they come from the hook command lines in the transcript and I did not open them.

**Cost audit:** 34,371,591 tokens (+219,989 subagent), 220 turns, 97.98% cache-read. Flags: no-verify-edit-streak 6, self-retraction 5, cache-creation spikes 2, model-tier 2 (about $0.0015), redundant reads 0, recurring failures 0. Hook blocks: 77 rows, 46 from diu-stop (14 of them after row 1285).

**Accepted**
- None. Every real fix sits above skill prose in the hierarchy.

**Backlog**
1. **Main-thread checking (tier 3, hook).**
   - Happened: the user said "you went off and did something and testied something?" (row 1740), after "huh?" (1678). In the main thread I ran an offline fake-GitLab test, a real run, 6 WebFetch slices of a 494,535-char doc, and timing and `ps` checks.
   - Fix: add a PostToolUse hook that counts verify-shaped calls (WebFetch, WebSearch, test-like Bash) in one user turn with zero Agent calls. At 3 or more, it tells the main thread to delegate and requires a capped-length reply.
   - Catch: I backtested the rule over this transcript and it fired on turns 1453 (7 calls) and 1691 (5 calls), the turns just before the complaints. It also fired on 1318 (3 calls).
2. **Stop-hook rewrite loop (tier 2, test).**
   - Happened: rows 1727 and 1731 are the same reply sent twice. The diu-stop hook flagged "I haven't run it, because you haven't approved it" as an unverified claim (trigger "because").
   - Fix: add a negative fixture so a statement about not having run something passes, and a positive fixture so a real unverified claim still trips.
   - Catch: the real-text fixture would have fired on row 1728's sentence. I have not run the fixed hook, so the fix itself is unchecked.

**Route-to-automate-me**
- **Default: delegate every check, get a short answer back.**
  - Happened: this is a same-type complaint twice (1678/1691 and 1740) plus the verbatim reflect complaint, and `intervention-must-automate` came back yes.
  - Fix: delegate any check likely to print more than a couple of lines to a subagent with a word cap, and use only its short result for the next step. A memory file already holds this (read-confirmed). Promote it to the automate-me mode, and pair it with Backlog 1.
  - Catch: the audit flag fired. The hook in Backlog 1 is the durable catch.

**Rejected**
- **Plain-words complaint.** Already covered by diu-stop plain-words-* blocks, which fired at rows 1301, 1595, 1625, 1655, 1704 and 1793. The cost is the rewrite loop, which Backlog 2 covers.
