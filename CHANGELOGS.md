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
- **Persistent engine daemon** — CBM engine stays alive across CLI
  invocations via a per-account Unix socket; eliminates per-query
  process spawn cost. (`6f00a8c`)
- **Two-tier JIT reconcile** — newest-wins union merge strategy +
  async JIT reconcile on publish-snapshot reads (W10). (`6f00a8c`,
  `47aec4a`)
- **Auto-acquire CBM engine on reconcile** — `sotgraph reconcile`
  bootstraps the pinned engine binary when absent instead of
  requiring a separate `sotgraph setup`. (`5f265c5`)

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
- **Six verified defects from `report_bug_20260913`** — resolved across
  CLI, MCP, and graph surfaces. (`06921fd`)
- **Windows portability** — separator-agnostic path matching in pack
  target recovery and dangling sweep; never probe liveness with
  `os.kill(pid, 0)`; normalize CBM store path shaping; skip AF_UNIX
  daemon tests on win32. (`a6c671d`, `4bbce2d`, `ff81d67`)
- **CI green main** — five root causes across Test, Module Eval, E2E,
  and Quality Gates restored. (`d9932e3`)
- **Fire-and-forget reconcile in harness extension templates** —
  adapters no longer block on reconcile completion. (`36a72de`)

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

---

## [0.3.7] — 2026-09-15

**Theme**: CBM-native graph store — reconcile is cbm-primary, tree-sitter
fallback. The codebase-memory engine becomes the default extraction
backend; the builtin tree-sitter extractor remains the always-available
fallback tier.

### Added

- **W9 CBM-native graph store** — `sotgraph reconcile` dispatches to the
  CBM engine as the primary extractor; tree-sitter is the fallback when
  the engine is unavailable. (`1fe0d17`)
- **W6-W8 assurance extensions** — semantic-break gate, learned risk
  model, zero-friction adoption. (`a71e5d1`)
- **Engine auto-acquire** — reconcile path auto-bootstraps the pinned
  engine binary. (`5f265c5`)

### Fixed

- All remaining read surfaces routed through `open_store`; dispatch
  everywhere reconcile runs. (`ecc578d`)

---

## [0.3.6] — 2026-09-14

**Theme**: Three-gate assurance loop complete — plan-scope → pre-commit
gate → post-commit outcome verdict is now a queryable lineage chain.

### Added

- **`receipt chain` — lineage dossier (W5)** — `sotgraph receipt chain
  <ref>` assembles scope → diff → commit → verdict into one dossier;
  `diff_impact` receipts carry `lineage{scope_receipt_digest, head_sha,
  minted_at}`; `scope-receipt` persists content-addressed into
  `.sot/receipts/`. (`0f3e5ce`)
- **Commit-outcome monitoring (W0, W3)** — `sotgraph log --outcomes`
  classifies each commit `clear-fault` / `still-hot` / `unknown`;
  per-risk-level calibration `P(still-hot | level)`; MCP tool
  `sot_commit_verdict`. (`d289472`, `e1a3213`)
- **Pre-commit gate (W1, W2)** — `scope-receipt` accepts multiple
  targets (union blast radius); `diff-impact` receipts carry
  `safe_commit{verdict: pass|warn|block}`; `--gate-strict` exits
  non-zero on `block`; `--test-report` feeds caller-supplied test
  outcomes. (`916b4a1`, `245538c`)
- **Accuracy foundations (W4)** — receiver disambiguation
  (`self.get()` / nested-scope `get()` no longer bind to same-named
  module-level decoys); `TestImpact.impact_reason` distinguishes
  `calls_modified_node` from `imports_modified_module`. (`74848fb`)

### Fixed

- MCP server starts degraded when `.sot/sot.db` is missing — tools
  return `database_unavailable` instead of killing the process;
  per-operation timeout budget. (`833b160`)
- `receipt_digest` volatile set strips `minted_at` and
  `graph_freshness` — identical content previously hashed differently
  per call, breaking executor↔MCP↔CLI digest parity. (`8bca299`)

### Verification

- Full suite: **2437 passed, 0 failed**.

---

## [0.3.5] — 2026-09-13

**Theme**: Diff receipt closes the loop — from "what was affected" to
"what is left unresolved".

