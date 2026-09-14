# Stack-branch landing fixture

PR #1789 was reported by GitHub as merged after it landed against a stack
branch instead of the trunk.

Old Step 6 input:

```text
#1789	MERGED	2026-09-09T10:11:12Z	Retarget child stack branch
```

Old Step 6 outcome:

```text
merged
```

New Step 6 verifier result:

```text
exit 1
FAIL: PR #1789 in owner/repo reports MERGED but abc123 is not on origin/master
```

New Step 6 outcome:

```text
merged-but-not-on-trunk
```
