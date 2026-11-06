A user says: "This repo has a web app and a CLI, but nobody can show me a
feature actually working. Make a control skill for this repo."

This skill fires. The repo has no scripted way to launch the app and prove
behavior, which is the stated trigger. It interviews the repo (surface, run,
drive, observe, isolate), writes `verify-<app>` with Launch, Doctor, Drive,
Evidence and Cleanup sections, seeds a feature map, runs one mapped feature
end to end before handing it over, and links the result into all four
harness roots.