### Added

- **P7.3 resolution ledger (receipt schema 1.9)** — every post-change
  receipt now includes a `resolution_ledger` block with three read-only
  collectors:
  - **Disposition matrix** — attach a PRE-change scope receipt
    (`--pre-receipt <digest|file>`) and classify each predicted direct
    caller and candidate test as `addressed` or `untouched`.
  - **Dangling-reference sweep** — decision-grade: any hit feeds
    `unresolved_count`, forces `unresolved_over_budget`, and blocks
    closure. Three nets: pending_edges UNRESOLVED/AMBIGUOUS from diff
    files, pending rows pointing at vanished pre-change symbols, and
    rename/delete leftover callers.
  - **Debt markers** — TODO/FIXME/HACK/XXX/`type: ignore`/`noqa`/bare
    `except:` introduced on ADDED diff lines; capped at 50 via
    `DEBT_MARKERS_SOURCE`. (`faf8bdc`)

### Changed

- Skill descriptions sharpened across all four harnesses (antigravity,
  omp, opencode, zcode) — lead with "Use for ANY codebase structural
  query" trigger wording. (`999286b`)

### Verification

- 16 new tests; full suite 2339 passed / 5 skipped / 22 failed (all
  within documented pre-existing failure set; no new regressions).

---

## [0.3.4] — 2026-09-12

**Theme**: Self-healing queries, architecture viewer, honest target
recovery.

### Added

- **`sotgraph arch` — deterministic tiered architecture HTML** —
  renders a dependency-layered diagram from the verified graph;
  `--flow "<target>"` for call-flow view; `--level module` for
  module-level layered system view. Stages 1–4 closed with DoD
  verified. (`82dbd1e` → `7c28215`, `2505695`)
- **JIT Freshness Gate** — `search`, `explore`, `usages`,
  `implementations`, `map`, `pack`, `trace` (CLI + MCP) and
  `diff-impact` probe `.sot/sot.db` against disk before answering and
  reconcile first when anything drifted. Modes: `auto` (default) |
  `force` | `off`. Never blocks — if reconcile fails the query still
  answers from the stale graph with `status: failed` disclosed.
  (`4f0133a`)
- **`pack` target recovery** — agent display-string targets
  (`"func main — backend/cmd/server/main.go:28"`) now resolve via a
  ladder: exact FQN → FQN suffix → path-scoped bare symbol →
  `path:line` containment → fuzzy candidates. Honesty disclosures:
  `PATH_LINE_RESOLVED` / `NORMALIZED_TARGET`. (`b5cd002`)
- **`scope-receipt` identity recovery + rename-gate disclosure** —
  falls back to the same recovery grammar when exact-match fails;
  receipt schema 1.7 → 1.8 with `identity.recovery` block; CLI prints
  `target recovered: '<query>' → '<fqn>'` and `✅ rename gate passed`.
  (`d3999cd`)

### Fixed

- Verified GPT-6-Astra benchmark findings: false receiver edges, B3
  pack truncation, lost `prepare` edge. (`4a1265e`)

### Changed

- Grammar table 10 → 21 registered tree-sitter grammars, scoped to
  builtin tier; CBM engine language coverage stated; MCP tool count
  corrected. (`45db7b8`, `21cdd1e`)

---

## [0.3.3] — 2026-09-11

**Theme**: Distribution rename `sot-graph` → `sotgraph` + trusted CBM
engine bootstrap.

### Changed

- **Distribution rename** — PyPI distribution, CLI, MCP server key,
  harness artifacts, and docs all renamed `sot-graph` → `sotgraph`.
  Python import package remains `sot_graph`. `sotgraph setup` migrates
  or removes provably-ours legacy artifacts. (`ac26089`, `0e4413a`,
  `5bbcbe6`)
- **CBM engine via trusted bootstrap** — `pipx install sotgraph` +
  `sotgraph setup` is the complete provisioning path. Engine binary
  pinned per platform in `engine_pins.json` (`engine-v2026.09.07`),
  fetched at setup time, verified against pinned sha256 + size,
  promoted via digest-addressed artifact store at
  `~/.sotgraph/engine-store`. Never pip/npm-installed, never
  download-on-query. (`ac26089`, `9916811`)
