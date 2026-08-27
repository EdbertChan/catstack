An audit already named three existing scorers (finding-priority mix,
fraud_learning case frequency, recency decay) and said flag types don't
transfer across companies because of exact-string matching. The user then
says: "these weights feel arbitrary, I think we need a real classifier."

This skill should fire: "real classifier" and "arbitrary weights" are the
exact trigger phrases, and the audit already named the gap (exact-string
transfer) on a specific existing scorer (fraud_learning). The next plan
should bind the complaint to that named scorer instead of proposing a new
sklearn model.
