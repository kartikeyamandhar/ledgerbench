# Launch punch list — owner-gated steps

Everything below needs a credential or account only the owner holds. Each item is
ready to execute as written; nothing else in the launch blocks on them.

## 1. API keys — DONE 2026-06-12

```bash
cp .env.example .env        # then paste real keys; gitignored + gitleaks-guarded
```

## 2. Live judge calibration — DONE 2026-06-12: agreement 0.90 (gate 0.80)

```bash
source agentic_flow/bin/activate
python scripts/judge_calibration.py     # prints agreement; gate >= 0.80
```
Record the measured agreement in `docs/architecture.md` and `docs/report.md`.

## 3. Frontier benchmark runs — small-model tier DONE 2026-06-12 (haiku-4-5 + gpt-4o-mini, $1.62; sonnet-4-6/gpt-4o still pending more credits)

Edit the roster at the bottom of `scripts/run_benchmark.py`
(e.g. `["naive", "anthropic", "http_openai"]`), pick models via
`LEDGERBENCH_ANTHROPIC_MODEL` / `LEDGERBENCH_OPENAI_MODEL`, then:

```bash
python scripts/run_benchmark.py benchmark/results   # resumable; skips existing dirs
gzip -9 benchmark/results/*/traces.jsonl            # commit results append-only
python scripts/build_leaderboard.py                 # regenerate the page
```
Then update the `[pending keyed runs]` sections of `docs/report.md` with the real
numbers and commit. Push to main → `pages.yml` redeploys the leaderboard.

## 4. PyPI trusted publishing (one-time; activates the release workflow's publish job)

1. Create/log into the PyPI account; register the project name `ledgerbench` promptly.
2. PyPI → Manage → Publishing → add a **Trusted Publisher**:
   repository `kartikeyamandhar/ledgerbench`, workflow `release.yml`,
   environment `pypi`.
3. GitHub → repo Settings → Environments → create `pypi` (no secrets needed — OIDC).
4. Re-run the `release` workflow for `v1.0.0` (or push the next tag). Verify:
   `docker run --rm python:3.12-slim sh -c "pip install ledgerbench -q && ledgerbench --help"`

## 5. Private split (RT-004)

Create the private repo `ledgerbench-private`; author the 30 items per
`docs/private-split.md`; run them locally only; publish aggregates only.

## 6. Cosmetics

- README screenshot of the demo report (needs a browser; `.ledgerbench/demo/report.html`).
- GitHub Release for `v1.0.0` with `docs/report.md` attached:
  `gh release create v1.0.0 --title "LedgerBench 1.0" --notes-file docs/report.md`
- External practitioner review pass over the item bank (RT-006).

## Already done (no action)

GitHub Pages is enabled (`build_type=workflow`); the leaderboard deploys on merge.
GHCR image pushes work with the workflow's built-in token. The naive floor tier is
committed and the report/leaderboard honestly mark everything else as pending.
