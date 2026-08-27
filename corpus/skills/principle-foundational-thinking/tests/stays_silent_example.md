User: "Rename this local variable from `x` to `userCount` for clarity."

A pure single-line rename inside one function, no new data structure, no
shared mutable state, no sequencing decision, and nothing else touches this
variable. There's no foundational data-shape choice or ownership question
here — just do the rename. The skill should stay silent.
