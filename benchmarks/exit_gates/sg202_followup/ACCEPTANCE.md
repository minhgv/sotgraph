# SG202 Independent Reviewer Acceptance — FINAL

Reviewer: independent SG202 reviewer agent. Repo untouched (read-only); all
artifacts produced under /tmp/sg202-final-independent/. Author declared FINAL
stable; no writers active during measurement.

## Decisive verdict

**Gate `sg202_task_sufficiency >= 0.95`: FAIL — 0.814 on 43 measurable.
Honest failure; no relaxed criteria applied.**

Primary metric: EXACT frozen 90-task roster (keys taken from
`benchmarks/exit_gates/sg202_task_sufficiency.json`, no re-sampling), replayed
end-to-end with the current stable worktree (own temp index, workers=4,
budget 1500, contracts cap 8, max_nodes 50, max_bytes 65536, oracle helpers
unmodified, current `sot_graph.pack`).

| cohort | n | full_success | sufficiency |
| :--- | --: | --: | --: |
| baseline-measurable cohort (frozen baseline snapshot) | 42 | 34 | **0.8095** |
| current measurable cohort | 43 | 35 | **0.8140** |
| all sampled | 90 | 35 | 0.3889 |

The replay.json gate block records `passed=false, verdict=FAIL` alongside full
provenance: git HEAD `8b45686a0ccf`, worktree digest `7fb059223fa4b6fe`
(digest_truncated=false), SHA256 of the frozen baseline report, of
`src/sot_graph/pack.py`, and of the oracle fixture, plus the exact
reproduction command. The replay script is portable (`--root/--output-dir`,
no hardcoded absolute paths). The author's "37/53 fresh pilot" used a changing
sample and is not comparable; the frozen-90 replay is the published metric.

Measurability delta baseline42 -> current43 is exactly one task,
`src/sot_graph/assurance/accounting.py::_LimitVisitor` (0 -> 1 relevant test
refs), attributed to the new test file `tests/test_accounting_visitor_typing.py`
(real ast reference). Both cohorts published.

## Remaining failures — 8 of 43 (5 MISSING_TEST + 3 PACK_ERROR)

- 3 PACK_ERROR = AMBIGUOUS_TARGET (`as_dict`, `_tag`, `__exit__`): safe
  fail-closed with candidates; dominant-candidate rule declined to guess.
- 5 MISSING_TEST (`CoverageState`, `Claim`, `FreshnessStatus`, `_ConnView`,
  `_index_binding`): relevant tests reference the bare name but never call it,
  so no caller edge can honestly exist under the current call-edge oracle.
- MISSING_CONTRACTS = 0, MISSING_TARGET = 0, OVER_BUDGET = 0.

Scope statement on the floor: 0.95 is currently unreachable through pack
allocation alone under the present graph/oracle/query contract (bare-name
task queries; receipt = call-edge from a filename-classified test module).
This is NOT a claim that 0.95 is inherently impossible: valid future design
work — qualified-identity task selection, usage-evidence edge types, or
oracle-contract revisions — could legitimately move the metric.

The earlier `reconciler.py::reconcile` regression (MISSING_TEST after the
node-cap reservation change) was repaired by the author and is FULL_SUCCESS in
this final replay (35/43); the only improvement vs the prior reviewer run.

## Acceptance checks (independent, final run)

1. Unchanged 1500 budget = real serialized cost: PASS. Enforcement measures
   `estimate_tokens(render_yaml(bundle))` on the real render (tiktoken cl100k
   present, so the evaluator recompute uses the same tokenizer); over_budget=0;
   max recomputed exactly 1500 <= 1500; independent raw-tiktoken count never
   exceeded the estimator. No placeholder estimates in the enforcement path.
2. Oracle honesty / no invented evidence: PASS. Contracts credited only on
   oracle `(callee_path, callee_name)` identity; receipt requires a graph
   inbound edge from a relevant test module. 32 outbound entries lack an
   oracle edge (extractor disagreement — real indexed symbols, none
   credit-earning). GT fixture: 9 curated cases; strictly additive vs the
   session-start snapshot. During review the fixture's McpService entry was
   accidentally replaced (new entry swapped in, prior entry dropped, count
   unchanged at 26); this reviewer flagged it, the author restored the
   dropped `tests/test_report_conformance.py`, and the final fixture (27
   entries) exactly equals the independently recomputed heuristic set. The
   validator was mutation-tested fail-closed from a /tmp tampered copy.
3. Ambiguity resolution safe: PASS (2x-dominance auto-resolve, disclosed;
   3 roster tasks auto-resolved, 3 fail closed).
4. Oversized targets bounded reads + partial flags: PASS. Streaming sha256,
   1 MiB materialization cap; `source_read_bounded` now sets
   `limits.truncated=True` + `completeness=PARTIAL` (probe P6).
5. Byte pass order: PASS. Source squeezed (byte floor 192) before callees are
   popped; exceed-cap only in the declared `byte_cap_unreachable` mode with an
   explicit warning (probe P5 hard byte semantics).
6. Node-cap retention after value ordering: PASS. Probe P2b: cap=2 with
   1 test + 3 prod callers + 1 same-file contract retains test caller +
   contract.
7. Same-file ordering: PASS (exact-file class 0, same-directory 1, elsewhere 2).
8. Metadata compaction honesty: PASS. Under token pressure the serialized
   neighbor rows may omit `node_id` and default-`FRESH` `trust_verdict`
   (derivable fields); `relative_path`, `fqn`, `callsite_line`,
   `contract`/`signature` always preserved; non-default verdicts kept and
   lead the row; the in-memory dict keeps all fields; disclosure warning +
   `metadata_compact` flag set; rolled back when it does not shrink.
9. Thin-source disclosure: counts published as HEURISTIC size labels (chars
   are a proxy, small defs are legitimately small; truncation flags are the
   definitive signals): full_success with <400-char source 15/35; source-
   truncated-flagged among full_success 17; truncated AND <200 chars 8.
   Every truncation is machine-disclosed (`truncated`, `source_truncated_cause`,
   accounting `partial` + returned/recorded lines). No undisclosed placeholder
   passes.
10. Tests: author dedicated SG202 suite 21/21; FULL `tests/` INCLUDING
    `tests/holdout`: **1578 passed, 2 skipped, 0 failed** (independent run).

## Bottom line for main

Publish the frozen-90 replay as the real metric: **0.814 measurable
(34/42 = 0.8095 on the baseline cohort), gate FAIL vs 0.95, denominator 43**,
with the counters above and the provenance-bound replay.json. Do not accept
changing-sample claims. The gate remains honestly open.

## Reproducibility

```
cd <sot-graph checkout>
.venv/bin/python /tmp/sg202-final-independent/replay_sg202.py \
    --root . --output-dir /tmp/sg202-final-independent
```

Artifacts: `replay.json` (provenance + summary + per-task + baseline diff),
`replay_sg202.py` (portable), `probes.py` / `probes2.py` (adversarial P1-P6).
