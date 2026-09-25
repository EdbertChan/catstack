## Summary

We run the same tools on seven machines. Keeping them all on the same version used to mean updating each one by hand.

Now `scripts/update_fleet.sh` does it. It reads `remoteTargets` from `~/.invoker/config.json`, updates every machine, then prints one line per machine saying whether it worked.

A machine it could not reach shows as failed, never as fine. A `--dry-run` changes nothing.

## Review Claim

The update script reports every machine it was asked about, and a machine it could not check shows as failed, not as fine.

## Review Lane

behavior

## Review Unit

corpus-lesson

## Safety Invariant

The script changes nothing on a `--dry-run`, and replacing the live app on that machine happens only behind an explicit flag. Release assets are checksum-verified before anything is installed.

## Slice Rationale

One claim, one review unit: the cat-mode skill package plus its colocated tests. The two mined rules are prose in the same skill; they ship no code and cannot be reviewed apart from the file they live in.

## Non-goals

- No Invoker-side change: the script consumes published release assets as they are.
- No scheduler or worker. Running it is still a person's decision.

## Test Plan

```
$ python3 -m unittest tests.test_cat_mode
Ran 92 tests in 0.113s
OK
```

Gates:

```
$ python3 scripts/ci/check_skill_file_refs.py    -> exit=0  ok      skill file refs
$ python3 scripts/ci/check_codify_has_code.py    -> exit=0  ok      codify-has-code
```

## Revert Plan

- Safe to revert? Yes
- Revert command: `git revert <sha>`
- Post-revert steps: None. No installed hook, skill, or machine reads the script.
- Data migration? No
