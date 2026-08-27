A lint check fails once because of a genuine one-off typo (`improt` instead
of `import`). The agent fixes the typo and the check passes on the very next
run — no second rejection of the same class ever occurs in this session.

There's no repeated pattern to generalize from; a single, already-resolved
mechanical failure isn't the trigger. The skill should stay silent.
