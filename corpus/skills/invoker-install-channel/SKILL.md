---
name: invoker-install-channel
description: >
  Apply when installing, updating, starting, or reporting Invoker
  (npm packages vs a git checkout, or a path under /opt/homebrew).
  Stay on npm as the distribution channel; name the command actually run.
---

# Invoker install channel

## Invariants (assert)

- Invoker is distributed via npm (`@neko-catpital-labs/invoker-ui`,
  `invoker-cli`, `invoker-slack`), not Homebrew. `/opt/homebrew/...` is
  only a filesystem prefix for global npm — never call that install
  "Homebrew." If the npm-packaged app cannot serve as owner, launching
  an already-built git checkout (`./run.sh --headless owner-serve`) is
  allowed without asking; do not call that "building from source." Do
  not switch away from a healthy npm owner just to use a checkout.
- When reporting install or update status, name the command actually
  run. Do not infer a distribution channel from a path prefix.

**Why:** npm's global prefix can be `/opt/homebrew/` without Homebrew
being the distribution channel.
