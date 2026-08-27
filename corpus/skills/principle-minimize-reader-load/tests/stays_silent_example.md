A review turns up a `PaymentGateway` interface with two real, distinct
implementations (Stripe and PayPal) that each hide meaningfully different
integration complexity behind the same three methods.

This interface compresses real complexity for its caller and isn't a
pass-through layer or unused abstraction — collapsing it would just move
the complexity back to every call site. The skill should stay silent.
