---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export, Fact Bundles).
---

# /sot-graph (Single Source of Truth Knowledge Layer for Google Antigravity / Gemini CLI)

Ground Gemini and Antigravity agent actions in physical filesystem reality using the SOT knowledge layer.

## When to Use SOT-Graph
- **Top-down orientation**: Map repository architecture without token waste (`sotgraph map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sotgraph search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sotgraph explore` / `sot_explore`, `sotgraph usages` / `sot_usages`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sotgraph implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sotgraph rename` / `sot_rename`).
- **Token-efficient context packaging**: Extract k-hop subgraphs into YAML ContextBundles (`sotgraph pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sotgraph verify` / `sot_verify`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sotgraph insert` / `sot_insert`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sotgraph bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sotgraph cluster`, `sotgraph report`, `sotgraph viz`, `sotgraph export`).
- **Git diff & revision blast radius**: Trace upstream callers, breaking API impacts, and affected tests across commits or working tree changes (`sotgraph diff-impact` / `sot_diff_impact`).
- **Git commit risk analysis**: Inspect commit history with automated risk scoring and impacted symbol tracking (`sotgraph log` / `sot_git_history`).
- **Database maintenance**: Purge stale records and vacuum freelists (`sotgraph clean`, `sotgraph vacuum`, `sotgraph doctor`).

## Trust Verdicts
| Verdict | Meaning | Action |
| :--- | :--- | :--- |
| `[STRONG]` | File exists on disk, symbol exists in AST, token coverage verified. | **Proceed directly.** Hash-verified anchor — high confidence, not absolute. |
| `[WEAK]` | Semantic or partial match; low lexical coverage. | **Inspect snippet range** before relying on symbol. |
| `[REBUILT]` | File moved or renamed; auto-rehomed by reconciler. | **Use updated path** reported in result. |
| `[REMOVED]` | Node deleted on disk; scheduled for purge. | **Do NOT use.** Symbol no longer exists. |
| `[NOPATH]` | Virtual or inline node without a physical file backing. | **Context-only.** Verify origin. |

## Quick CLI & MCP Tool Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sotgraph search "<query>" [-n 5] [--hybrid]` | `sot_search` |
| **Repository Map** | `sotgraph map [--focus <areas>] [--tokens 1024]` | `sot_map` |
| **Trace Call Graph** | `sotgraph explore "<symbol>" [--depth 2]` | `sot_explore` |
| **Inspect Usages** | `sotgraph usages "<symbol>"` | `sot_usages` |
| **Implementations** | `sotgraph implementations "<interface>"` | `sot_implementations` |
| **Rename Impact** | `sotgraph rename "<symbol>" --to <new_name>` | `sot_rename` |
| **Pack Subgraph** | `sotgraph pack "<symbol>" [--depth 2] [-o <file>]`| `sot_pack` |
| **Synchronize DB** | `sotgraph reconcile [--workers 4]` | `sot_reconcile` |
| **Batch Reconcile** | `sotgraph batch-reconcile <dir> [--workers 4]` | CLI |
| **Audit Drift** | `sotgraph verify [--deep]` | `sot_verify` |
| **Database Doctor** | `sotgraph doctor` | `sot_doctor` |
| **Clean Stale Data**| `sotgraph clean [--purge-missing] [--include-notes]` | `sot_clean` |
| **Vacuum Database** | `sotgraph vacuum [--analyze]` | `sot_vacuum` |
| **Store Note** | `sotgraph insert --title "..." --body "..."` | `sot_insert` |
| **Cluster Graph** | `sotgraph cluster [--scope <path>]` | `sot_cluster` |
| **Architecture Report** | `sotgraph report [-o report.md]` | `sot_report` |
| **Interactive Viz** | `sotgraph viz [-o graph.html]` | `sot_viz` |
| **Export Graph** | `sotgraph export -f <graphrag/obsidian/scip>` | `sot_export` |
| **Fact Bundler** | `sotgraph bundle [-o .sot/bundle/] [--include-tests]` | `sot_bundle` |
| **Full-Stack Trace** | `sotgraph trace "<target>" [--depth 2] [-o <file>]` | `sot_trace` |
| **UI Decision Tree** | `sotgraph ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sotgraph be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sotgraph solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sotgraph solution steps "<method>" [--format table/json]` | `sot_solution_steps` |
| **Solution Bundle** | `sotgraph solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Diff Impact** | `sotgraph diff-impact [target] [--staged] [--depth 2]` | `sot_diff_impact` |
| **Commit History** | `sotgraph log [-n 10] [--author <name>] [--since <date>]` | `sot_git_history` |
| **Embed Index** | `sotgraph embed [--limit 5000]` | CLI |
| **File Watcher** | `sotgraph watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sotgraph setup [--harness <name>]` | CLI |
