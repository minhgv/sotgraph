# sotgraph Capability Matrix & Trust Ceilings

This document defines the verified technical capabilities, language support tiers, provider integration boundaries, trust ceilings, and known architectural gaps for **sotgraph v0.3.8**.

---

## 1. Architectural Model & Verification Philosophy

sotgraph operates as a **Verified Code Evidence and Impact-Assurance Layer**. It differentiates itself from traditional code indexers by enforcing strict verification invariants before elevating candidate edges to verified assertions:

1. **Physical Filesystem as Single Source of Truth (SSOT)**: Filesystem state, content hashes, and line spans supersede all cached or external provider metadata.
2. **Deterministic Evidence Verification**: Candidate symbols, calls, and relations are verified against current worktree source code, snapshot fingerprints, and lexical declaration spans.
3. **Fail-Closed Assurance**: If coverage is incomplete, parse gaps exist, or ambiguity remains unresolved, sotgraph abstains or issues `PARTIAL`/`HEURISTIC` verdicts rather than generating unverified positive or negative claims.
4. **Honest Scope Ceilings**: sotgraph guarantees bounded impact assurance within the verified AST/compiler scope; it does not claim unbounded runtime completeness over dynamic reflection or metaprogramming.

---

## 2. Language Support Tiers

| Tier | Languages | AST Extractor | Source Verifier | Scope-Aware Resolver | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier A** | Python | Tree-sitter + AST module | AST + Token Analyzer | Full Module, Class, Nested & Import resolution | Primary Reference (Production) |
| **Tier A** | TypeScript / JS | Tree-sitter | Tree-sitter AST | ESModule / CommonJS imports, Class, Method & Interface | Production |
| **Tier A** | Go | Tree-sitter | Tree-sitter AST | Package, Struct, Receiver Method & Interface | Production |
| **Tier A** | Rust | Tree-sitter | Tree-sitter AST | Module, Trait, Impl block, Function & Associated Item | Production |
| **Tier A** | Java | Tree-sitter | Tree-sitter AST | Package, Class, Static Import, Interface & Override | Production |
| **Tier B** | C / C++ | Tree-sitter / Regex | Lexical Header Span | File & Namespace scope (Static analysis) | Beta |
| **Tier B** | Dart / PHP | Tree-sitter | Lexical Pattern | Class, Method & Function declarations | Beta |
| **Tier C** | Markdown / Docs | Regex / Block Parser | Text Anchor | Section headers, Markdown anchors & cross-refs | Experimental |

---

## 3. Core Capability Matrix by Language & Provider

### Capabilities Key
- **`SYMBOL_SEARCH`**: Qualified symbol discovery, lexical kind extraction, and FTS5 BM25 retrieval.
- **`DEFINITION` / `REFERENCE`**: Declaration site locating and reference site usage auditing.
- **`DIRECT_CALL`**: Static caller-to-callee edge extraction (`calls` relation).
- **`HIERARCHY`**: Inheritance (`extends`) and interface satisfaction (`implements`).
- **`DIFF_IMPACT`**: Git diff blast radius, upstream caller traversal, and affected test detection.
- **`PATH_COVERAGE`**: Line/file level index and parse coverage measurement.
- **`SNAPSHOT_BINDING`**: Atomic binding to HEAD SHA + dirty worktree content fingerprint.

### Capability Breakdown Table

