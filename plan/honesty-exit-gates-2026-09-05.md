# Honesty exit gates — acceptance ledger (2026-09-05) — historical batch snapshot

> Superseded by `plan/remaining-work-handoff-2026-09-05.md` for current status and commits.
> Follow-up: report honesty and typing fixed; full suite 1578 passed / 2 skipped;
> quality gates PASS. SG-202 frozen-roster replay 34/42 original cohort, 35/43 current
> measurable cohort (FAIL versus 95%). SG-201 external 11-repo measurement accepted;
> human study remains pending. The sections below preserve the earlier snapshot.

Live status for the 4 groups and honesty exit gates. Prior history (commits
`1254bdc`…`c745b47`, batches 1–2 + retrieval group) is NOT duplicated here — see
`plan/agent-batch-handoff-2026-09-05.md` (its intro now points back here).

Rules: no `PASS` until independently confirmed (ledger-owner run or reviewed diff, not
agent self-reports); frozen splits are never re-tuned (dev split only); no commits from
this ledger; statuses not owned here stay pending until the coordinator relays.

## 1. Group 1 — frozen 10-repo holdout `benchmarks/holdout_unseen` — ACCEPTED (bounded)

**Baseline CONFIRMED** on disk: 10 repos disjoint from dev 11; frozen 2026-09-05T11:18:35Z;
manifest sha256 `db0e8324…73919` (still unchanged); impact recall macro 0.9909 (601/217/
384 `sample_cap_25`); presence 1.0, false absence 0, test-selection 1.0, abstention 1.0;
retrieval Hit@1 0.8233 / Hit@5 0.9467 / MRR 0.8730 — reported, **not gated**; weakest
cells published (platformdirs 0.4667, attrs 0.6333).

**Freeze-enforcement repair: FINAL ACCEPTED — bounded baseline + split governance, NOT
global engine correctness.** 36 focused tests (19 split + 17 oracle/denominators);
malformed/empty manifest → exit 1; frozen-overwrite refused; tamper demo reproduced by
ledger owner (`SPLIT GOVERNANCE FAIL`, exit 1). SG-205→SG-204 label fix closed.

## 2. Group outcomes

### Group 3 — bundle honesty — ACCEPTED (coordinator-relayed + spot check)

- Independent pass: 27 tests + 30/31 adversarial (1 preexisting pattern-inference case);
  main separately 54 bundle/map/pack tests: pass; ledger-owner spot 12/12. Bundle
  3-states conformance coverage and schema-driven template accepted.
- Commit `8b45686` landed prematurely despite the no-commit rule; no rewrite/reset —
  history kept, diff reviewed after the fact.
- **Remaining (P1):** `src/sot_graph/analytics/report.py` (~418) still emits
  `ZERO_VIOLATIONS` CLEAN row; unqualified inferred-pattern label remains. Do NOT claim
  architecture reporting fixed.

### Group 2 — four-axis trust interface — ACCEPTED (coordinator-relayed + spot check)

- Independent pass: 138 focused tests; 55 axis tests (ledger-owner spot 55/55); a reviewer
  mention of `tests/test_holdout_end_to_end.py` refers to a nonexistent file — disregarded.
- Exact semantics (`evidence.py`): axes are `hit.axes` siblings; `identity` = whole-index
  bare-symbol uniqueness (not compiler resolution); `query_relevance` lexical (exact |
  semantic = token coverage | weak | unknown — not calibrated); per-hit
  `scope_completeness` **always `unknown`** — result-set coverage only via envelope
  `result_set.scope_completeness` (`bounded`), never repo-wide. Legacy STRONG/WEAK = compat.
- Doc sync (scoped, coordinator-corrected wording): `AGENTS.md` (both verdict blocks) +
  `README.md` (pillar 1, search example). `docs/KNOWN_LIMITATIONS.md` does not exist —
  not created. Claims lint clean.

### Group 4 — measurement — FINAL ACCEPTED (scores + metadata, no blockers); SG-202 gate NOT MET

- Reviewer final ACCEPT: SG-202 FAIL **0/42** and SG-201 contamination pilot **PASS 0/91**
  (controls 18.2%/14.5%) reproduced; 32-test final delta and worktree digest reproduced;
  no blockers. Measurement accepted as valid — **implementation NOT accepted for the
  SG-202 95% target** (0/42 at 1500 tokens). Human landmark study PENDING (≥3 human
  reviewers, protocol + worksheet manifest; simulated participants never qualify).
- JSON-verified denominators (`benchmarks/exit_gates/sg202_task_sufficiency.json`):
  attempted 90 = 42 measurable + **48 `no_relevant_test`** exclusions; the 1
  `contracts_overflow` (cap) case **overlaps inside the 48** (not additive). Failure
  modes on the 42: MISSING_TEST 26, MISSING_CONTRACTS 12, PACK_ERROR 4.
- Provenance: reports bind worktree digest **`e590733defd8540e`** (HEAD `8b45686a…`,
  37 dirty entries disclosed) — a **measurement-time snapshot only**: later docs
  edits/commits change the worktree digest; **no rerun needed**, and no claim that it
  matches the current tree exactly forever.
- Diff-impact (heuristic engine): 37 files, 228 direct, 145 callers, 51 tests impacted;
  reconcile 11 updated, 0 failed.

## 3. Toolchain snapshot (main final quality tester, relayed)

- Full suite latest: **1504 passed / 2 skipped**.
- `scripts/quality_gates.sh`: **FAIL — preexisting pyright** at
  `src/sot_graph/assurance/accounting.py:320` (`visit_AsyncFunctionDef = visit_FunctionDef`
  signature mismatch); file unchanged from base (git-verified); **no fix in this scope**.
  **Do NOT claim full quality gates green.**
- Separate PASSes: coverage **core 87%, receipts 94%**, bandit, pip-audit, ruff,
  claims lint, diff check.

## 4. Honesty exit gates — status

- **SG-201 human study: PENDING** — ≥3 real human reviewers (protocol + worksheet
  manifest); simulated or agent-acted participants never satisfy this gate.
- **SG-201 contamination: measurement ACCEPTED** (0/91 pilot pass, reproducible; controls
  18.2%/14.5%) — accepted at pilot scope.
- **SG-202 task-sufficiency: NOT MET** — measurement accepted, 0/42 << 95% floor; stays
  failed until an accepted re-measurement passes.

## 5. Claims registry — provenance correction APPLIED & VERIFIED (2026-09-05)

Scoped correction authorized by coordinator; `claims/registry.yaml` only: repointed 3
claims (`search-semantic-row`, `search-overall-row`, `capability-hit-rates`) from
`9127367e…` (plan-docs-only commit; artifact then read 0.9375/0.75) to
`c745b4720b9e3315758b4a2582c7e984718747f7` after pre-edit git-show verification (1.0/1.0
at that commit; commit touched artifact+registry+docs). Post-edit lint clean (10 claims,
15 files, 29 hits). Reported-only: optional hygiene repoints (`search-exact/ambiguous/
path-qualified` → `c745b47` same-byte trace; `root-isolation-guarantee` → `6e408ab`);
linter hardening out of scope.

## 6. Protocol

- Registry/docs changes must keep `sot claims lint` clean; frozen splits publish deltas, never silent replaces.
