# Lessons — Phase 8 (Launch)

## What worked

Splitting the launch into a keyless tier (shipped) and a key-gated punch list (exact
commands, nothing vague) meant Phase 8 never blocked on externalities — RT-007 held to
the end. Committing results as files made the leaderboard a pure function of the repo,
enforced by a drift test. The Pages API call worked first try, removing a manual step.

## What was harder than expected

Packaging truths only a container reveals: `WORLDS_DIR` resolved against the source
tree and broke for wheel installs — the Dockerfile was the test that caught a bug every
pip user would have hit. And committed open-book traces were 3 MB of repeated rulebook
text; gzip (50×) plus transparent `.gz` reading in `read_traces` kept results auditable
without bloating the repo.

## What I would do differently

Run a wheel-install smoke test in CI from Phase 6 onward, not just at release — the
WORLDS_DIR class of bug is invisible to editable installs.

## Carry-forward action

The punch list (docs/launch-punch-list.md) is the live document: keys → calibration →
frontier runs → PyPI registration → private split → screenshot/release/external review.
