User: "I am fixing the wrong-check-reflect checker. It currently uses a regex
to decide whether a reply admits a previous statement was wrong."

This should fire: the checker decides based on what free-form prose means, so
its meaning belongs in `engine/hooks/llm-judge/phrases/<checker>.json` with
real `match` and `not_match` phrases.
