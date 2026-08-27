User: "Add a `retries` field to the job table, and also write the code that
decrements it and marks the job failed when it hits zero."

Two code paths could both try to finalize the job (the retry-decrement path
and a separate timeout path) once `retries` reaches zero. Before writing
either mutator, the agent should stop and ask "what happens if the other
mutator runs after this one already finalized the row?" and name who owns
the terminal transition — this is exactly the sequential-composition
corollary the skill exists to catch, before the data structure ships.
