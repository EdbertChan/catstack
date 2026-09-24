## Summary

We run the same tools on seven machines. Keeping them all on the same
version used to mean updating each one by hand. Now `scripts/update_fleet.sh`
does it: it updates every machine, then prints one line per machine saying
whether it worked.

## Review Claim

The update script reports every machine it was asked about, and a machine
it could not check shows as failed, not as fine.

## Review Lane

behavior

## Review Unit

corpus-lesson

## Safety Invariant

The script changes nothing on a `--dry-run`, and replacing the live app
happens only behind an explicit flag.

## Slice Rationale

One claim, one review unit: the fleet-upkeep script and its colocated
tests.

## Non-goals

- No scheduler or worker. Running it is still a person's decision.

## Test Plan

```
$ python3 -m unittest tests.test_cat_mode
Ran 92 tests in 0.113s
OK
```

## Revert Plan

- Safe to revert? Yes
- Revert command: `git revert <sha>`
- Post-revert steps: None.
- Data migration? No
