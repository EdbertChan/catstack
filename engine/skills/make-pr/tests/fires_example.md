User: "Make a PR for the changes to engine/hooks/demo-freeze and
product/skills/visual-proof."

This should fire: any PR authored inside the catstack repo loads this
overlay instead of plain `draft-pr`, and because the diff touches
`engine/hooks/` and `product/skills/`, the extra gates apply too — hook
e2e coverage (`check_hook_test_coverage.py`) and the three-harness /
ecosystem-boundary checks must pass before publishing.

The skill change also requires the diff-aware
`check_skill_test_coverage.py --base <actual-pr-base> --head HEAD` gate, so
the same direct PR slice must change the touched skill's corresponding test.
