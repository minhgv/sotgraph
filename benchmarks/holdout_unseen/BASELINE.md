# Unseen holdout split — frozen baseline (SG-204 follow-up:
# untouched-holdout governance)

Frozen provenance (see honesty note below on what "frozen" does and
does not prove; verified by `tests/test_holdout_splits.py`):

- manifest: `manifest.json`, sha256 `db0e8324de2a6355b8aba52b0937996795fac098237740369ded0d0870a73919`
- frozen_at: `2026-09-05T11:18:35Z`; selection: `scripts/bench_holdout_select.py`
  (deterministic; git history + stdlib-ast oracle ONLY — no production engine
  consulted at selection time)
- split: 10 repos disjoint from the 11-repo development/regression corpus
  (`benchmarks/holdout`): attrs, filelock, iniconfig, more-itertools,
  platformdirs, pluggy, pyflakes, python-dateutil, soupsieve, sqlparse
- policy: `tuning_exclusion: true` — no extractor, ranking, gate, or
  threshold change may be authored from this split's scores. The dev
  split is the only tuning-eligible corpus.

Honest scope of the freeze: the sha-256 verifies the INTEGRITY of the
binding between `FREEZE.json` and the exact manifest bytes, and the
report's `manifest_digest` binds the evaluation to the same bytes. It
does NOT cryptographically prove the historical ORDER
(freeze-before-evaluation): that chronology is RECORDED — the
`frozen_at` timestamp, the freeze-then-run workflow in
`scripts/bench_holdout_select.py`, and this file — not proven. The
runner now enforces the binding fail-closed before any evaluation or
selfcheck (`bench_holdout.py --selfcheck` refuses a tampered manifest),
which makes post-freeze tampering detectable, though not retroactively
impossible for an author with filesystem access before the gate existed.

Baseline command (single evaluation of the frozen bytes):

```
.venv/bin/python scripts/bench_holdout.py \
  --manifest benchmarks/holdout_unseen/manifest.json \
  --repos-dir .holdout-cache-unseen \
  --report benchmarks/holdout_unseen/report.json --ensure-clone
```

Results (10/10 repos measured, 0 run errors; schema 2 with denominators):

| metric | value | denominator (universe / measured / excluded) |
| :-- | :-- | :-- |
| presence precision (macro/min) | 1.0 / 1.0 | 9306 / 9306 / 0 |
| false absence (total) | 0 | 8246 / 8246 / 0 |
| impact recall (macro) | 0.9909 | 601 / 217 / 384 (`sample_cap_25`) |
| test-selection recall (macro) | 1.0 | 19 / 19 / 0 |
| abstention accuracy | 1.0 | 200 / 200 / 0 |
| retrieval Hit@1 / Hit@5 / MRR (macro, reported not gated) | 0.8233 / 0.9467 / 0.8730 | 30 queries x 10 repos |

Gates: presence >= 0.995, false absence == 0, impact recall >= 0.95,
test-selection recall >= 0.98 — **all pass**. Weakest published cell:
platformdirs retrieval Hit@1 = 0.4667 (MRR 0.6661); attrs Hit@1 = 0.6333.

Honest limitations:

1. Same selection RULE as the dev corpus (most recent non-merge commit
   with 1-4 source .py + tests, non-empty top-level delta, >=1 GT test).
   The rule is oracle-measurability only, but the system WAS iterated
   against dev-corpus-shaped tasks, so these numbers may be optimistic
   for adversarial distributions.
2. One evaluation, one snapshot, Python-only, mostly small repos;
   selection-time HEADs drift upstream — the frozen manifest is the SSOT,
   re-running selection later pins different commits.
3. Impact recall denominator publishes the 25-edge/repo sample cap
   (384 excluded); per `score_basis` all scores are
   measured-denominator-only.
4. This baseline must not be re-run-and-replaced silently: any re-run
   publishes deltas against this file, and the selector refuses to
   regenerate over a frozen generation (new generations need a new
   `--output` path and their own FREEZE record).
5. Chronology disclosure (repeat for emphasis): freeze-before-evaluation
   is recorded, not cryptographically proven; the enforced gate is
   binding integrity (any post-freeze byte change fails the runner).