- **Internal MCP client** — sotgraph speaks to the engine over MCP
  stdio with per-account runtime namespace and isolated cache.
  (`ac26089`)
- **Engine admin requires `--store`** — every `sotgraph engine`
  operation names the trusted store explicitly. (`a4fa508`)

### Fixed

- Cross-platform CI: py3.10 digest, bandit nosec, windows portability;
  skip POSIX-gated engine/trusted-config suites on win32; kernel pipe
  handle to `wait()` on win32 in engine MCP client. (`2737e25`,
  `d3ade86`, `69e22fb`, `23877ce`)

---

## [0.3.2] — 2026-09-08

**Theme**: Truth/surface fixes — every place the tool *claims* something
about a diff, an assurance verdict, or a metric now matches what it
actually measured.

### Fixed

- **PR diff-impact bot analyzes the true merge-base range** (SG-101/102/103)
  — reusable action computes `base...head` from merge-base instead of
  single-revision `R~1 R` pair; a 50-file PR range was previously
  reported as 2 changed files. (`1797929`)
- **Truncation can no longer keep an ASSURED verdict** (SG-104) — any
  trimmed collection re-runs canonical `decide()` with
  `facts.truncated=True`; `returned_count < enumerated_count` always
  degrades the receipt. (`cb3e259`)
- **Evaluator regression gate** (SG-106) — `sot eval-oracle --gate`
  enforces per language×relation P/R floors from baseline minus
  tolerance plus clean-bucket regression rule; exit 1 on regression;
  CI accuracy job runs it. (`b09548d`)
- **Docs bounded to evidence** (SG-110) — README advisory phrasing
  aligned; accuracy badge states enforced floors (≥85% precision /
  ≥90% recall), not peak metrics; `RELEASE_DECISION` superseded →
  CONDITIONAL_GO / HUMAN_GATED. (`c9c5107`)

### Added

- **Canonical impact-claim pipeline** (SG-105) — one executor, stable
  digests, immutable receipts; CLI and MCP surfaces become projections
  of the one executor. (`a85653b`, `8ad8149`)
- **Collector cap/error accounting** (SG-107) — `collection_stats`,
  truncation sources. (`616dcf2`)
- **Scope universe + exhaustion semantics** (SG-108) — absence claims
  require enumerated scope; adversarial suite: false-assured rate 0.
  (`dc7e5a5`, `c39a88c`)
- **Generation-scoped evidence invalidation** (SG-109) — conflict join,
  N/N-1/N-2 generation replay. (`aacaade`, `10138cd`)
- **Trust-claim registry + docs claim linter** (SG-110) — CI workflow
  for claim provenance. (`aeada04`, `40784b5`)
- **Canonical cross-provider identity joins** (SG-203) — measured P/R
  1.00 on real corpus. (`6e408ab`, `92a192a`)
- **Real-repo holdout benchmark** (SG-204) — stdlib-ast oracle, 5
  suites, nightly gate, 11 real repos all gates pass. (`0a2066c`,
  `78a4415`)
- **Honest pack completeness** (SG-202) — PARTIAL on truncation,
  explicit ambiguity resolution, per-category accounting. (`1254bdc`)
- **Production-source repo-map filters** (SG-201) — category
  classification, cross-root isolation, deterministic ranking.
  (`d60f8c4`)
- **Human receipt explorer** (SG-205) — read-only terminal view + diff,
  version gating, no-recompute guarantee. (`dc3d1b3`)
- **OSS governance baseline** (SG-302) — CONTRIBUTING, SECURITY,
  CODEOWNERS, dependabot, PR template. (`6082f1b`)
- **Supply-chain hardening** (SG-303) — pin all Actions to commit SHAs,
  pin uv version, least-privilege permissions. (`262ec79`)
- **Honest 3-state conformance verdict** — replaces ZERO_VIOLATIONS
  claim; schema-driven template. (`8b45686`)
- **Identifier-component FTS tokenization** — bounded exact-bare-name
  signal; holdout Hit@1 0.7879→0.8818, synthetic overall 93.8%→100%.
  (`c745b47`)
