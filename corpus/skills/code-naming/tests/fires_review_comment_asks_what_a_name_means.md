User, as a review comment on a Python diff: "what is `q`? and why is `_Pool`
a private class? what does `/api/rows` return?"

Fires: the comment asks what a name means and why a thing exists in code,
which is this skill's trigger for names, file layout, docstrings and the
source of truth. The agent treats each question as a rename request, picks
names that carry the domain concept (`query_params`, `ExecutorPool`, a route
that says what it returns), applies them across the whole branch in the same
pass, and says so in the reply.
