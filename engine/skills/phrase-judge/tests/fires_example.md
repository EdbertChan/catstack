User: "I am fixing the wrong-check-reflect checker. It currently uses a regex
to decide whether a reply admits a previous statement was wrong."

This should fire: the checker decides based on what free-form prose means, so
its meaning belongs in `engine/hooks/llm-judge/phrases/<checker>.json` with
real `match` and `not_match` phrases.

User: "Another repo's review-unit checker fails my plan because the words
stale and skip count as a policy change. I'll trim those words from its list."

This should fire too: the checker lives outside catstack, but it still decides
meaning by matching words, so the fix is to replace that decision with typed
inputs or a judge, not to trim the word list.
