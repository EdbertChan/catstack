# coding bindings

Use when the workload runs through Invoker / Codex on a software repo.

- Prefer Invoker YAML plans with unique `bound-tool-ab-<arm>-<rep>` style tags
  so session discovery can key on workflow id + name prefix.
- `onFinish: pull_request` + `mergeMode: external_review` when PR diffs are
  part of the comparison; empty product diffs may skip Invoker PR publication
  (still record that in the gist).
- Wait with `invoker-cli query` polling (or a single `invoker-cli wait` per
  workflow). Do not fan out many parallel `invoker-cli wait` calls — owner
  discovery can time out under that load.
- Codex sessions live under `~/.codex/sessions/` as `rollout-*.jsonl`.
