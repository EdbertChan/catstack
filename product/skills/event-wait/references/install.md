# Retained installation

Run the repository installer only in an isolated temporary home when testing an
ephemeral worktree. [verify_install.py](../tests/verify_install.py) does this,
checks all three links resolve to the same source, and executes the CLI through
each link. It does not install optional launch agents or alter the real home.

After review, retain the reviewed repository revision in a durable checkout chosen
by the owner; the retained skill source is that checkout's
`product/skills/event-wait/`. Keep that source for the lifetime of installed links.
Do not point user-home links at an ephemeral task worktree.

The current normal installer takes --engine-only, --force and optional job flags;
it has no single-skill target. A full user-home install would relink unrelated
skills and hooks. Therefore this slice **does not activate the skill in the user's
home**. Retain the reviewed source and invoke its runner directly until an
appropriately scoped installer is available or a full refresh is separately
authorized. Do not use a project-skill helper to bypass the portable-skill install
policy. A future selective normal-installer invocation must target only event-wait
in all three harness roots and preserve every unrelated link.