- **Type-checking declaration universe** — lambda/comprehension call
  ownership; impact recall 0.9609→0.9798. (`de021da`)
- **Structured accounting-cap registry** — replaces line-bound
  tripwire; holdout publishes denominators/unmeasurable. (`3015e28`)
- **Independent four-axis trust evidence** — search exposes four
  independent trust axes. (`50bf330`)
- **Frozen untouched corpus + split governance** — holdout integrity.
  (`9d81297`)

### Verification

- Full suite: **1047 passed / 2 skipped** (35 new tests); quality gates
  green: core 86% / receipts 91% coverage.

---

## [0.3.1] — 2026-09-05

**Theme**: First publicly installable release (`pip install sotgraph`);
post-audit remediation (G7–G10) + R1–R5 gap-closure roadmap.

### Added

- **CI-native blast radius** — `sot diff-impact --format github`
  renders a PR-safe report; reusable composite action
  `.github/actions/diff-impact` posts/updates an idempotent PR comment.
  (`1a758c2`)
- **MCP prompts** — `sot_deep_dive` (embeds token-budgeted
  ContextBundle) and `sot_refactor_checklist` (embeds PRE-change scope
  receipt) join the 22 read tools and 3 resources. (`1a758c2`)
- **Provider cross-check** — `sot providers cross-check` compares
  builtin AST edges against external provider evidence (agreements /
  builtin-only / external-only) with normalized relations. (`1a758c2`)
- **Real release path** — PyPI trusted publishing wired into CI;
  releases require the accuracy-oracle job; `module_eval
  --strict-probes` fails closed on probe crashes; test matrix extended
  to Python 3.13/3.14. (`4b6d0bb`)

### Performance

- Watcher debounce batches run global pending-edge resolver and orphan
  janitor **once per batch** instead of once per file. (`5ed8ffc`)
- `explore_node` BFS level-batched (chunked `IN` queries per hop);
  rehome healing caches basename walk; `_fits_response` single-pass
  incremental. (`5ed8ffc`)
- Ledger history retention: `sot providers sync` prunes to newest 10
  runs per provider and 20 unreferenced snapshots per repo. (`5ed8ffc`)
- 10,000-file scale run: reconcile p50 6.4s (~1,560 files/s), verified
  search p50 97.5ms. (`85fd9dd`)

### Fixed

- **Evidence hardening** — search-quality benchmark (48 probes × 4
  query classes, Hit@1/5/10 + MRR, CI-gated); diff-impact oracle (6
  scenarios, ground truth by construction, macro P/R/F1, CI-gated);
  +14 Rust/Java negative `implements`/`extends` ground-truth cases —
  zero misresolutions. (`85fd9dd`)
- **Trust truth-telling (audit P2 debt)** — post-change receipts no
  longer silently cap cited files at 200: `changed_files_total` /
  `changed_files_truncated` (receipt schema 1.2) plus explicit
  partial-closure warning; oversized diffs degrade to PARTIAL;
  `verify_drift` MCP calls cancellable between files; SCIP decoding
  stays loud on truncation; vector embedding incremental. (`9d313e2`)
- Windows Job Object process-tree kill (G9); append-only ledger with
  `synchronous=FULL` commits (G8); strict module-eval CI gate (G7).
  (`60b3e91`, `b523e01`, `3536de4`)
- Windows matrix test failures: file locking, encoding, path
  separators, line ending normalization, false-positive journal
  staleness. (`b609d66`, `7dd9e54`)

### Verification

- Full suite: **1014 collected** (1012 pass / 2–3 skips); module-eval
  6 scopes × ruff/pyright/pytest + 12 probes all green.

---

## [0.3.0] — 2026-09-01

**Theme**: Verified Code Evidence & Impact-Assurance Layer — transition
from passive structural indexer to active verified evidence layer.
Schema v8 (backward compatible).

### Added — P0–P9 architectural deliverables

- **P0: Exact 6-tuple accuracy oracle** — `(repo, path,
  source_identity, relation, target_identity, span)` evaluated against
  frozen 234-file multi-language corpus; **99.8% precision, 99.2%
  recall, 99.5% F1** across 1,012 positive + 110 adversarial negative
  edges. (`a1667b9`)
