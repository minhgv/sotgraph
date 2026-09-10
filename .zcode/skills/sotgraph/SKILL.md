---
name: sotgraph
description: "Use for ANY codebase structural query: explore the codebase, understand the architecture, what functions exist, who calls this function, what does X call, trace the call chain, find callers, show dependencies, impact analysis, dead code, unused functions, refactor candidates. Single Source of Truth (SOT) verified knowledge graph for AI coding agents: verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export, Fact Bundles)."
---

# /sotgraph (Single Source of Truth Knowledge Layer for ZCode)

Ground every implementation decision in physical filesystem reality. The graph
(`.sot/sot.db`) is an authoritative projection of the codebase — never a
replacement for verifying against disk.

## When to Use SOT-Graph
- **Top-down orientation**: Map repository architecture without token waste (`sotgraph map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sotgraph search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sotgraph explore` / `sot_explore`, `sotgraph usages` / `sot_usages`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sotgraph implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sotgraph rename`).
- **Token-efficient context packaging**: Extract k-hop subgraphs into YAML ContextBundles (`sotgraph pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sotgraph verify`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sotgraph insert`).
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

## JIT Freshness Gate (Auto-Reconcile Before Queries)
Query surfaces self-heal a stale index instead of serving stale answers.
`search`, `explore`, `usages`, `implementations`, `map`, `pack`, `trace`
(CLI + MCP) and `diff-impact` probe `.sot/sot.db` against disk — size +
mtime per journal row, plus a scan walk for never-indexed files — and
reconcile first when anything drifted.

- **Modes**: `auto` (default — probe, reconcile only when stale) \| `force` (always reconcile) \| `off` (skip the gate).
  CLI: `--reconcile auto|force|off` on the 7 query commands; diff-impact: `--auto-reconcile` / `--no-auto-reconcile` (default on).
  MCP: `auto_reconcile` parameter (boolean or string) on the 8 gated tools.
- **Disclosure**: gated MCP responses carry a `graph_freshness` envelope (probe counts for modified/deleted/unindexed files, reconcile `performed|skipped|failed` status). CLI prints a `↻ JIT reconcile: ...` notice on stderr when a reconcile ran.
- **Never blocks**: if reconcile fails (DB lock, parse error), the query still answers from the stale graph with `status: failed` disclosed — check the envelope before trusting freshness-sensitive verdicts.
- **Known blind spot**: same-size edits within the same millisecond skip the probe hash; the assurance layer still hash-checks cited paths post-query. After bulk changes (branch switches, merges, codegen), an explicit `sotgraph reconcile` remains the authoritative heal.

## Quick CLI & MCP Tool Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sotgraph search "<query>" [-n 5] [--hybrid] [--reconcile auto\|force\|off]` | `sot_search` |
| **Repository Map** | `sotgraph map [--focus <areas>] [--tokens 1024] [--reconcile auto]` | `sot_map` |
| **Trace Call Graph** | `sotgraph explore "<symbol>" [--depth 2] [--reconcile auto]` | `sot_explore` |
| **Inspect Usages** | `sotgraph usages "<symbol>" [--reconcile auto]` | `sot_usages` |
| **Import SCIP Index** | `sotgraph import-scip <path>` | CLI only |
| **Implementations** | `sotgraph implementations "<interface>" [--reconcile auto]` | `sot_implementations` |
| **Rename Impact** | `sotgraph rename "<symbol>" --to <new_name>` | `CLI only` |
| **Pack Subgraph** | `sotgraph pack "<symbol>" [--max-hops 2] [-o <file>] [--reconcile auto]`| `sot_pack` |
| **Synchronize DB** | `sotgraph reconcile [--workers 4]` | `CLI only` |
| **Batch Reconcile** | `sotgraph batch-reconcile <dir> [--workers 4]` | CLI |
| **Audit Drift** | `sotgraph verify [--deep]` | `sot_verify_drift` |
| **Database Doctor** | `sotgraph doctor` | `CLI only` |
| **Clean Stale Data**| `sotgraph clean [--all] [--include-notes]` | `CLI only` |
| **Vacuum Database** | `sotgraph vacuum [--analyze]` | `CLI only` |
| **Store Note** | `sotgraph insert --title "..." --body "..."` | `sot_notes` (query/list) |
| **Cluster Graph** | `sotgraph cluster [--scope <path>]` | `sot_communities` |
| **Architecture Report** | `sotgraph report [-o report.md]` | `sot_architecture_report` |
| **Interactive Viz** | `sotgraph viz [-o graph.html]` | `CLI only` |
| **Export Graph** | `sotgraph export -f <graphrag/obsidian/json/graphml/scip>` | `CLI only` |
| **Fact Bundler** | `sotgraph bundle [-o .sot/bundle/] [--include-tests]` | `sot_bundle` |
| **Full-Stack Trace** | `sotgraph trace "<target>" [--depth 2] [-o <file>] [--reconcile auto]` | `sot_trace` |
| **UI Decision Tree** | `sotgraph ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sotgraph be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sotgraph solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sotgraph solution steps "<method>" [--format table/json]` | `sot_solution_steps` |
| **Solution Bundle** | `sotgraph solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Diff Impact** | `sotgraph diff-impact [target] [--staged] [--depth 2] [--auto-reconcile/--no-auto-reconcile]` | `sot_diff_impact` |
| **Commit History** | `sotgraph log [-n 10] [--author <name>] [--since <date>]` | `sot_git_history` |
| **Embed Index** | `sotgraph embed [--limit 5000]` | CLI |
| **File Watcher** | `sotgraph watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sotgraph setup [--harness <name>]` | CLI |
| **Architecture & Flow Views** | `sotgraph arch [--flow "<target>"] [--level module]` | CLI only |
| **MCP Server** | `sotgraph mcp` | CLI only |
| **Providers Admin** | `sotgraph providers <detect/list/doctor/resolve/lifecycle/cross-check/sync>` | `sot_providers_sync`, `sot_cross_check` |
| **Scope Receipt (P7.1)** | `sotgraph scope-receipt "<symbol>" [--depth 2]` | `sot_scope_receipt` |
| **Diff Receipt (P7.2)** | — | `sot_diff_impact_receipt` |
| **Receipt Explorer** | `sotgraph receipt <show/diff>` | CLI only |
| **Claims Lint** | `sotgraph claims lint [--registry <path>]` | CLI only |
| **Engine Admin** | `sotgraph engine --store <dir> <bootstrap/status/doctor/...>` | CLI only |

## 7 Operational Protocols for Agents

### 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality.
- Never assume a file path exists based on historical context without verification.

### 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sotgraph search "<keyword>"` or use the `sot_search` MCP tool.
2. Check Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk.
   - `[WEAK]`: Semantic match only; inspect the file.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.

