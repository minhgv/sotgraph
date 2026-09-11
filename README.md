# sotgraph (Single Source of Truth Knowledge Graph)

> **Verified, self-healing knowledge layer for AI coding agents and engineering teams.**
> *Filesystem is the Single Source of Truth — The knowledge graph is a verified, bounded evidence index: every returned anchor is span-verified on disk; verdicts are advisory and scope-bounded. Zero external daemons required.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![SQLite: WAL + FTS5](https://img.shields.io/badge/SQLite-FTS5%20%2B%20WAL-orange.svg)](src/sot_graph/db.py)
[![Schema: v8 Multi-Provider](https://img.shields.io/badge/Schema-v8%20Multi--Provider-purple.svg)](src/sot_graph/db.py)
[![Tests: 2294 collected](https://img.shields.io/badge/Tests-2294%20collected-brightgreen.svg)](tests/)
[![Quality Gates: Passing](https://img.shields.io/badge/Quality%20Gates-Passing%20(%3E%3D85%25%20Core%20%7C%20%3E%3D90%25%20Receipts)-success.svg)](scripts/quality_gates.sh)
[![Architecture: Zero-Daemon](https://img.shields.io/badge/Architecture-Zero--Daemon-purple.svg)](#database-architecture--durability)
[![Builtin Tier: 21 Grammars](https://img.shields.io/badge/Builtin%20Tier-21%20Grammars-success.svg)](src/sot_graph/ts_extract.py)

---

See [development readiness and migration audit](docs/DEVELOPMENT_READINESS.md).

> **Renamed: `sot-graph` → `sotgraph`.** The CLI is `sotgraph`, the PyPI
> distribution is `sotgraph`, and the Python import package remains `sot_graph`.
> Per-repo `.sot/` databases, stored notes, and `~/.sotgraph/engine-store` are
> unaffected by the rename. The legacy PyPI project `sot-graph` (≤ 0.3.2) is the
> same tool before the rename — migrate with
> `pip uninstall sot-graph && pipx install sotgraph`. The rename details are in
> [RELEASE_NOTES_v0.3.3.md](docs/RELEASE_NOTES_v0.3.3.md); the latest changes are in
> [RELEASE_NOTES_v0.3.6.md](docs/RELEASE_NOTES_v0.3.6.md).

## Installation & Quick Start (one shot)

One package, one command. The CBM extractor engine is fetched, digest-verified,
and activated by sotgraph itself — **you never install codebase-memory
separately** (details in [CBM Extractor](#cbm-extractor--codebase-memory-engine-auto-bootstrapped)).

```bash
# Isolated CLI (recommended)
pipx install sotgraph          # or: uv tool install sotgraph

# Plain pip
pip install sotgraph

# Straight from git (no PyPI needed)
pipx install git+https://github.com/minhgv/sotgraph.git
```

Provision every AI-agent harness integration and bootstrap the CBM engine with
the same command:

```bash
sotgraph setup --harness all   # adapters + skills + MCP config + engine bootstrap
sotgraph --version
sotgraph engine --store ~/.sotgraph/engine-store status   # verify pinned engine artifact
```

On first run, `sotgraph setup` performs the **trusted engine bootstrap**: it
downloads the platform-pinned `codebase-memory` binary declared in
`engine_pins.json`, verifies sha256 + size, stages it into
`~/.sotgraph/engine-store`, and promotes it. This is the only sanctioned
retrieval path — no PATH discovery, no unpinned URLs, never
download-on-query. Opt out with `SOT_ENGINE_BOOTSTRAP=off` and bootstrap later
with `sotgraph engine --store ~/.sotgraph/engine-store bootstrap`.

Then index your first repository and confirm health:

```bash
cd ~/code/my-project
sotgraph reconcile        # incremental index into .sot/sot.db
sotgraph doctor           # schema v8 + FTS sync + orphan audit
sotgraph search "Database" -n 5
```

## Development checkout

```bash
git clone https://github.com/minhgv/sotgraph.git
cd sotgraph
uv sync --locked --all-extras --group dev
.venv/bin/sotgraph --help
# Optional native source (requires access to both private repositories):
git submodule update --init --recursive
.venv/bin/python scripts/verify_native_source.py
```

Python-only CLI development does not require the native checkout, compiler, or
an installed CBM binary. For a complete checkout, use `git clone --recurse-submodules`
with the same URL. After pulling a changed native pin, run
`git submodule update --init --recursive` again. The native source checkout is
approximately 1.33 GB; building it requires the toolchain documented in
`engines/codebase-memory-mcp/README.md`. No installer is run by Python setup.
The CLI remains `sotgraph`, the distribution `sotgraph`, and imports `sot_graph`.

The native submodule is the private standalone controlled mirror
[ minhgv/sotgraph-cbm ](https://github.com/minhgv/sotgraph-cbm), **not a GitHub fork**.
It preserves authentic history from `DeusData/codebase-memory-mcp`, including
commit `46ae198fc11cda80e817acbc5f5908d7c2de7032` and its unchanged source tree
`01132faf9bb4acfbd260fcbc6f29638d005be0ee`, licenses, executable modes, and symlinks.
The existing source manifest continues to bind that authentic upstream pin;
no synthetic snapshot identity or artifact trust substitution is involved.
GitHub Actions are disabled in both private repositories. Before enabling any
native workflow, configure `NATIVE_SOURCE_READ_TOKEN` with read-only contents
access to both private repositories; the default parent token cannot read the
private submodule. Native build checks are experimental, not release certification.

## What is sotgraph?

`sotgraph` is an ultra-fast, zero-daemon knowledge graph and symbol intelligence engine designed specifically for **Autonomous AI Coding Agents** (Oh My Pi / OMP, Claude Code, Cursor, OpenCode, Google Antigravity / Gemini CLI, ZCode IDE).

It replaces slow, blind, and hallucination-prone text grepping with an incremental, AST-verified structural graph stored in SQLite (WAL mode + FTS5 full-text indexing + Schema v8 Multi-Provider Provenance Ledger).

### Core Value Pillars

1. **Verified Anchors (advisory)**: The filesystem is the single source of truth. Search reports anchor verification through four per-hit axes (`hit.axes`) — `anchor_freshness` (indexed anchor vs disk), `identity` (whole-index bare-symbol uniqueness, not true compiler resolution), `query_relevance` (lexical heuristic: `exact` | `semantic` = raw-query token coverage | `weak` | `unknown`; not calibrated, not correctness), `scope_completeness` (always `unknown` per hit; result-set coverage is asserted separately as `result_set.scope_completeness`, e.g. `bounded` — never repo-wide). Legacy verdict labels (`[STRONG]`, `[WEAK]`, `[REBUILT]`) are backward-compatibility only; some anchors are unmeasurable (`unknown`/nopath), semantic fit and exhaustiveness are NOT guaranteed — read the snippet and treat absence claims as scope-bounded.
2. **Multi-Provider Provenance Ledger (Schema v8)**: Transparently records fast AST Heuristics (`AST_HEURISTIC_PARSER`), compiler-backed SCIP indices (`COMPILER_INDEXED_SYMBOLS`), and external provider telemetry (Codebase Memory) in dedicated `provider_runs` and `provider_evidence` tables.
3. **Bounded Impact Trust Chain & Canonical Root Isolation**: Strictly evaluates scope coverage through a fail-closed 6-state decision machine (`ASSURED_WITHIN_SCOPE`, `PARTIAL`, `CONFLICTED`, `STALE`, `UNVERIFIABLE`, `ABSTAINED`). Enforces canonical `os.path.realpath` bounding across DB persistence and ledger queries, preventing cross-repository evidence leakage and symlink retarget exploits in multi-tenant environments.
4. **Token-Bounded Context Packaging (`sotgraph pack`)**: Extracts exact target spans (L0) + 1-hop caller/callee contracts (L1) + 2-hop signature stubs (L2) within strict hard token budgets (`--tokens` / `--max-tokens`), preventing prompt bloat.
5. **Architectural Blast Radius (`sotgraph usages` / `sotgraph explore` / `sotgraph diff-impact`)**: Inbound and outbound dependency traversal identifying transitive callers, breaking API contracts, and unresolved bare-name shadowing risk before refactoring or landing pull requests.
6. **Atomic Two-Phase Mutation Gateway**: All database mutations (`reconcile`, `batch-reconcile`, `insert`, `clean`, `import-scip`, `providers sync`) acquire exclusive write locks (`BEGIN IMMEDIATE` + `.sot/write.lock`) with note preservation across schema migrations.

---

## Polyglot AST Engine — Builtin Tier (Tree-sitter Grammars)

Language coverage comes in two tiers and the numbers belong to their tier:

- **Builtin tier (always installed, zero-dependency core)** — the 21 tree-sitter grammars below plus the Python stdlib AST tier. This tier works even when the CBM engine is absent or opted out.
- **CBM engine tier (auto-bootstrapped `codebase-memory` extractor)** — the pinned artifact `engine-v2026.09.07` vendors its own tree-sitter grammars covering **158 languages** per the pinned artifact's own documentation (the engine's claim, ingested as provider evidence — sotgraph does not re-measure it; the upstream live README has drifted to 162 without reconciling against the pin), and adds Hybrid LSP semantic type resolution for a core language set (Python, TypeScript/JavaScript family, Go, C/C++, Java, Kotlin, Rust, PHP, C#, Perl).

Builtin tier registry (`src/sot_graph/ts_extract.py`) — 21 tree-sitter grammars (TypeScript and TSX counted separately; GraphQL needs its own package install) across 19 language families, plus the Python stdlib AST tier:

| Language | Extractor Engine | Key AST Constructs |
| :--- | :--- | :--- |
| **Python** | `ast` + `symtable` (stdlib) | Classes, Functions, Methods, Decorators, Lexical Scope & Shadowing |
| **TypeScript / TSX** | `tree-sitter-typescript>=0.23` | Interfaces, TypeAliases, Classes, Methods, Enums, Exported Consts |
| **JavaScript / JSX** | `tree-sitter-javascript>=0.23` | Classes, Functions, Arrow Functions, Lexical Declarations (`const`/`let`/`var`) |
| **Go** | `tree-sitter-go>=0.23` | Structs, Interfaces, Functions, Methods, Type Definitions |
| **Rust** | `tree-sitter-rust>=0.23` | Structs, Enums, Traits, Impl Blocks, Functions, Modules |
| **Java** | `tree-sitter-java>=0.23` | Classes, Interfaces, Enums, Records, Methods, Fields |
| **C#** | `tree-sitter-c-sharp>=0.23` | Classes, Structs, Interfaces, Enums, Records, Namespaces |
| **PHP** | `tree-sitter-php>=0.23` | Classes, Interfaces, Traits, Enums, Methods, Functions |
| **Kotlin** | `tree-sitter-kotlin>=0.7` | Classes, Interfaces, Objects, Companion Objects, Extension Functions |
| **Swift** | `tree-sitter-swift>=0.7` | Protocols, Structs, Classes, Extensions, Actor Declarations |
| **C** | `tree-sitter-c>=0.23` | Functions, Structs, Unions, Enums, Preprocessor Defines |
| **C++** | `tree-sitter-cpp>=0.23` | Classes, Namespaces, Templates, Functions, Using Declarations |
| **Dart** | `tree-sitter-dart>=0.1.0` | Classes, Extensions, Mixins, Enums, Functions |
| **Scala** | `tree-sitter-scala>=0.26.0` | Classes, Traits, Objects, Case Classes, Def Declarations |
| **Elixir** | `tree-sitter-elixir>=0.3.0` | Modules, Def Macros, Protocols, Function Heads |
| **Lua** | `tree-sitter-lua>=0.5.0` | Functions, Local Functions, Table Fields, Methods |
| **Zig** | `tree-sitter-zig>=1.1.0` | Functions, Structs, Enums, Const Declarations, Tests |
| **Julia** | `tree-sitter-julia>=0.23.0` | Structs, Functions, Modules, Abstract Types, Macros |
| **SQL** | `tree-sitter-sql>=0.3.0` | Tables, Views, CREATE Statements, Functions, Indexes |
| **GraphQL** | `tree-sitter-graphql` (not in the default extra) | Type Definitions, Interfaces, Unions, Enums, Schemas |

*(Ruby is supported via a high-fidelity token state machine; every language also falls back to the builtin tokenizer tier when its grammar package is not installed).*

---

## CBM Extractor — codebase-memory Engine (Auto-Bootstrapped)

sotgraph ships two complementary extraction tiers, and installing sotgraph
provisions both:

1. **Builtin tree-sitter AST extractor** — always available, zero
   dependencies; the fast per-language heuristic tier behind `reconcile`
   (`AST_HEURISTIC_PARSER` in the Schema v8 provenance ledger).
2. **CBM engine (`codebase-memory`, protocol `artifacts-v1`)** — an external
   extractor and evidence provider consulted for symbols, callgraph, usages,
   impact, and broad-language discovery (158 vendored tree-sitter grammars
   per the pinned artifact's documentation, plus Hybrid LSP type resolution
   for a core language set — see
   [Polyglot AST Engine](#polyglot-ast-engine--builtin-tier-tree-sitter-grammars)).
   Its telemetry is joined into the
   `provider_runs` / `provider_evidence` tables and surfaced by
   `sot cross-check`; sotgraph talks to it through an internal MCP stdio
   client with a per-account runtime namespace
   (`$TMPDIR/sotgraph-engine-<uid>`, mode 0700).

**One-shot install, no separate CBM setup.** The engine binary is never pip-
or npm-installed. It is pinned per platform in
`src/sot_graph/providers/engine_pins.json` (currently `engine-v2026.09.07`,
engine commit `e477a32`, for darwin-arm64 / linux-arm64 / linux-x86_64),
fetched only at `sotgraph setup` or explicit command time, verified against
the pinned sha256 + size before staging, and promoted via the artifact store
under `~/.sotgraph/engine-store` (digest-addressed, rollback-safe).

Engine lifecycle commands (all require the trusted store):

```bash
sotgraph engine --store ~/.sotgraph/engine-store bootstrap   # fetch pinned artifact
sotgraph engine --store ~/.sotgraph/engine-store status      # verify, no spawn
sotgraph engine --store ~/.sotgraph/engine-store doctor      # identity + limits
sotgraph engine --store ~/.sotgraph/engine-store mcp-probe   # stdio handshake probe
sotgraph engine --store ~/.sotgraph/engine-store rollback    # switch verified digest
```

Additional lifecycle subcommands (all store-gated, `sotgraph engine --help`
for full flags): `import`, `promote`, `uninstall`, `disable`, `config-status`,
`config-doctor`, `register`, `prepare`, `probe`, `sync`, `search`,
`runtime-status`.

Environment knobs: `SOT_ENGINE_BOOTSTRAP=off` disables auto-bootstrap;
`SOT_ENGINE_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN` authenticate the pinned
release download when the mirror requires it.

> Platform note: pinned artifacts exist for darwin-arm64, linux-arm64, and
> linux-x86_64 today. On any other host, `bootstrap` fails closed with the
> list of available platforms — the builtin tree-sitter extractor keeps
> working everywhere.

---

## 1-Command AI Agent Harness Provisioning (`sotgraph setup`)

`sotgraph` automatically provisions MCP tools, extensions, and SSOT agent rules across all major AI coding harnesses:

```bash
# Provision all supported harnesses at once (Global + Workspace)
sotgraph setup --harness all

# Or provision specific harnesses
sotgraph setup --harness pi          # Pi Harness / Oh My Pi (OMP)
sotgraph setup --harness zcode       # ZCode IDE (MCP + Skill + Slash Commands)
sotgraph setup --harness opencode    # OpenCode
sotgraph setup --harness claude      # Claude Code & Cursor
sotgraph setup --harness antigravity # Google Antigravity / Gemini CLI

# Scope configuration to current workspace only
sotgraph setup --harness all --workspace-only
```

### Supported Harnesses & Deployed Integrations

| Harness | Configuration Files & Artifacts | Integration Highlights |
| :--- | :--- | :--- |
| **Pi Harness / Oh My Pi (OMP)** | `~/.omp/agent/extensions/sotgraph.ts`<br>`.omp/extensions/sotgraph.ts`<br>`.omp/skills/sotgraph/SKILL.md`<br>`.omp/RULES.md`<br>`.omp/rules/sotgraph.md` | Full `xd://sot_*` tool devices, SSOT system prompt rules, and background subagent knowledge reuse |
| **Claude Code & Cursor** | `~/.claude/CLAUDE.md`<br>`.claude/CLAUDE.md` | SSOT Knowledge Reuse Protocol, Blast Radius Pre-Check, and Token-Bounded Context packaging |
| **Google Antigravity** | `~/.gemini/GEMINI.md`<br>`.gemini/GEMINI.md`<br>`.gemini/skills/sotgraph/SKILL.md` | Single-Source-of-Truth directives, pure-read search, and architectural fact bundles |
| **OpenCode** | `~/.config/opencode/opencode.json`<br>`~/.config/opencode/skill/sotgraph/SKILL.md`<br>`~/.config/opencode/plugins/sotgraph/index.ts`<br>`.opencode/opencode.json`<br>`.opencode/skills/sotgraph/SKILL.md` | OpenCode skill integration, local MCP server configuration, and file permissions |
| **ZCode IDE** | `~/.zcode/config.json`<br>`~/.zcode/skills/sotgraph/SKILL.md`<br>`~/.zcode/commands/sot-*.md`<br>`.zcode/config.json`<br>`.zcode/skills/sotgraph/SKILL.md`<br>`.zcode/commands/sot-*.md` | MCP server registration, slash command suite (`/sot-search`, `/sot-map`, `/sot-explore`, `/sot-usages`, `/sot-rename`), and IDE skill |

Legacy artifacts from pre-rename setups (`sot-graph.ts` extensions,
`skills/sot-graph/`, `rules/sot-graph.md`, MCP server keys named `sot-graph`)
are migrated or removed automatically by `sotgraph setup` — foreign files with
the same names are never touched.

### Native OMP/OpenCode Adapter Safety

The native TypeScript adapters resolve the installed `sotgraph` command to an
absolute canonical executable from the trusted process `PATH` before invoking
it. They treat environment-variable names case-insensitively (including
Windows-shaped `Path` and `PythonPath` keys), remove every `PATH`/`PythonPath`
variant, filter both the original and canonical forms of each `PATH` entry and
its `sotgraph` target whenever either form is under the canonical workspace root,
and publish only canonical representations of retained external entries. On
Windows, executable candidates follow the configured `PATHEXT` suffix order.
They never inject the workspace `src` directory through `PYTHONPATH`.
Session-start reconciliation remains best-effort when `sotgraph` is unavailable, and
OMP schedules a debounced reconcile after successful `write`, `edit`, `ast_edit`,
or `patch` tool results.

The OMP `sot_diff_impact` adapter rejects revision targets beginning with `-`
before invoking the CLI, preventing option-like targets from being
reinterpreted as command flags.

For the OMP `sot_pack` tool, `depth` is translated to the CLI's `--max-hops`
option and `tokens` is forwarded as `--max-tokens`. The destructive OMP
`sot_clean` reset requires an explicit `confirm: true` argument when `all: true`
(unless `dry_run: true`); only an explicit confirmation adds the CLI `--yes`
flag.
---

## CLI & Agent Tool Usage Reference

### 1. Codebase Indexing & Synchronization
```bash
# Incrementally reconcile modified files into SQLite graph
sotgraph reconcile

# Parallel multi-worker reconciliation for large codebases (100k+ LOC)
sotgraph reconcile --workers 4

# Batch reconcile multiple distinct repositories under a parent directory
sotgraph batch-reconcile /path/to/parent_projects --workers 4

# Import exact compiler-backed SCIP index (e.g. from scip-typescript or scip-python)
sotgraph import-scip index.scip

# Watch filesystem and reconcile automatically on file changes
sotgraph watch --debounce-ms 200

# Audit graph health and Schema v8 table counts
sotgraph doctor

# Emit machine-readable audit receipt
sotgraph doctor --receipt

# CI-safe drift check: compare database projection against the filesystem
sotgraph verify --deep

# Safe reset of disposable graph records (user notes preserved by default)
sotgraph clean --all --yes

# Compact the SQLite database file and re-run ANALYZE
sotgraph vacuum --analyze
```

### 2. Pure-Read Code Search & Trust Verdicts
```bash
# Ranked symbol search — per-hit trust axes (anchor_freshness, identity, query_relevance, scope_completeness); legacy [STRONG]/[WEAK]/[REBUILT] labels are compat-only
sotgraph search "Database.commit_file_batch"

# Search scoped to specific path or module
sotgraph search "Reconciler" --scope "src/sot_graph" -n 10

# Build/refresh the optional vector index, then combine FTS + vector recall
sotgraph embed
sotgraph search "retry backoff policy" --hybrid
```

### 3. Dependency Impact & Blast Radius
```bash
# Bounded graph traversal (inward callers and outward dependencies)
sotgraph explore "Database" --depth 2

# Find indexed references grouped by caller with bare-name renaming risk
sotgraph usages "commit_file_batch"

# Find implementations and interface extensions in both directions
sotgraph implementations "BaseStore"

# Non-destructive dry-run rename impact analysis
sotgraph rename "explore_node" --to "walk_node"
```

### 4. Context Bundling for Agent Prompts (`sotgraph pack`)
```bash
# Package exact target span (L0) + 1-hop contracts (L1) + 2-hop signature stubs (L2)
sotgraph pack "Database.commit_file_batch" -o .sot/bundle.yaml

# Hard token budget cap (using --tokens or --max-tokens)
sotgraph pack "Database.commit_file_batch" --tokens 1500 --json

# Token-budgeted repository map ranked by personalized PageRank
sotgraph map --tokens 1024 --focus "Database.commit_file_batch"
```

### 5. Multi-Provider Assurance & Bounded Scope Receipts
```bash
# Detect installed provider executables and SCIP artifacts
sotgraph providers detect

# List registered providers, health status, and supported capabilities
sotgraph providers list

# Diagnose provider health with recommended remediation actions
sotgraph providers doctor

# Synchronize index for a specific provider
sotgraph providers sync codebase-memory

# Resolve the effective provider for a capability with policy precedence
sotgraph providers resolve symbols --json

# Show provider lifecycle state (registration, health, last run)
sotgraph providers lifecycle codebase-memory

# Cross-check builtin graph claims against external provider evidence
sotgraph providers cross-check [--provider codebase-memory]

# Generate PRE-change bounded impact scope receipt (P7.1)
sotgraph scope-receipt "Pipeline.process" --depth 2 --change-kind local-body --json

# Inspect stored receipts (P7.1/P7.2) and diff before/after snapshots
sotgraph receipt show <receipt-id>
sotgraph receipt diff <before-id> <after-id>

# Lint public trust claims in docs against the claim registry (SG-110)
sotgraph claims lint
```

### 6. Full-Stack Execution Tracing & Solution Workflows
```bash
# Extract full-stack execution trace with Mermaid sequence/flowchart diagrams
sotgraph trace "OrderController.createOrder" --depth 3

# Extract frontend UI decision tree, validation rules, and modal transitions
sotgraph ui-tree "OrderModal.tsx" --json

# Extract backend processing micro-steps, multi-datasources, and exception branches
sotgraph be-flow "OrderProcessingService" --json

# Stage 1: Feature discovery by user role for solution documentation
sotgraph solution inventory "Billing" -o .sot/Feature_Inventory.md

# Stage 2: Micro-step decomposition (4-column table) for labor estimation
sotgraph solution steps "PaymentService.processTransaction" --format table

# Synthesize complete context bundle for downstream documentation agents
sotgraph solution bundle "Billing" -o .sot/bundle/ContextBundle.md
```

### 7. Architecture Fact Bundles & SDLC Documentation
```bash
# Extract 5 high-density fact files into .sot/bundle/ for LLM documentation
sotgraph bundle -o .sot/bundle

# Generate human-readable Markdown architecture report
sotgraph report -o ARCHITECTURE_REPORT.md

# Run Louvain community detection to evaluate modularity (Q) and cohesion
sotgraph cluster

# Persist a durable knowledge/decision note (survives clean --all, queryable via sot_notes)
sotgraph insert --title "ADR: retry policy" --body "..." --keywords "adr,retry"
```

### 8. Interactive Visualizer & Knowledge Graph Export
```bash
# Launch zero-server D3.js interactive force-directed visualizer
sotgraph viz --open

# Export graph for GraphRAG pipelines (JSON)
sotgraph export --format graphrag -o graphrag_dataset.json

# Export Obsidian Markdown Vault with [[wikilinks]]
sotgraph export --format obsidian -o .sot/obsidian_vault

# Export raw JSON graph or GraphML (for Gephi/Cytoscape/yEd)
sotgraph export --format json -o graph.json
sotgraph export --format graphml -o graph.graphml
```

### 9. Architecture & Flow Views
Renders a single self-contained, deterministic HTML file — zero dependencies, fully offline (`file://`).

```bash
# Tiered architecture view of the whole repo (or a --scope subdirectory)
sotgraph arch [-o architecture.html] [--scope <dir>]

# Layered system view: one card per module/package with aggregated edge weights
sotgraph arch --level module [-o system.html]

# Flow view of a module/symbol/feature (default depth 3, node budget 60)
sotgraph arch --flow "<target>" [--depth N] [--max-nodes M] [--lanes module] [-o flow.html]
```

Interactions: press `/` to search, click a node for its evidence passport, toggle dark/light theme. Honesty: an unknown `--flow` target exits 2 with no file written; when the node budget truncates the view, a badge reports shown/total.

### 10. Git Diff Blast Radius & Commit Risk Analysis
```bash
# Analyze blast radius and upstream caller impact for working tree changes
sotgraph diff-impact --working-tree

# Analyze blast radius of staged changes against HEAD~1 with reverse call graph depth 2
sotgraph diff-impact HEAD~1 --depth 2 --staged

# Auto-reconcile knowledge graph and output impact analysis in JSON
sotgraph diff-impact HEAD~1 --auto-reconcile --json

# Inspect recent commit history with automated risk scoring and impacted symbols
sotgraph log -n 10 --author "developer"

# PR-comment-safe rendering for CI bots (collapsed sections, repo-relative paths)
sotgraph diff-impact HEAD~1 --format github
```

> CI-native usage: post/update this report as an idempotent PR comment with the reusable composite action — see [docs/CI_INTEGRATION.md](docs/CI_INTEGRATION.md).

---

## Model Context Protocol (MCP) Server

`sotgraph` exposes 23 structured MCP tools, 2 reusable prompts, and resources over standard I/O for AI coding agents:

```bash
# Start MCP server over stdio
sotgraph mcp
```

### Registered MCP Tools & Exact Schemas

#### Read-Only Inspection & Assurance Tools
| MCP Tool | Description | Required Parameters | Optional Parameters |
| :--- | :--- | :--- | :--- |
| `sot_search` | Read-only verified graph search with resource links (`sot://node/{id}`) | `query` (str) | `limit` (int, default 6), `scope` (str), `threshold` (float 0-1), `assurance` (bool), `provider_policy` ('builtin_only'\|'prefer_external'\|'require_external'), `budget` (int) |
| `sot_explore` | Bounded graph traversal (inbound and outbound) | `node_id` (str) | `depth` (int, default 1), `limit` (int, default 100) |
| `sot_usages` | Find indexed references grouped by caller + bare-name shadowing risk | `target` (str) | `limit` (int, default 100), `scope` (str), `assurance` (bool), `provider_policy` ('builtin_only'\|'prefer_external'\|'require_external'), `budget` (int) |
| `sot_implementations`| Extends and implements type hierarchy relationships | `target` (str) | — |
| `sot_verify_drift` | Non-destructive filesystem vs database drift check | — | `deep` (bool), `limit` (int) |
| `sot_cross_check` | Classify builtin graph claims vs external provider evidence (agreements / builtin-only / external-only / conflicts) joined on canonical symbol identity | — | `provider` (str), `sample_limit` (int, 1-500, default 20) |
| `sot_architecture_report` | Architectural analysis with god nodes and modularity metrics | — | `scope` (str), `min_size` (int), `sigma` (float) |
| `sot_communities` | Louvain / Label Propagation community detection with cohesion scores | — | `scope` (str), `min_size` (int) |
| `sot_pack` | ContextBundle (YAML/JSON) with 1-hop contracts and 2-hop signature stubs | `target` (str) | `max_hops` (int, 1-3), `max_nodes` (int), `max_bytes` (int), `max_tokens` (int) |
| `sot_map` | Token-budgeted repository map ranked by personalized PageRank | — | `focus` (str), `max_tokens` (int, default 1024) |
| `sot_notes` | Persisted architectural knowledge notes query | — | `query` (str), `limit` (int, default 50) |
| `sot_trace` | Execution path trace, UI decision branches, and Mermaid diagrams | `target` (str) | `depth` (int, 1-5, default 2) |
| `sot_ui_tree` | Frontend UI decision tree, validation rules, button triggers, modals | `component` (str) | — |
| `sot_backend_flow` | Backend service micro-steps, multi-datasources, exception branches | `service` (str) | — |
| `sot_solution_steps` | Stage 2 Micro-step decomposition (4-column table) for manpower effort | `method` (str) | — |
| `sot_diff_impact` | Analyze git diff blast radius, inward callers, API contract impacts, and affected tests | — | `target` (str, default 'HEAD~1'), `depth` (int, default 2), `staged` (bool), `working_tree` (bool), `auto_reconcile` (bool), `format` ('markdown'\|'json'\|'github') |
| `sot_git_history` | Inspect git commit history with automated risk scoring and impacted symbol detection | — | `limit` (int, default 10), `author` (str), `since` (str), `with_impact` (bool, default true), `format` ('markdown'\|'json') |
| `sot_scope_receipt` | PRE-change bounded impact scope receipt (P7.1) with snapshot binding and risk assessment | `target` (str) | `kind_of_change` ('local-body'\|'rename'\|'delete'\|'public-api'), `touches_auth` (bool), `dynamic_heavy` (bool), `depth` (int) |
| `sot_diff_impact_receipt` | POST-change diff-impact receipt (P7.2) with post-change snapshot and closure verification | — | `target` (str), `depth` (int, 1-5), `staged` (bool), `working_tree` (bool) |

#### Write-Guarded & Artifact Generator Tools
| MCP Tool | Description | Required Parameters | Optional Parameters |
| :--- | :--- | :--- | :--- |
| `sot_providers_sync` | Explicit provider index sync (write path): records ledger run + evidence with snapshot | — | `provider_name` (str, default 'codebase-memory') |
| `sot_bundle` | Generates 5 high-density architecture fact bundle markdown files | — | `output_dir` (str, default `.sot/bundle`) |
| `sot_solution_inventory` | Stage 1 Feature Discovery by User Role for Solution docs | — | `module` (str), `output_file` (str) |
| `sot_solution_bundle` | Full solution context bundle (UI forms, DataTable schemas, API specs) | — | `module` (str), `output_file` (str) |

---

## Database Architecture & Durability

- **Storage Engine**: SQLite in WAL (Write-Ahead Logging) mode with `NORMAL` synchronous mode and 64MB memory-mapped I/O (`mmap_size = 67108864`).
- **Physical Tables (Schema v8)**:
  - `graph_nodes`: AST symbols, signatures, docstrings, content hashes, roles, and generation timestamps.
  - `graph_edges`: Directed dependency edges (`calls`, `imports`, `extends`, `implements`, `defines`).
  - `provider_runs`: Immutable ledger of extraction runs (`AST_HEURISTIC_PARSER` vs SCIP vs Codebase Memory, versions, argument digests, snapshot hashes, status, canonical project roots).
  - `provider_evidence`: Multi-provider provenance assertions keyed by run, target, capability, confidence score, and JSON payload.
  - `meta`: Key-value store tracking schema version, repository generation, and commit state.
- **Canonical Project Root Isolation**: All run recordings and evidence queries resolve `os.path.realpath(project_root)` before database queries or inserts, guaranteeing strict multi-tenant isolation.
- **Atomic Two-Phase Mutation Gateway**: All database-mutating operations acquire an exclusive file lock (`.sot/write.lock`) and execute inside `BEGIN IMMEDIATE` transactions.
- **Note Preservation**: User notes (`kind == 'note'`) are preserved across schema migrations and `sotgraph clean --all` resets. *(Note: physically deleting the `.sot/sot.db` file from the disk destroys all database data including notes).*

---

## Installation

### From PyPI
```bash
pip install sotgraph            # zero-dependency core
pip install "sotgraph[all]"     # with MCP, analytics, watch, vector, tree-sitter extras
```

### From Source / Git
```bash
git clone https://github.com/minhgv/sotgraph.git
cd sotgraph
pip install -e ".[all,dev]"
```

### Extraction Engine (automatic, trusted)
Running `sotgraph setup` — or the explicit `sotgraph engine bootstrap` — automatically
fetches the pinned native extraction engine into `~/.sotgraph/engine-store`, verifies its
SHA-256 against the pin manifest shipped inside this package, and promotes it through the
managed artifact store. The engine is an **internal component**: sotgraph talks to it over
MCP stdio and it is never exposed as a separate CLI or agent-facing MCP server. Private
release sources honor `SOT_ENGINE_TOKEN`/`GH_TOKEN`. Use `SOT_ENGINE_BOOTSTRAP=off` to
disable automatic fetch, or `sotgraph engine bootstrap --source <file>` for offline
machines. sotgraph remains fully functional without the engine (builtin AST extraction).

### Optional Dependency Extras
- `sotgraph[mcp]`: MCP server and JSON-RPC stdio protocol (`mcp>=1.3,<2`).
- `sotgraph[analytics]`: Graph community detection and modularity analysis (`networkx>=3.0`, `scipy>=1.10`).
- `sotgraph[tokens]`: Fast Rust BPE tokenizer for prompt budgeting (`tiktoken>=0.7`).
- `sotgraph[watch]`: Real-time filesystem watcher daemon (`watchfiles>=0.21`).
- `sotgraph[vector]`: Hybrid FTS5 + vector retrieval (`sotgraph search --hybrid`) (`sqlite-vec>=0.1.6`).
- `sotgraph[scip]`: Compiler-backed SCIP index importer (`protobuf>=4.21`).
- `sotgraph[tree-sitter]`: Polyglot Tree-sitter grammars (Go, Rust, Java, Kotlin, Swift, PHP, TS/JS, C/C++, Dart, Lua, Scala, SQL, Zig, ...).
- `sotgraph[all]`: All optional dependencies and polyglot Tree-sitter parsers.

---

## Verification & Test Suite

The test suite includes **2294 collected tests** covering unit functionality, multi-OS file locking, stateful Hypothesis property testing, fault injection (WAL crash simulation, disk-full ENOSPC simulation, mid-batch connection drops), cross-language AST extractions, and multi-provider trust chain boundary enforcement:

```bash
# Run full test suite with pytest (2294 collected; win32-gated suites skip per-platform)
pytest tests/ -v --strict-markers

# Run end-to-end quality gates script (Ruff + Pyright + Bandit + Pip-Audit + Coverage)
./scripts/quality_gates.sh

# Run trust chain hardening and symlink isolation test suite
pytest tests/test_trust_chain_hardening.py -v

# Run fault-injection and process-crash resilience tests
pytest tests/fault/test_fault_injection.py -v

# Run Hypothesis state-machine property invariant tests
pytest tests/property/test_invariants.py -v
```

---

## Open-Source Acknowledgments & Third-Party Licenses

`sotgraph` acknowledges and credits the following open-source projects:

1. **[Graphify](https://github.com/voidshard/graphify)** (MIT License): AST extraction logic foundation and multi-language tokenizers (`src/sot_graph/_vendor/graphify/`).
2. **[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)** (MIT License): The `codebase-memory` engine — external extractor and evidence provider auto-bootstrapped by sotgraph (protocol `artifacts-v1`; mirrored source at `minhgv/sotgraph-cbm`). We respect its upstream project and authentic history.
3. **[Tree-sitter](https://tree-sitter.github.io/tree-sitter/)** (MIT License): Incremental concrete syntax tree parsing system for polyglot AST extractors.
4. **[D3.js](https://d3js.org/)** (ISC / BSD-3-Clause License): Standalone force-directed graph visualizer (`sotgraph viz`).
5. **[SQLite](https://www.sqlite.org/)** (Public Domain): Embedded relational, FTS5 full-text indexing, and Write-Ahead Logging (WAL) engine.

---

## License

MIT License. Copyright (c) 2026 Minh Giap.
