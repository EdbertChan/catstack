User, reviewing a dashboard diff: "why does the board only show 100 runs? and
why does the roadmap say 1h 38m when the board says 115.6 min?"

Fires: a built-in row limit and two outputs that disagree on the same data are
both source-of-truth questions. The agent removes the baked-in limit (or moves
it to a configured value with its reason beside it), makes the board and the
roadmap read one shared loader and one computation, and says so in the reply.
