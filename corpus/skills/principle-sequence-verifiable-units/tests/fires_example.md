User types `/principle-sequence-verifiable-units`. A sweep needs to
rename a config key across 40 files. The plan is to edit all 40 files
first, then run the full test suite once at the end to check
everything.

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-sequence-verifiable-units` invocation above is the
only way it activates. Once invoked: this batches the edits and
verifies once at the end instead of per unit. Correct shape: edit one
file, run its check, confirm green, then move to the next — so a break
is caught at the file that caused it, not buried in a batch of 40.