| Language | Provider | `SYMBOL_SEARCH` | `DIRECT_CALL` | `HIERARCHY` | `DIFF_IMPACT` | `PATH_COVERAGE` | Trust Ceiling |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Python** | SOT Builtin AST | Verified | Verified (100% F1, bounded synthetic corpus) | Verified | Verified | Full Line-Level | `VERIFIED_PRESENCE` |
| | SCIP Import | Verified | References only; no call inference | Relationship evidence | Verified | Snapshot Bounded | `VERIFIED_PRESENCE` |
| | Codebase Memory CLI | Candidate | Candidate (bare name) | Candidate | Candidate | Path Scoped | `HEURISTIC` (unless verified) |
| **TypeScript** | SOT Builtin AST | Verified | Verified (100% F1, bounded synthetic corpus) | Verified | Verified | Full Line-Level | `VERIFIED_PRESENCE` |
| | SCIP Import | Verified | References only; no call inference | Relationship evidence | Verified | Snapshot Bounded | `VERIFIED_PRESENCE` |
| | Codebase Memory CLI | Candidate | Candidate (bare name) | Candidate | Candidate | Path Scoped | `HEURISTIC` (unless verified) |
| **Go** | SOT Builtin AST | Verified | Verified (100% F1, bounded synthetic corpus) | Verified | Verified | Full Line-Level | `VERIFIED_PRESENCE` |
| | SCIP Import | Verified | References only; no call inference | Relationship evidence | Verified | Snapshot Bounded | `VERIFIED_PRESENCE` |
| | Codebase Memory CLI | Candidate | Candidate (bare name) | Candidate | Candidate | Path Scoped | `HEURISTIC` (unless verified) |
| **Rust** | SOT Builtin AST | Verified | Verified (100% F1, bounded synthetic corpus) | Verified | Verified | Full Line-Level | `VERIFIED_PRESENCE` |
| | SCIP Import | Verified | References only; no call inference | Relationship evidence | Verified | Snapshot Bounded | `VERIFIED_PRESENCE` |
| | Codebase Memory CLI | Candidate | Candidate (bare name) | Candidate | Candidate | Path Scoped | `HEURISTIC` (unless verified) |
| **Java** | SOT Builtin AST | Verified | Verified (100% F1, bounded synthetic corpus) | Verified | Verified | Full Line-Level | `VERIFIED_PRESENCE` |
| | SCIP Import | Verified | References only; no call inference | Relationship evidence | Verified | Snapshot Bounded | `VERIFIED_PRESENCE` |
| | Codebase Memory CLI | Candidate | Candidate (bare name) | Candidate | Candidate | Path Scoped | `HEURISTIC` (unless verified) |
| **C / C++** | SOT Builtin AST | Verified | Partial (Static) | Partial | Verified | File Level | `HEURISTIC` |
| **Dart / PHP** | SOT Builtin AST | Verified | Partial (Static) | Partial | Verified | File Level | `HEURISTIC` |

> **Note on Trust Ceilings (advisory)**: `VERIFIED_PRESENCE` means anchors are physically span-verified on disk for the measured scope — it is not an exhaustiveness or correctness guarantee. On the synthetic exact corpus (236-file `oracle-corpus-v1`, §4) the engine measures aggregate F1 = 100% (TP 1013 / FN 0 / FP 0). Ceilings are advisory; any absence claim ("no callers", "no references") still requires scope exhaustion per the fail-closed coverage rules.

---

## 4. Exact Oracle Evaluation Baseline (v2.0.0)

Evaluated against the frozen 236-file multi-language test corpus (`oracle-corpus-v1`, digest: `23c0e29c...`) using exact 6-tuple matching `(repo, path, source_identity, relation, target_identity, span)`:

| Language | Static+ Edges | Static- Edges | True Positives | False Positives | False Negatives | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Go** | 159 | 11 | 159 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **Java** | 131 | 18 | 131 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **Python** | 378 | 45 | 378 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **Rust** | 132 | 17 | 132 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **TypeScript** | 213 | 33 | 213 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **Total / Overall** | **1,013** | **124** | **1,013** | **0** | **0** | **100.0%** | **100.0%** | **100.0%** |

- **True Negatives**: 124 / 124 forbidden/adversarial edges rejected in this corpus.
- **Dynamic diagnostics**: 26 fixtures; 5 exact observed claims, 0 wrong-target claims, 21 abstentions. Dynamic results are excluded from static P/R/F1.
- **Search Top-K (48-probe corpus, advisory)**: Hit@1: 100%, Hit@5: 100%, Hit@10: 100% (`benchmarks/search-quality.json`). The separate 20-query polyglot oracle has Hit@1 65%, Hit@5/10 100%.
- **Release gates**: any static false positive or dynamic wrong-target claim fails regardless of metric tolerance. TS nested-scope truth records direct closure calls. Scores describe these synthetic fixtures only.

