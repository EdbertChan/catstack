# Evidence check (apply everywhere)

A Grep or name hit is **not** a check.

- Do not cite a file, line, or "the bug is X" until this turn's Read or
  command output is in the same message.
- If two files could match, Read both before picking one.
- Prefix `UNVERIFIED:` until you have that evidence.
- "My earlier check was wrong" means the claim went out before the check —
  that is a process failure, not a polite recovery. The
  `wrong-check-reflect` hook will force `/reflect` when it sees that
  admission.
