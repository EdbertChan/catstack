A user is designing a cache key format for a service and says: "this is
expensive to change once it's in production — what are our real options
here?"

This skill fires. It is a design decision that is expensive to reverse,
which is the stated trigger, and the user is explicitly asking for the
option set rather than a recommendation. Step 2 fans out subagents each
optimizing a different constraint (fewest moving parts, cheapest to migrate,
best for the caller), and Step 3 labels every returned option `considered`
with a citation or `invented`. Because the leading option is expensive to
reverse, Step 4 routes it to `spike-and-validate` before it can decide
anything.
