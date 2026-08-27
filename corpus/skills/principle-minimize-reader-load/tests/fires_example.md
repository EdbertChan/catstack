A code review turns up an `AbstractResultAdapter` interface with exactly
one implementation and one caller, wrapping a simple data transform in two
extra indirection layers a reader has to trace through to find out what
actually happens.

This is a one-caller wrapper adding reader load without compression — the
skill should fire: collapse the adapter, inline the transform, and reduce
the number of layers a future reader has to trace between the call site and
the actual logic.
