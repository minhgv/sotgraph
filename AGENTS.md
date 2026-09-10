# Agent Rules & Protocols (sotgraph SSOT v0.3.4)

## sotgraph Knowledge Reuse & Multi-Provider Protocol

Before implementing any new feature, fix, or refactoring:
1. Check existing work across projects using the Single Source of Truth search:
   `sotgraph search "<what you are looking for>" --scope <optional-dir> [--json]`
2. Follow Multi-Provider Trust Verdict Guidance:
   - `[STRONG]`: Legacy compat label only — file and symbols physically verified on disk (Schema v8). Trust decisions should read the four per-hit axes (`hit.axes`) reported with each search hit (see below).
   - Per-hit trust axes (`hit.axes`): `anchor_freshness`; `identity` (whole-index bare-symbol uniqueness — NOT true compiler resolution); `query_relevance` (lexical heuristic: exact | semantic = query-token overlap | weak | unknown — not calibrated); `scope_completeness` (always `unknown` per hit; result-set coverage is a separate `result_set.scope_completeness`, e.g. `bounded` — never repo-wide).
   - `[WEAK]`: Semantic match only — inspect the file snippet before relying on it.
   - `[REBUILT]`: File has moved location; use the updated reported path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
3. Check `providers` in response envelope to distinguish AST heuristic extractions from compiler-backed SCIP indices.
4. Trace architectural impact before modifying core symbols:
   `sotgraph explore "<symbol_or_function_name>" --depth 2`
5. Ingest compiler indices for compiler-exact cross-file references when a SCIP index is imported; the builtin AST provider is heuristic:
   `sotgraph import-scip <path_to_index.scip>`
6. Package subgraphs for subagents under strict token ceilings:
   `sotgraph pack "<symbol>" --tokens 1500 --json`
7. After completing reusable work, architecture choices, or tricky fixes, persist it:
   `sotgraph insert --title "<topic>" --body "<details>" --keywords "k1,k2"`
   *(User notes are permanently preserved even when resetting disposable graph indexes).*

# sotgraph Single Source of Truth Protocols & Rules for Agents (SSOT v0.3.4)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the ground truth. The SOT knowledge graph (`.sot/sot.db`) is a verified, scope-bounded projection of it (Schema v8) — re-verify against disk before acting on any verdict.
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse & Multi-Provider Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sotgraph search "<keyword>" [--json]` or use the `sot_search` MCP tool (Pure-Read Search; never mutates SQLite).
2. Check Multi-Provider Trust Verdicts:
   - `[STRONG]`: Legacy compat label only; code physically exists and is verified on disk. Trust decisions should read the four per-hit axes (`hit.axes`) reported with each search hit:
     `anchor_freshness`; `identity` (whole-index bare-symbol uniqueness — NOT true compiler resolution); `query_relevance` (lexical heuristic: exact | semantic = query-token overlap | weak | unknown — not calibrated); `scope_completeness` (always `unknown` per hit; result-set coverage is a separate `result_set.scope_completeness`, e.g. `bounded` — never repo-wide).
   - `[WEAK]`: Semantic match only; inspect the file snippet before relying on it.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.
3. Inspect `providers` metadata to distinguish `AST_HEURISTIC_PARSER` vs. `COMPILER_SCIP_INDEX`.

## 3. Dependency Impact & Safe Refactoring Protocol (Honest Usages)
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sotgraph explore "<symbol>" [--depth 2] [--json]` or `sot_explore` to inspect Outward Calls and Incoming References.
2. Run `sotgraph usages "<symbol>" [--json]` or `sot_usages` to locate indexed calling sites within the reported scope.
3. For interfaces or abstract classes, run `sotgraph implementations "<symbol>"` or `sot_implementations`.
4. For compiler-exact cross-package symbol resolution, run `sotgraph import-scip <path_to_index.scip>`.
5. For multi-file symbol renames, run `sotgraph rename "<symbol>" --to "<new_name>"` to review staged changes.
6. Before submitting PRs or finalizing diffs, run `sotgraph diff-impact [target]` or `sot_diff_impact` to evaluate blast radius, upstream inward callers, API contract impacts, and affected test suites.
7. Inspect git commit history risk scores and impacted symbols via `sotgraph log` or `sot_git_history`.
## 4. Context Isolation & Hard-Budget Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sotgraph pack "<symbol>" --tokens 1500 --json` (or `sot_pack`) to extract a token-efficient k-hop subgraph with hard token ceiling.
2. Feed the compact ContextBundle instead of full raw files to save 60-70% tokens.

