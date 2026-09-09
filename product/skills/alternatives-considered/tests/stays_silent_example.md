A user asks the agent to rename a local variable inside one function from
`res` to `response`, and confirms the function is not exported.

This skill stays silent. The decision is cheap to reverse — a rename inside
one unexported function is a single edit undone by a single edit — and the
skill's Step 1 says a cheap-to-reverse decision does not need it. There is
no option set worth generating, and producing three labeled alternatives for
a local rename would be the padding its own "do not" list forbids.
