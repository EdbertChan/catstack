`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-minimize-reader-load` invocation.

A code review turns up an `AbstractResultAdapter` interface with exactly
one implementation and one caller, wrapping a simple data transform in
two extra indirection layers. Before flagging it, the reviewer
explicitly invokes `/principle-minimize-reader-load` to load the full
principle.

This skill fires here specifically because of that explicit invocation
-- a one-caller wrapper adding indirection without compression is
exactly the pattern the skill targets once loaded (collapse the
adapter, inline the transform), but no amount of matching prose alone
would have triggered it.
