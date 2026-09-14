After the human explicitly invokes `/principle-never-block-on-the-human`,
the agent replies with a login script for the human to run. It ran only a
syntax check on the local wrapper; the remote portion was never executed,
so the handoff includes an untested command sequence and no evidence that
the remote step succeeds.

The attention-guard Stop hook fires: a script handed to the human must have
been run end to end first. The agent should run the remote portion itself
when possible, or run up to the first genuinely human-only step and hand
over only that step with the reason, such as a password, browser login, or
2FA requirement.
