---
name: visual-proof
description: >
  Capture and present trustworthy before/after visual evidence (screenshots,
  video) for a UI-affecting change. Use when a PR modifies UI, the user asks
  for visual proof or before/after screenshots, or when reviewing a UI change
  and wanting to see what actually changed.
---

# visual-proof

Generalized from a repo-specific `visual-proof` skill built around Playwright + a custom upload pipeline. The mechanics below assume nothing about your stack — swap in whatever capture/diff tooling the project actually has (Playwright, Puppeteer, Cypress, a manual screenshot, `ffmpeg`, ImageMagick `compare`). The discipline is what generalizes.

## Never reuse an unrelated or stale asset as proof

Every image/video in a visual-proof section must come from a capture run **against the change being proved**, in the same review. Do not paste in a screenshot or gif from a different PR, a different bugfix, or an earlier state of the UI just because it happens to show the same general screen — a stale asset asserts something that was never verified and actively misleads reviewers, since it can predate the fix by many commits and no longer match what the app looks like today.

## When part of the behavior genuinely can't be shown in a still image

OS/browser cursor icons, an animation's motion in a single frame, a race that only exists for milliseconds:

1. Capture whatever partial signal actually *is* visible — e.g. a spinner or indicator element that's now present where it wasn't before, even if the frame can't show it moving. Hold the state open artificially (a test-only delay/override) long enough to screenshot it, rather than skipping the capture because the real thing resolves too fast.
2. For the part that truly can't be captured, say so plainly in the write-up and point to a concrete non-visual proof instead (a DOM/class assertion, a grep check, a test name) — never substitute an image that doesn't actually demonstrate the claim.

## Actually look before you claim

A captured screenshot or video file is not proof that anyone looked at it. Before writing any claim about what the media shows — "fixed," "no longer happens," "stays in place" — open the exact file yourself: read the image, or extract frames from a video (`ffmpeg -vf fps=4 ...`) and read those. State precisely what you saw on an explicit `Manually inspected:` line next to the media. A PR-body linter that rejects a visual-proof section with media but no `Manually inspected:` line is worth having if the repo enforces PR bodies at all — see `principle-encode-lessons-in-structure`.

## Generic workflow shape

1. **Before**: on the unmodified base, capture the UI state that's about to change.
2. **Make the change.**
3. **After**: same capture, same state, on the changed code.
4. **Compare**: a pixel diff or side-by-side (any tool works — `compare` from ImageMagick, a screenshot-diff library, or manual eyeballing for a small change).
5. **Present**: before/after (and diff, if generated) embedded together, with the `Manually inspected:` line stating what actually changed.

## Device/emulator capture loops can wedge — probe liveness before each batch

Driving a device or emulator for capture (`adb shell input tap/text` + `screencap`, an iOS simulator equivalent, or any similar tap-and-screenshot automation) can silently stop responding mid-loop — the shell accepts commands but the device never acts on them again. Retrying the same tap/screenshot command against a wedged device just times out repeatedly without ever revealing that the device itself, not the command, is the problem.

- Before each batch of automated taps/screenshots, run a cheap liveness probe first (e.g. `timeout 40 adb shell echo alive || echo "SHELL WEDGED"`) rather than diagnosing a wedge only after several silent timeouts.
- On a detected wedge, restart the automation bridge itself (`adb kill-server && adb start-server`, or the platform equivalent) before retrying the batch — retrying the same tap sequence against a dead bridge just repeats the timeout.
- This is a distinct failure mode from a flaky assertion or a genuinely slow app: the symptom is *the whole automation channel* going unresponsive, not one interaction failing.

## Plan ahead for UI changes

Don't bolt this on after the fact. If a change touches UI, capture "before" while you still have the unmodified code checked out — capturing "before" from memory or from an old screenshot defeats the whole point.
