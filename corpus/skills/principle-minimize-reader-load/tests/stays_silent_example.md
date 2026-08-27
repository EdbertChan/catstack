A review turns up a `PaymentGateway` interface with two real, distinct
implementations (Stripe and PayPal) that each hide meaningfully
different integration complexity behind the same three methods. No
explicit invocation of this skill happens anywhere in the session.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. This interface also compresses real complexity for its
caller and isn't a pass-through layer -- even if this skill somehow
were invoked, its content would not apply here, since collapsing it
would just move the complexity back to every call site.
