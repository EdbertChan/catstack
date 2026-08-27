User types `/principle-separate-before-serializing-shared-state`. Two
parallel worker agents both need to record their own progress, and the
plan has them both writing into the same `state.json` file, each
updating their own `lastX` field, with an instruction to "just don't
step on each other's fields."

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-separate-before-serializing-shared-state`
invocation above is the only way it activates. Once invoked: this is
still one shared mutable write target with two concurrent writers, and
"take turns" is a convention, not concurrency control. Default move:
give each worker its own file (`worker-a-state.json` /
`worker-b-state.json`) and merge only at the read boundary.
