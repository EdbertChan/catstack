User types `/principle-type-system-discipline` while reviewing a
TypeScript interface: `{ completed: boolean; completedAt?: Date }`.
Completion logic elsewhere assumes `completedAt` is always set once
`completed` is true, with a runtime "should never happen" throw
guarding that assumption.

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-type-system-discipline` invocation above is the
only way it activates. Once invoked: this is the illegal-state-
representable anti-pattern named directly in the skill. `completed:
true, completedAt: undefined` type-checks but is meaningless. Fix at
the type: a discriminated union like `{ kind: 'open' } | { kind:
'done'; at: Date }`, then delete the runtime throw once the type makes
the bad state unrepresentable.