- **P1: Snapshot binding & dirty worktree verification** — binds every
  query to `(head_sha, dirty_fingerprint, manifest_digest,
  graph_generation)`; uncommitted edits immediately invalidate stale
  evidence → `STALE`/`UNVERIFIABLE`. (`cf5e782`)
- **P2: Shared assurance orchestrator** — unified engine serving CLI
  and MCP with identical routing; declarative provider policies
  (`builtin`, `auto`, `prefer:<name>`, `require:<name>`, `all`);
  fail-closed error isolation. (`4c72a51`)
- **P3: Provider adapters & plugin architecture** — Codebase Memory
  CLI structured JSON protocol; SCIP import provider; tree-sitter AST
  enhancements (Go receiver methods, TS/Java interface impls, Rust
  trait impls); versioned plugin contract. (`b908845`, `828262c`,
  `29bf700`, `ee80c15`)
- **P4: Canonical identity & high-precision search** — standardized
  `(repo, normalized_path, language, kind, qualified_name, span)`;
  multilingual scope resolvers; dual-tier FTS5 BM25 + filesystem
  verification. (`28892c8`)
- **P5: Multilingual coverage engine** — `indexed`, `parsed`,
  `partial`, `skipped`, `excluded`, `stale` path states; AST-anchored
  verifiers for Python, TS/JS, Go, Rust, Java; gap taxonomy for
  dynamic dispatch, reflection, DI, framework routing. (`45d32b3`)
- **P6: Evidence ledger & conflict adjudication** — append-only
  SQLite ledger recording provider runs, execution digests, normalized
  candidates, verification statuses; multi-provider evidence union;
  deterministic conflict adjudication. (`af54321`)
- **P7: Impact engine & assurance receipts** — pre-change
  `scope-receipt` (bounded caller/callee sets, candidate tests,
  remaining gaps); post-change `diff-impact` (modified AST nodes,
  invalidated upstream call chains, recommended tests); risk-tiered
  gating (`verify` local / `audit` public API). (`7ae8255`)
- **P8: OMP closed-loop delivery workflow** — 8-step delivery loop:
  Scope Receipt → Todo Plan → Source/LSP Confirmation → Surgical Edit
  → Targeted Tests → Diff-Impact Receipt → Reconcile → Reviewer
  Closure. (`c36cc55`)
- **P9: Hardening, scale & release qualification** — zero-daemon
  in-process architecture, sub-millisecond query latency, sub-30ms
  batch reconciliation; 100-cycle continuous mutation/reconcile
  integrity; Schema v8 compatibility with zero data loss. (`ab5a44d`)

### Added — earlier v0.3.0 milestones

- **Phase 0 hardening** — multi-OS CI workflow, bug fixes. (`4ff1460`)
- **Phase 1: Schema v5 + Multi-Provider Evidence** — SCIP importer,
  North-Star envelope, 200+ edge benchmark. (`c24e1a8`)
- **Phase 2: Analytics SQL aggregation** — hypothesis property tests,
  fault-injection suite, cooperative cancellation. (`49663b5`)
- **Git commit history + diff impact** — `sot log`, `sot diff-impact`.
  (`748dfd1`)
- **Tree-sitter extractors** — C/C++ (with fallback + verification),
  Scala/Elixir/Lua (Tier 1), Zig/Julia/R/Clojure (Group 2),
  Vue/Svelte SFC + SQL DDL + GraphQL (Group 3). (`0ef6167`,
  `b53c455`, `2eb25e5`)
- **Codebase Memory federated CLI provider** — structured JSON
  protocol integration. (`bdb2370`)
- **Evidence layer foundation (P0+P1)** — trust evidence groundwork.
  (`ba99fbe`)
- **Python lexical scope shadowing fix** — independent evaluator
  harness. (`1d5dcaf`)
- **Accuracy fixes** — eliminate false positives, stale JIT evidence,
  SCIP attribution leaks. (`ad62c97`)
- **Cross-platform CI** — tomllib import, python grammar sample,
  windows-capable fake executable harness, posix path normalization,
  windows-safe sqlite handles, byte-exact writes, posix asserts,
  utf-8 console output, windows PID probing via Win32 API, watcher
  log_file handle cleanup. (`bfa7fa5`, `992b16c`, `84ca989`,
  `2e60f3d`, `56be1a8`, `ff0d4c6`, `5328f93`, `8eee373`, `8540ff0`,
  `7d03014`)