---

## 5. Trust Verdicts & Assurance Tiers

### 5.1 Evidence Verdict Hierarchy

```text
SUPPORTED      ──> Source span + fresh snapshot + unique qualified identity verified on disk.
HEURISTIC      ──> Candidate discovered via AST/pattern matcher; lacking full static proof.
AMBIGUOUS      ──> Multiple candidate definitions or unresolvable receiver polymorphism.
CONFLICT       ──> Providers or source rules present conflicting targets without resolution.
STALE          ──> Evidence generated from an outdated commit or unindexed worktree edit.
UNVERIFIABLE   ──> Target or file is outside active indexed boundary or unparseable.
```

### 5.2 Receipt Assurance Tiers

1. **`scout` Tier (Exploratory / Read-Only)**:
   - Optimized for sub-millisecond candidate discovery and broad navigation.
   - Prohibits negative claims (cannot assert absence of callers).
   - Returns candidate symbols and direct relationships.

2. **`verify` Tier (Local Refactoring / Moderate Risk)**:
   - Requires snapshot binding + dirty worktree validation + source span checks on all cited paths.
   - Enforces coverage verification across modified files.
   - Permitted for internal method rewrites and private module modifications.

3. **`audit` Tier (Public APIs / Core Refactors / Removals)**:
   - Requires multi-provider federation union, exhausted pagination, zero unhandled conflicts, and complete bounded scope coverage.
   - Generates pre-change `ScopeReceipt` and post-change `DiffImpactReceipt`.
   - Mandatory for public symbol renames, method deletions, and security/tenant boundaries.

---

## 6. Known Architectural Gaps & Boundary Handling

sotgraph enforces honest, fail-closed handling when encountering language features that transcend static closed-world AST analysis:

### 6.1 Dynamic Dispatch & Polymorphism
- **Gap**: Virtual method invocation on runtime-injected interfaces or abstract base types without concrete type derivation.
- **Handling**: Emits `AMBIGUOUS` or multiple candidate targets. Does not issue single-target `SUPPORTED` without type proof.

### 6.2 Reflection & Metaprogramming
- **Gap**: Dynamic method invocation via `getattr()` in Python, `eval()`/reflection in JavaScript/Java, or macro-generated symbols in Rust/C.
- **Handling**: Classified under `dynamic_positive` in oracle evaluation. Downstream assurance marks the dynamic boundary and requires explicit runtime/LSP confirmation.

### 6.3 Dependency Injection (DI) & Magic String Routing
- **Gap**: Call connections wired at runtime via Spring, NestJS, FastAPI dependency injection containers, or string-based router declarations.
- **Handling**: Static edges are linked to the declaration/registration site; runtime resolution gaps are explicitly flagged in `ScopeReceipt.known_gaps`.

### 6.4 Cross-Repository Boundaries
- **Gap**: Calls traversing network APIs, microservices, gRPC channels, or external package binaries outside the local workspace.
- **Handling**: Bounded to the local workspace boundary. External calls are recorded as terminal external references with `UNRESOLVED_EXTERNAL` status.

---

## 7. Negative Claim Protocol ("Zero Callers" Rule)

To prevent accidental breakage of public interfaces, asserting **"0 callers"** or **"no affected dependents"** is strictly forbidden unless all of the following conditions are simultaneously met:

1. **Target Identity Unique**: Symbol is unambiguous and uniquely resolved across the workspace.
2. **Fresh Snapshot**: HEAD commit and working tree dirty content fingerprint are synchronized with zero uncommitted drift.
3. **Complete Scope Coverage**: 100% of candidate files within the bounded package/module are indexed and parsed without parser errors.
4. **Exhausted Pagination**: All result buffers from the underlying engine are fully consumed.
5. **No Truncation**: Output hard caps were not triggered during evidence collection.
6. **No Intersecting Dynamic Gaps**: The target symbol does not lie within a reflection or dynamic dispatch boundary.

If any single condition is unfulfilled, sotgraph outputs:
> *"No callers found within reported scope and active provider capabilities; completeness is unproven beyond verified AST boundaries."*
