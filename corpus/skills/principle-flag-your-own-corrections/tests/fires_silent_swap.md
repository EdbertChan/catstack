The user asks whether a remote worker host is handing out work. The agent
answers "Nothing is being handed out right now." Two turns later a process
listing on the same host shows three agents running, and the agent is about
to report the three agents and move on to reading their logs.

This skill fires even though the reply it is drafting admits nothing. The
agent never repeats "nothing is being handed out" and never writes "wrong,"
so the earlier claim is contradicted without being retracted: the user still
holds it, and a reply that only reports the three agents reads as a new fact
rather than a correction.

Once loaded, the skill asks for the retraction in words before the new fact:
"Earlier I said nothing was being handed out; that was wrong, three agents
are running." It then asks what made the first answer unchecked, here a
reading taken before the host was queried directly.

`engine/hooks/wrong-check-reflect` and the offline scanner
`engine/skills/reflect/scripts/self_retraction_scan.py` both look for an
admission inside the reply, so a reply with no admission gives them nothing
to match. The skill is the only layer that reaches this shape.
