# Release Notes — v0.3.8 (2026-09-19)

Hunk-verified commit verdicts on every surface, a persistent CBM engine
daemon, and honest identity loading across the analytics stack. G3
hand-label precision improved 0.6364 → 0.7778; the full suite is green
at 2495 tests.

## Commit verdicts now hunk-verified everywhere

`make_hunk_verifier` is wired into all five verdict surfaces —
`cmd_commit_verdict`, `log --outcomes`, `sot_commit_verdict` (MCP),
`lineage._verdict_for`, and `bench_g3_verdict.py`. Previously only
`cmd_calibrate` verified hunks; file-level linkage alone could not
distinguish same-file-different-region churn from a real repair.

Measured on the frozen G3 roster: hand-label precision **0.6364 →
0.7778** (98 still-hot, 181 unknown). The 2 residual mismatches are
documented boundary cases where hunk overlap cannot distinguish a repair
from an adjacent doc edit — not bugs.

## `direct_affected_files` — 1-hop evidence surface on scope receipts

`scope_receipt` and `scope_receipt_multi` now expose a narrow 1-hop
surface (target file + direct callers/callees) alongside the full
transitive `affected_files` blast radius. The narrow surface is what a
fixer actually opens first; precision metrics can now score both
surfaces honestly.

- `bench_g1_scope.py` reports `precision_union` and `precision_direct`
  in parallel, plus `precision_drop_direct` as an informational
  (non-gated) check.
- G1 replay: union drop 0.1917 (FAIL vs 0.10 bar — blast-radius
  construction); direct-surface drop **−0.054** (union 1-hop precision
  0.3674 > best-single 0.3134). The direct surface is the actionable
  metric going forward.

## Persistent engine daemon + two-tier JIT reconcile

- CBM engine stays alive across CLI invocations via a per-account Unix
  socket — eliminates per-query process spawn cost.
- Newest-wins union merge strategy + async JIT reconcile on
  publish-snapshot reads (W10).
- `sotgraph reconcile` auto-acquires the pinned engine binary when
  absent — no separate `sotgraph setup` required.

## Identity loading — real names instead of `cbm:<id>`

`AnalyticsGraph.from_connection` now reads `symbol`/`fqn` from
`graph_nodes`. `GodNodeInfo`, `SurprisingConnection`, and all
bundle/report/MCP/export consumers display real symbol names instead of
opaque `cbm:<id>` placeholders.

`_identity_grade` now prefers the canonical `symbol` field (bare name)
→ `fqn` → `label`. `label` is a display string (`"def f — path:line"`),
not a name — the previous label-primary ordering broke exact-match
grading on real search rows.

## `pack` — scoped locators and import-edge awareness

- `path::name` scoped locators accepted in `_parse_target` —
  disambiguate same-name symbols by file scope.
- `_neighbors` includes `imports` edges with a typed `relation` field
  distinguishing import-only edges from direct call/extends edges.
- Scoped-ambiguity falls back to global dominant when in-scope;
  module-import test receipt fallback (`imports_module`).
- `_test_line_by_id` type annotation corrected (`Dict[str, int]` →
  `Dict[str, Tuple[int, int]]`); `_path_in_scope` suffix overreach
  tightened to exact/`/`-boundary/absolute-suffix only.

## Windows portability

Separator-agnostic path matching in pack target recovery and dangling
sweep; never probe liveness with `os.kill(pid, 0)`; normalize CBM store
path shaping; skip AF_UNIX daemon tests on win32.

## Six verified defects resolved

All six defects from `report_bug_20260913` fixed across CLI, MCP, and
graph surfaces.

## Benchmark status

| Gate | Score | Bar | Status |
| :-- | :-- | :-- | :-- |
| SG-202 task-sufficiency | 0.8864 (39/44) | ≥ 0.95 | Open — 5 MISSING_TEST are structural extractor gaps |
| G3 hand-label precision | 0.7778 | ≥ 0.80 | Open — 2 residual boundary mismatches |
| G1 union precision drop | 0.1917 | ≤ 0.10 | Open — blast-radius construction; direct surface −0.054 |
| SG-201 landmark | — | — | PENDING_HUMAN_EVIDENCE (≥3 reviewer CSVs) |

## Verification

- Full suite: **2495 passed, 0 failed, 5 skipped** (628.85s)
- Pyright: 0 errors on changed files
- Louvain clustering: **5.3s** on 35,905 nodes / 166,668 edges
  (networkx 3.6.1, core dep)
