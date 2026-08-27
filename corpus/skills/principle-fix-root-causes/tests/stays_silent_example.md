A designer asks for the button color on a settings page to be changed
from blue to the brand's green, purely a visual styling preference
with no bug or crash involved. No explicit invocation of this skill
happens anywhere in the session — the agent just makes the change.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no debugging happening and no symptom being
papered over — even if this skill somehow were invoked, its content
would not apply to a straightforward styling change with a known,
intended outcome.