## 5. Self-Healing, Note Preservation & Storage Integrity
- Query commands auto-reconcile a stale index by default (JIT Freshness Gate, section 7), but after bulk changes (many files, branch switches, merges) run `sotgraph reconcile` explicitly — it remains the authoritative heal.
- Run `sotgraph doctor` to audit database health, schema v8, and page allocations.
- `sotgraph clean --all` purges disposable graph records while permanently preserving user notes (`kind == 'note'`).
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sotgraph insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sotgraph bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/` (MCP output paths are strictly confined to project root).
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with facts grounded ONLY in the bundle files (mark anything beyond them as [INFERENCE]), valid diagrams, and prioritized recommendations.

## 7. JIT Freshness Gate (Auto-Reconcile Before Queries)
Query surfaces self-heal a stale index instead of serving stale answers:
1. **Gated surfaces**: `search`, `explore`, `usages`, `implementations`, `map`, `pack`, `trace` (CLI + MCP) and `diff-impact` probe `.sot/sot.db` against disk — size + mtime per journal row, plus a scan walk for never-indexed files — and reconcile first when anything drifted.
2. **Modes**: `auto` (default — reconcile only when stale) | `force` (always) | `off` (skip). CLI: `--reconcile auto|force|off` (diff-impact: `--auto-reconcile`/`--no-auto-reconcile`, default on). MCP: `auto_reconcile` parameter on the 8 gated tools.
3. **Disclosure**: gated MCP responses carry a `graph_freshness` envelope (probe counts for modified/deleted/unindexed files, reconcile `performed|skipped|failed` status). CLI prints a `↻ JIT reconcile: ...` notice on stderr when a reconcile ran.
4. **Never blocks**: if reconcile fails (DB lock, parse error), the query still answers from the stale graph with `status: failed` disclosed — check the envelope before trusting freshness-sensitive verdicts.
5. **Known blind spot**: same-size edits within the same millisecond skip the probe hash; the assurance layer still hash-checks cited paths post-query. Explicit `sotgraph reconcile` (section 5) remains the authoritative heal after bulk changes.

## Quick CLI & MCP Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sotgraph search "<query>" [-n 5] [--json] [--reconcile auto\|force\|off]` | `sot_search` |
| **Repository Map** | `sotgraph map [--focus <areas>] [--tokens 1024] [--reconcile auto]` | `sot_map` |
| **Trace Call Graph** | `sotgraph explore "<symbol>" [--depth 2] [--json] [--reconcile auto]` | `sot_explore` |
| **Inspect Usages** | `sotgraph usages "<symbol>" [--json] [--reconcile auto]` | `sot_usages` |
| **Import SCIP Index**| `sotgraph import-scip <path> [--provider-version v1]` | CLI |
| **Implementations** | `sotgraph implementations "<interface>" [--reconcile auto]` | `sot_implementations` |
| **Rename Impact** | `sotgraph rename "<symbol>" --to <new_name>` | `CLI only` |
| **Pack Subgraph** | `sotgraph pack "<symbol>" [--tokens 1500] [--json] [--reconcile auto]` | `sot_pack` |
| **Synchronize DB** | `sotgraph reconcile [--workers 4] [--force]` | `CLI only` |
| **Audit Drift** | `sotgraph verify [--deep]` | `sot_verify_drift` |
| **Database Doctor** | `sotgraph doctor [--json]` | `CLI only` |
| **Clean Stale Data**| `sotgraph clean [--all] [--include-notes]` | `CLI only` |
| **Vacuum Database** | `sotgraph vacuum [--analyze]` | `CLI only` |
| **Store Note** | `sotgraph insert --title "..." --body "..."` | `sot_notes` (query/list) |
| **Cluster Graph** | `sotgraph cluster [--scope <path>]` | `sot_communities` |
| **Architecture Report** | `sotgraph report [-o report.md]` | `sot_architecture_report` |
| **Interactive Viz** | `sotgraph viz [-o graph.html]` | `CLI only` |
| **Export Graph** | `sotgraph export -f <graphrag\|obsidian\|json\|graphml\|scip>` | `CLI only` |
| **Fact Bundler** | `sotgraph bundle [-o .sot/bundle/]` | `sot_bundle` |
| **Full-Stack Trace** | `sotgraph trace "<target>" [--depth 2] [-o <file>] [--reconcile auto]` | `sot_trace` |
| **UI Decision Tree** | `sotgraph ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sotgraph be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sotgraph solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sotgraph solution steps "<method>" [--format table]` | `sot_solution_steps` |
| **Solution Bundle** | `sotgraph solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Diff Impact** | `sotgraph diff-impact [target] [--staged] [--depth 2] [--auto-reconcile/--no-auto-reconcile]` | `sot_diff_impact` |
| **Commit History** | `sotgraph log [-n 10] [--author <name>] [--since <date>]` | `sot_git_history` |
| **Embed Index** | `sotgraph embed [--limit 5000]` | CLI |
| **File Watcher** | `sotgraph watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sotgraph setup [--harness <name>]` | CLI |
| **Batch Reconcile** | `sotgraph batch-reconcile <dir> [--workers 4]` | CLI only |
| **Architecture & Flow Views** | `sotgraph arch [--flow "<target>"] [--level module]` | CLI only |
| **MCP Server** | `sotgraph mcp` | CLI only |
| **Providers Admin** | `sotgraph providers <detect\|list\|doctor\|resolve\|lifecycle\|cross-check\|sync>` | `sot_providers_sync`, `sot_cross_check` |
| **Scope Receipt (P7.1)** | `sotgraph scope-receipt "<symbol>" [--depth 2]` | `sot_scope_receipt` |
| **Diff Receipt (P7.2)** | — | `sot_diff_impact_receipt` |
| **Receipt Explorer** | `sotgraph receipt <show\|diff>` | CLI only |
| **Claims Lint** | `sotgraph claims lint [--registry <path>]` | CLI only |
| **Engine Admin** | `sotgraph engine --store <dir> <bootstrap\|status\|doctor\|...>` | CLI only |