### 3. Dependency Impact & Safe Refactoring Protocol
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sotgraph explore "<symbol>"` or `sot_explore` to inspect Outward Calls and Incoming References.
2. Run `sotgraph usages "<symbol>"` or `sot_usages` to locate all calling sites.
3. For interfaces or abstract classes, run `sotgraph implementations "<symbol>"` or `sot_implementations`.
4. For multi-file symbol renames, run `sotgraph rename "<symbol>" --to "<new_name>"` to review staged changes.
5. Before submitting PRs or finalizing diffs, run `sotgraph diff-impact` or `sot_diff_impact` to analyze blast radius, upstream inward callers, API contract impacts, and affected tests.
6. Inspect commit risk history via `sotgraph log` or `sot_git_history`.
### 4. Context Isolation & Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sotgraph pack "<symbol>" --max-hops 2 -o .sot/bundle/context.yaml` to extract a token-efficient k-hop subgraph.
2. Feed the compact YAML ContextBundle instead of full raw files to save 60-70% tokens.

### 5. Self-Healing & Drift Reconciliation
- Query commands auto-reconcile a stale index by default (JIT Freshness Gate, see above), but after bulk changes (many files, branch switches, merges) run `sotgraph reconcile` explicitly (or `sotgraph batch-reconcile` for monorepos) — it remains the authoritative heal.
- Run `sotgraph verify --deep` or `sot_verify_drift` to audit phantom anchors and dead paths.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sotgraph insert --title "..." --body "..." --keywords "..."`.

### 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sotgraph bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with facts grounded ONLY in the bundle files — anything beyond them must be marked [INFERENCE]. Valid diagrams, prioritized recommendations.

### 7. Markdown, LaTeX & Unicode Rendering Rules (Dual-Target: Human & AI)
1. **Mermaid Diagrams:**
   - Wrap every Node label and Subgraph title in double quotes: `NODE["Label"]`, `subgraph ID ["Title"]`.
   - Never use bare pipe `|` inside node labels (use `/` or `\|`).
   - Maintain blank lines before and after ````mermaid` blocks.
2. **Mathematical & Unicode Symbols:**
   - Use clean Unicode symbols directly: `Q ≥ 0.650`, `Q = 0.371`, `≈ 400`, `State ∈ { Initial, Loading, Success(data), Failure(error) }`.
   - NEVER use raw `$ ... $` math blocks inside Markdown table cells, headers, or bullet items to prevent raw syntax display on GitHub, VS Code, Obsidian, and Word/DOCX converters.
3. **Markdown Tables & Formatting:**
   - In table cells, escape comparison operators: use `&lt;`, `&gt;` or Unicode `≤`, `≥`.
   - Escape table cell pipes `\|` to preserve table column alignments.
