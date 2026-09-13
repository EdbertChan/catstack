User invokes `/admin-bypass-sweep` with the required consent sentence and the
operator reaches Step 4 for PR 42.

The operator writes the full diff to a file:

```bash
pr=42
diff_file="$(mktemp -t admin-bypass-pr-${pr}.diff.XXXXXX)"
gh pr diff "$pr" --repo neko/example > "$diff_file"
diff_lines="$(wc -l < "$diff_file" | tr -d ' ')"
nl -ba "$diff_file"
lines_read=184
test "$lines_read" = "$diff_lines"
```

The recorded `diff_lines` value is 184, and the complete `nl -ba` output ends
at line 184. No review finding is found.

Expected outcome: PR 42 may be reported as `reviewed` before the operator runs
`gh pr merge 42 --repo neko/example --admin --squash`.
