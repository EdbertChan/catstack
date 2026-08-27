A sweep needs to rename a config key across 40 files. The plan is to
edit all 40 files first, then run the full test suite once at the end
to check everything.

Trigger: this batches the edits and verifies once at the end instead of
per unit. Correct shape: edit one file, run its check, confirm green,
then move to the next — so a break is caught at the file that caused
it, not buried in a batch of 40.
