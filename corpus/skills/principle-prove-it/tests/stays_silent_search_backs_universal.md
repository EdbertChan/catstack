An agent writes "only five of the 28 workers listen for task events" and
pastes, in the same message, a search over every package for the
subscription call:

```
$ git grep -n "subscribe<WorkflowLifecycleEvent>" -- packages | grep -v __tests__
auto-fix-recovery.ts:927
auto-approve-worker.ts:524
infra-repair-worker.ts:1525
requeue-worker.ts:319
workflow-resume-worker.ts:238
```

This skill stays silent. The claim says "only", and the evidence next to it
is a search over all of the code, not a single line read. The output entails
the sentence: five files subscribe, and the search could have shown a sixth.

A plain `file:line` claim that says nothing about all of anything also stays
silent. "The lock is taken at `headless.ts:708`" is backed by that line alone.
