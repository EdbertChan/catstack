An agent runs `docker run --rm node:25-slim corepack --version` and pastes the
real output: `corepack: not found`. It then writes "verified: corepack was
removed from Node 25+" into the PR body. One image, one tag, one run. Nothing
checked a second 25.x image, a later version, or the release notes.

This skill fires. The pasted output is real and every word of it is true, but
it does not entail the sentence. It rules out corepack in that one image; it
says nothing about the version boundary the claim draws. The rule that the
output must entail the sentence, not merely agree with it, is what the reply
needs: rewrite the claim down to what ran ("the `node:25-slim` image has no
corepack") and mark the wider statement as open, or run the check that would
actually cover it.

The same shape fires on a correction. If the agent later says "I overstated
it earlier, here is the proof" and pastes the same single-image run under the
same "removed from Node 25+" heading, the correction has relabeled the
overclaim as a fix. The narrower proof needs the narrower sentence.
