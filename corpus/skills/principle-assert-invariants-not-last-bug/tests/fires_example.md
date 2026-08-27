A code-review bot flagged a duplicate row for ticker "AUR" in the holdings
table. The fix ships as `if ticker == "AUR": dedupe()`. Two weeks later the
same duplicate-row bug appears for ticker "SERV" and sails through review
because the fix only patched the AUR case.

This skill should fire: the commit message reads like "fix dedupe for AUR,"
which is exactly the "fix X for ticker/case Y" pattern this skill targets —
the fix should have named the invariant ("every (period, entity) pair has
exactly one row") and encoded it generally, not patched one ticker.
