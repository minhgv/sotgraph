# Integration handoff — 2026-09-05

## Current outcome

Implementation and independent acceptance are complete for this batch. Branch: `work/holdout-honesty-gates`. Local commits only; nothing pushed. Product gates are distinct from code-quality acceptance: SG-202 remains FAIL; SG-201 human study remains PENDING.

Before integration there were 88 changed/untracked files, including 49 benchmark artifacts. The unrelated `plan/python-c-monorepo-architecture-plan-2026-09-05.md` was preserved and deliberately excluded; it was not authored or reviewed by this batch.

## Integrated commits

- `9d81297`: frozen unseen holdout and fail-closed split governance, plus artifact ignore exceptions.
- `50bf330`: independent four-axis search trust interface and documentation.
- `4fc305b`: shared report/bundle conformance assessment, actual CLI/MCP coverage, qualified pattern inference, removal of ungrounded recommendation claims.
- `8766b4b`: typed sync/async accounting visitor wrappers and regression tests.
- `3223b7a`: SG-201/SG-202 evaluators, original pilot reports, human protocol and worksheet.
- `e166795`: eleven-repository external contamination measurement and pin-integrity validation.
- `5c859c4`: pack priority allocation, bounded/partial source disclosure, metadata compaction and regression tests.
- `287eac3`: claims registry historical provenance correction.
- Subsequent report/handoff commit contains this file and the independent SG-202 replay.

The original architecture commit `8b45686` and older history were preserved. A newly created integration commit accidentally collected several staged groups after CSV CRLF whitespace checks failed; that same unpublished commit was immediately split into the logical groups above, without changing worktree content. CSV bytes and their manifest binding were preserved; whitespace verification uses `core.whitespace=cr-at-eol` for the standard CSV line endings.

## Independent acceptance

- Full `tests/`: **1578 passed, 2 skipped**, zero failures.
- Real `scripts/quality_gates.sh`: PASS, including core Ruff/Pyright, coverage **core 87% / receipts 94%**, Bandit and pip-audit (no known vulnerabilities).
- Additional Ruff on all 30 changed/new Python files: PASS. Extra Pyright on pack, analytics and evaluator implementation scope: zero errors.
- A broader, non-gating Pyright sweep including test files still reports test typing/import-configuration issues; do not describe the whole repository as universally type-clean.
- Independent main diff review plus separate authors/reviewers reproduced and repaired byte/node-cap priority, source partial-flag loss, recommendation claim leakage and pinned-checkout validation defects.
- `sot reconcile`: 63 updated, 322 unchanged, zero purged/failed at final code snapshot. Doctor: schema 8, quick_check OK, no orphan nodes. Diff-impact uses AST heuristic evidence, not compiler-exact proof.
- Full test/gate logs: `/tmp/sg-followup-accepted-full.log`, `/tmp/sg-followup-accepted-quality.log`, `/tmp/sg-followup-accepted-ruff.log`, `/tmp/sg-followup-accepted-pyright.log` (temporary local diagnostics, not durable artifacts).

## SG-202 — still FAIL, highest remaining product priority

Independent replay uses the **exact original 90-task roster**, budget **1500 tokens**, unchanged oracle rules and 95% floor:

| Cohort | Success | Rate |
| --- | ---: | ---: |
| Original 42 measurable tasks | 34/42 | 80.95% |
| Currently measurable tasks on that same roster | 35/43 | 81.40% |
| All sampled tasks | 35/90 | 38.89% |

The one newly measurable task is `_LimitVisitor`, due to a real new accounting test reference. These cohorts must not be conflated. The changing-sample author pilot 37/53 is not the before/after comparison.

Remaining eight current-measurable failures:
1. Three `AMBIGUOUS_TARGET`: `as_dict`, `_tag`, `__exit__`. Preserve fail-closed behavior; investigate explicit qualified identity selection without picking arbitrary candidates or removing difficult tasks.
2. Five `MISSING_TEST`: `CoverageState`, `Claim`, `FreshnessStatus`, `_ConnView`, `_index_binding`. Current relevance oracle recognizes name/attribute references while receipt requires a caller edge. Design and validate genuine usage evidence or improve extraction where justified; do not fabricate call edges or silently relax the benchmark.

No missing-contract outcomes or token-budget violations in this frozen replay. The `reconcile` regression is repaired. Partial source remains a limitation: the final independent report counts 17 of 35 successes with truncated source; thin-source counters are heuristic, not proof of usefulness. Retain explicit partial/line-count metadata. Further work should improve substantive source context, not exploit the evaluator's nonempty-source check.

Durable evidence:
- `benchmarks/exit_gates/sg202_followup/ACCEPTANCE.md`
- `benchmarks/exit_gates/sg202_followup/replay.json`
- `benchmarks/exit_gates/sg202_followup/replay_sg202.py`

Reproduce to a NEW output directory:

```sh
.venv/bin/python benchmarks/exit_gates/sg202_followup/replay_sg202.py --root . --output-dir /tmp/sg202-replay-next
```

Report provenance records the measurement-time HEAD/worktree digest and SHA-256 of pack, baseline and oracle fixture. Later commits naturally change HEAD/digest; this does not rewrite measurement history. Original baseline files remain unchanged.

## SG-201 — automated external measurement accepted; human gate open

- External development/regression corpus: **11/11 repos PASS**, contamination 0% across measured default cells, budgets 1024/2048, strict threshold below 2%, minimum 50 symbols for sufficient sampling.
- Four 1024-token cells are below minimum sample size; each repository's 2048 run is sufficiently sampled. Do not label all budget cells as individually well-sampled passes.
- Pin checks reject tracked/untracked source changes before and after measurement; benign `.sot/` cache is exempt. Duplicate/unsafe identities and tuning-excluded manifests are refused.
- Limitation: no symbol-bearing fixture/vendor code in this corpus; 0% control runs do not establish detector sensitivity. Synthetic controls provide sensitivity evidence. A future external contamination-rich corpus would strengthen acceptance; do not tune on unseen holdout.
- Evidence: `benchmarks/exit_gates/external/sg201_external_corpus.{json,md}` and per-repo/rendered artifacts. Superseded HEAD-only-pin reports are explicitly named and retained.
- **Human study: 0 of at least 3 real reviewers; PENDING_HUMAN_EVIDENCE.** Use `plan/sg201-landmark-study-protocol.md` and manifest-bound worksheet. No agents posing as humans, no manufactured CSVs; aggregation stays pending manual verification.

## Lower-priority backlog not implemented

- Real external CBM/SCIP federation evidence and provider comparison corpus.
- SG-301 characterization tests before hotspot-module extraction/refactoring.
- Multi-signal repo-map ranking beyond PageRank.
- SBOM/provenance choice and maintainer decisions for CODEOWNERS, SECURITY contact and Dependabot ecosystem.
- Claims-linter validation against historical artifact snapshots, not merely ancestry/current values.

## Constraints for the next batch

- User requested commit and handoff, not further expansion of this batch. Stop implementation here.
- Never tune against `benchmarks/holdout_unseen`; frozen manifest SHA-256 remains `db0e8324de2a6355b8aba52b0937996795fac098237740369ded0d0870a73919`.
- Delegate independent file ownership; main reviews actual diffs; a different agent tests. Do not let multiple authors mutate the same pack file concurrently.
- Commit accepted logical groups promptly rather than accumulating another large uncommitted batch.
- No push or external publication without authorization.
