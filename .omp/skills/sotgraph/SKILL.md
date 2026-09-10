---
name: sotgraph
description: "Use for ANY codebase structural query: explore the codebase, understand the architecture, what functions exist, who calls this function, what does X call, trace the call chain, find callers, show dependencies, impact analysis, dead code, unused functions, refactor candidates. Single Source of Truth (SOT) verified knowledge graph for AI coding agents: verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export, Fact Bundles)."
---

# /sotgraph (Single Source of Truth Knowledge Layer)

When to use:
- **Top-down orientation**: Map repository architecture without token waste (`sotgraph map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sotgraph search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sotgraph explore` / `sot_explore`) and exact call-sites (`sotgraph usages` / `sot_usages`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sotgraph implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sotgraph rename`).
- **Token-efficient context packaging**: Extract k-hop subgraphs into YAML ContextBundles (`sotgraph pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sotgraph verify` / `sot_verify_drift`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sotgraph insert` / `sot_notes`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sotgraph bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sotgraph cluster`, `sotgraph report`, `sotgraph viz`, `sotgraph export`).
- **Git diff & revision blast radius**: Trace upstream callers, breaking API impacts, and affected tests across commits or working tree changes (`sotgraph diff-impact` / `sot_diff_impact`).
- **Git commit risk analysis**: Inspect commit history with automated risk scoring and impacted symbol tracking (`sotgraph log` / `sot_git_history`).
- **Database maintenance**: Purge stale records and vacuum freelists (`sotgraph clean`, `sotgraph vacuum`, `sotgraph doctor`).

## Trust Verdicts
- `[STRONG]`: hash-verified against disk reality (high confidence, not absolute). File exists, symbol exists, token coverage matches.
- `[WEAK]`: Semantic or partial match. Inspect the file snippet before relying on it.
- `[REBUILT]`: File has moved location; use the updated path reported by the reconciler.
- `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
- `[NOPATH]`: Virtual/inline node without a direct physical file backing.

## Quick CLI & Native Tool Device Reference
| Category | CLI Command | Native Tool Device |
| :--- | :--- | :--- |
| **Search Codebase** | `sotgraph search "<query>" [-n 5] [--hybrid]` | `xd://sot_search` |
| **Repository Map** | `sotgraph map [--focus <areas>] [--tokens 1024]` | `xd://sot_map` |
| **Trace Call Graph** | `sotgraph explore "<symbol>" [--depth 2]` | `xd://sot_explore` |
| **Inspect Usages** | `sotgraph usages "<symbol>"` | `xd://sot_usages` |
| **Implementations** | `sotgraph implementations "<interface>"` | `xd://sot_implementations` |
| **Rename Impact** | `sotgraph rename "<symbol>" [--to <new_name>]` | `xd://sot_rename` |
| **Pack Subgraph** | `sotgraph pack "<symbol>" [--max-hops 2] [-o <file>]`| `xd://sot_pack` |
| **Synchronize DB** | `sotgraph reconcile [--workers 4]` | `xd://sot_reconcile` |
| **Batch Reconcile** | `sotgraph batch-reconcile <dir> [--workers 4]` | CLI |
| **Audit Drift** | `sotgraph verify [--deep]` | `xd://sot_verify` |
| **Database Doctor** | `sotgraph doctor` | `xd://sot_doctor` |
| **Clean Stale Data**| `sotgraph clean [--all] [--include-notes]` | `xd://sot_clean` |
| **Vacuum Database** | `sotgraph vacuum [--analyze]` | `xd://sot_vacuum` |
| **Store Note** | `sotgraph insert --title "..." --body "..."` | `xd://sot_insert` |
| **Cluster Graph** | `sotgraph cluster [--scope <path>]` | `xd://sot_cluster` |
| **Architecture Report** | `sotgraph report [-o GRAPH_REPORT.md]` | `xd://sot_report` |
| **Interactive Viz** | `sotgraph viz [-o graph.html]` | `xd://sot_viz` |
| **Export Graph** | `sotgraph export -f <graphrag/obsidian/scip>` | `xd://sot_export` |
| **Fact Bundler** | `sotgraph bundle [-o .sot/bundle/] [--include-tests]` | `xd://sot_bundle` |
| **Full-Stack Trace** | `sotgraph trace "<target>" [--depth 2] [-o <file>]` | `xd://sot_trace` |
| **UI Decision Tree** | `sotgraph ui-tree "<component>"` | `xd://sot_ui_tree` |
| **Backend Flow** | `sotgraph be-flow "<service>"` | `xd://sot_backend_flow` |
| **Feature Inventory** | `sotgraph solution inventory [module] [-o <file>]` | `xd://sot_solution_inventory` |
| **Micro-steps Decompose** | `sotgraph solution steps "<method>" [--format table/json]` | `xd://sot_solution_steps` |
| **Solution Bundle** | `sotgraph solution bundle [module] [-o <file>]` | `xd://sot_solution_bundle` |
| **Diff Impact** | `sotgraph diff-impact [target] [--staged] [--depth 2]` | `xd://sot_diff_impact` |
| **Commit History** | `sotgraph log [-n 10] [--author <name>] [--since <date>]` | `xd://sot_git_history` |
| **Embed Index** | `sotgraph embed [--limit 5000]` | CLI |
| **File Watcher** | `sotgraph watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sotgraph setup [--harness <name>]` | CLI |