---

## [0.2.1] — 2026-08

**Theme**: JIT micro-reconcile + post-mutation hooks + multi-harness
rules.

### Added

- JIT micro-reconcile — staleness-gated auto-reconcile before queries.
  (`5f87ef9`)
- Post-mutation hooks — reconcile triggers after agent edits.
  (`5f87ef9`)
- Multi-harness rules v0.2.1 — synchronized adapter rules across all
  supported harnesses. (`5f87ef9`)

---

## [0.2.0] — 2026-08

**Theme**: Roadmap sprints 1–4 — multi-harness adapters, watch daemon,
expanded CLI, solution trace.

### Added

- **Multi-harness adapters** — support for 5 AI coding harnesses
  (OpenCode, OMP, ZCode, Antigravity, Claude) with `sotgraph setup`
  CLI and auto-provisioned `AGENTS.md`. (`1bd27e8`, `8c1e57d`,
  `b6ad6fa`, `9ed82f2`, `340258c`, `d081c76`)
- **Watch daemon** — multi-project auto-discovery, background daemon,
  OS service integration. (`870f27f`)
- **Expanded CLI** — 20 commands, solution trace, sync adapters.
  (`f844847`)
- **Zero-dependency ignore engine** — path normalization for
  reconcile. (`d71543c`)
- **Dart/Flutter AST extractor** — third-party attribution.
  (`be02683`)
- **2-stage fact bundle & report** — architecture analytics.
  (`9572abf`)
- **v2 core upgrade** — binding-aware resolution, CAS publication,
  ContextBundle, watch daemon. (`e52b90f`)
- **Graph analytics + visualizer** — multi-format export, MCP tools.
  (`77bcd3c`)
- **MCP stdio server** — parallel reconciler, `db clean`/`vacuum`,
  benchmarks. (`0998d77`)
- **Navigation** — `usages`, `implementations`, report-only rename
  plan. (`95923e2`)
- **PageRank repo map** — pack trusted tier, MCP notes. (`a29245f`)
- **MCP 2025-06-18** — structured output, resource links,
  subscriptions, pagination. (`f4fff1e`)
- **Hybrid retrieval** — optional sqlite-vec + RRF fusion. (`628c103`)
- **Tree-sitter extractors** — Go/Rust/Java/Kotlin/Swift via optional
  extra. (`f1727ab`)
- **SCIP export** — git hooks provisioning, deterministic context
  benchmark. (`a1da45a`)
- **PHP state-machine extractor** — interfaces, traits, enums, call
  graph. (`13dd093`)
- **Java extends/implements edges** — both parse paths. (`7075141`)
- **Search improvements** — content previews on file nodes,
  `reconcile --force`, symbol-first ranking, 4KB preview default.
  (`b4fedb4`, `bdf9b16`)

### Fixed

- Self-method calls, explore defines leak, depth overflow. (`bb6a55e`)
- Relative import absolutization, super()/chained self-loop call edge
  pruning. (`6cc8c69`)
- Inbound edge re-queue on `delete_path`, orphan sweep after
  reconcile. (`c989d1b`)
- Symbol presence required before re-homing moved node. (`cd20b13`)
- Rename plan shows definition site; community labels repo-relative.
  (`2c87ad3`)
- Legacy schema reset warning + auto-reconcile. (`1ddb53f`)
- Real-world indexing, AST extraction, FTS5 search edge cases.
  (`2c3a059`)

---

## [0.1.0] — 2026-08 (initial)

**Theme**: Verified knowledge engine — initial commit.

### Added

- SQLite-backed knowledge graph with FTS5 search.
- Tree-sitter AST extraction for Python, TypeScript/JavaScript.
- `sot reconcile`, `sot search`, `sot explore`, `sot doctor`.
- Trust verdicts ([STRONG], [WEAK], [REBUILT]).
- Basic MCP server (stdio).
- README with purpose, architecture, and operational guide.
  (`ed13ea3`, `d6c256c`)
