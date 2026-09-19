# Changelog

All notable changes to sotgraph are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 2026-09-19

### Added

- **`direct_affected_files` on scope receipts** — `scope_receipt` and
  `scope_receipt_multi` now expose a 1-hop evidence surface (target file +
  direct callers/callees) alongside the full transitive `affected_files`
  blast radius. The narrow surface is what a fixer actually opens first;
  precision metrics can now score both surfaces honestly. Per-target
  `direct_affected_files` also exposed in `per_target` blocks.
  (`src/sot_graph/assurance/receipts.py`)
- **Dual-surface precision reporting in G1 benchmark** —
  `bench_g1_scope.py` reports `precision_union` (full blast radius) and
  `precision_direct` (1-hop surface) in parallel, plus
  `precision_drop_direct` as an informational (non-gated) check.
  (`scripts/bench_g1_scope.py`)
- **`path::name` scoped locators in pack target parsing** —
  `_parse_target` accepts `path::symbol` so agents can disambiguate
  same-name symbols by file scope. (`src/sot_graph/pack.py`)
- **`--target-mode scoped|bare` on SG-202 replay** — frozen-roster
  replay can run in scoped or bare target mode for honest comparison.
  (`benchmarks/exit_gates/sg202_followup/replay_sg202.py`)

### Fixed

- **Commit verdicts now hunk-verified on every surface** —
  `make_hunk_verifier` wired into `cmd_commit_verdict`,
  `log --outcomes`, `sot_commit_verdict` (MCP), `lineage._verdict_for`,
  and `bench_g3_verdict.py`. Previously only `cmd_calibrate` verified
  hunks; file-level linkage alone could not distinguish
  same-file-different-region churn from a real repair. G3 hand-label
  precision 0.6364 → 0.7778. (`src/sot_graph/cli.py`,
  `src/sot_graph/mcp_service.py`, `src/sot_graph/assurance/lineage.py`,
  `scripts/bench_g3_verdict.py`)
- **Identity grading uses canonical `symbol` field** — `_identity_grade`
  now prefers `symbol` (bare name) → `fqn` → `label`. `label` is a
  display string (`"def f — path:line"`), not a name; the previous
  label-primary ordering broke exact-match grading on real search rows.
  (`src/sot_graph/cli.py`, `tests/test_p4_ranking.py`)
- **`symbol`/`fqn` loaded into `AnalyticsGraph`** —
  `AnalyticsGraph.from_connection` now reads `symbol`/`fqn` from
  `graph_nodes`; `GodNodeInfo`, `SurprisingConnection`, and
  bundle/report/MCP/export consumers display real names instead of
  `cbm:<id>` placeholders. (`src/sot_graph/analytics/graph.py`,
  `src/sot_graph/db.py`, `src/sot_graph/mcp_service.py`,
  `src/sot_graph/analytics/{architecture,bundle,diagnostics,report}.py`,
  `src/sot_graph/export/{arch_flow,arch_html,html}.py`,
  `src/sot_graph/mcp_server.py`)
- **`_neighbors` includes `imports` edges** — typed `relation` field
  distinguishes import-only edges from direct call/extends edges;
  scoped-ambiguity falls back to global dominant when in-scope;
  module-import test receipt fallback (`imports_module`).
  (`src/sot_graph/pack.py`)
- **`_test_line_by_id` type annotation** — stores `(strength, line)`
  tuples; corrected `Dict[str, int]` → `Dict[str, Tuple[int, int]]`
  (pyright gate). (`src/sot_graph/pack.py`)
- **`_path_in_scope` suffix overreach** — bare `p.endswith(s)` matched
  `test_utils.py` against scope `utils.py`; tightened to exact match,
  `/`-boundary suffix, or absolute-path suffix only — mirroring
  `_path_scope_sql`. (`src/sot_graph/pack.py`)

### Changed

- **SG-202 task-sufficiency score** — 0.8182 → 0.8864 (39/44) on the
  frozen roster; remaining 5 `MISSING_TEST` failures are structural
  extractor gaps (no `uses`/`references` edges for `x.as_dict()` on
  returned objects, monkeypatched attrs, `with` protocol methods,
  same-name test functions). Gate remains honestly open.
- **SG-201 landmark worksheet + manifest** — regenerated at HEAD
  (20 rows, budget 1024). Protocol unchanged; gate remains
  `PENDING_HUMAN_EVIDENCE` pending ≥3 reviewer CSVs.
  (`benchmarks/exit_gates/landmark/`)

### Verification

- Full suite: **2495 passed, 0 failed, 5 skipped** (628.85s)
- Pyright: 0 errors on changed files
- G1 replay: union precision drop 0.1917 (FAIL vs 0.10 bar — blast-radius
  construction); direct-surface drop **−0.054** (union 1-hop precision
  0.3674 > best-single 0.3134)
- G3 replay: hand precision **0.7778** (98 still-hot, 181 unknown;
  2 residual mismatches are documented boundary cases where hunk overlap
  cannot distinguish repair from adjacent doc edits)
- Louvain clustering: **5.3s** on 35,905 nodes / 166,668 edges via
  `nx.community.louvain_communities` (networkx 3.6.1, core dep)
