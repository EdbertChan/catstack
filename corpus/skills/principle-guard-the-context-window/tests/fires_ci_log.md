The user explicitly invokes `/principle-guard-the-context-window` while asking
for CI diagnostics from a large GitHub Actions job log.

Instead of downloading or printing the whole log in the main thread, the agent
should read `scripts/ci_logs.py --help`, capture the job log into a local
artifact, ask bounded snippet questions by artifact handle, and cite the exact
source ranges, omitted bytes, hash, and uncertainty fields in the answer.
