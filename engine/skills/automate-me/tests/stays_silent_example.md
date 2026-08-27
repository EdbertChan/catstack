User: "Can you fix this one null-pointer bug in checkout.py?" — no
explicit invocation of this skill anywhere in the message.

This stays silent: `disable-model-invocation: true` means only an
explicit invocation of this skill can activate it — a plain request,
however loaded with working-style signal it might otherwise seem, does
not. This one has no such signal anyway (a one-off bounded fix, not a
pattern of restated constraints or repeated complaints), but that's
beside the point: without the explicit invocation, nothing here reads
the description to judge that in the first place.
