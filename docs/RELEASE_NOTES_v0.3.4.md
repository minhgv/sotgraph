# Release Notes — v0.3.4 (2026-09)

Self-healing queries, an architecture viewer, and honest target recovery.
Query surfaces now reconcile a stale index before answering (JIT Freshness
Gate), `sotgraph arch` renders a deterministic tiered architecture diagram,
and both `pack` and `scope-receipt` recover the display-string targets agents
actually paste instead of failing with `TARGET_NOT_FOUND`.

## New: `sotgraph arch` — deterministic tiered architecture HTML

- `sotgraph arch [-o out.html]` renders a deterministic, tiered architecture
  diagram from the verified graph — layers follow dependency direction and
  the same graph always renders the same picture.
- `--flow "<target>"` renders a call-flow view for one target.
- `--level module` switches to a module-level layered system view.
- Viewer interaction, docs, and the staged contract (plan 23a90ed → DoD
  verified in 29d1834) closed across stages 1–4.

## JIT Freshness Gate — auto-reconcile before queries

- `search`, `explore`, `usages`, `implementations`, `map`, `pack`, `trace`
  (CLI + MCP) and `diff-impact` probe `.sot/sot.db` against disk before
  answering — size + mtime per journal row, plus a scan walk for
  never-indexed files — and reconcile first when anything drifted.
- Modes: `auto` (default) | `force` | `off`. CLI `--reconcile auto|force|off`
  (diff-impact: `--auto-reconcile` / `--no-auto-reconcile`); MCP
  `auto_reconcile` parameter on the gated tools.
- Disclosure: gated MCP responses carry a `graph_freshness` envelope; the CLI
  prints a `↻ JIT reconcile: …` notice on stderr when a reconcile ran.
- Never blocks: if reconcile fails (DB lock, parse error), the query still
  answers from the stale graph with `status: failed` disclosed.
- Known blind spot: same-size edits within the same millisecond skip the
  probe hash; explicit `sotgraph reconcile` remains the authoritative heal.
- AGENTS.md section 7 records the full contract.

## Graph correctness — benchmark findings verified and fixed

- Verified the GPT-6-Astra benchmark findings against the codebase and fixed
  the confirmed ones (4a1265e): false receiver edges in the graph, B3 pack
  truncation, and a lost `prepare` edge.

## `pack`: recover agent display-string and `path:line` targets

- `sotgraph pack "func main — backend/cmd/server/main.go:28"`-style targets —
  declaration prefixes (func/type/struct/class/def…), separators (em/en dash,
  pipe, spaced hyphen), `:line` / `#Lnn` suffixes, backticks, `()` — now
  resolve instead of failing with `TARGET_NOT_FOUND`.
- Resolution ladder: exact FQN → FQN suffix → path-scoped bare symbol
  (ambiguity surfaced, never auto-picked) → `path:line` containment
  (innermost node) → fuzzy candidates.
- Relative pasted paths match the absolute-path DB via suffix scoping.
- Honesty disclosures: `PATH_LINE_RESOLVED` / `NORMALIZED_TARGET` resolution
  status; `target_normalized:` / `target_resolved_by_path_line:` warnings in
  the bundle's limits block. The error path prints a usage hint plus fuzzy
  candidates.
- MCP `sot_pack` schema and description updated to accept `path:line`.

## `scope-receipt`: identity recovery + rename-gate disclosure

- Receipt identity resolution falls back to the same recovery grammar when
  exact-match fails, under strict decision semantics: the name step carries
  no SQL LIMIT (a decision, not a truncating collection — the SG-107
  accounting sweep enforces this), file nodes are filtered out, and there is
  no dominant-candidate auto-pick.
- Receipt schema 1.7 → 1.8: the new `identity.recovery` block records
  `query → selected` plus the method used; `receipt_explorer` accepts 1.8.
- CLI text now prints `target recovered: '<query>' → '<fqn>' (via <method>)`
  and `✅ rename gate passed: N caller(s) resolved within covered scope`
  (the `🚫 BLOCKED` line already existed).

## Docs accuracy sweep

- Grammar table 10 → 21 registered tree-sitter grammars, scoped to the
  builtin tier; CBM engine language coverage stated; codebase-memory-mcp
  credited; MCP tool count corrected and the missing `sot_cross_check` row
  added to README (45db7b8, 21cdd1e).

## Tests

- 36 new tests: 27 pack target-recovery
  (tests/test_pack_target_recovery.py), 9 scope-receipt recovery + CLI
  rendering (tests/test_scope_receipt_recovery.py).
- 8 existing files re-pinned to receipt schema 1.8 (5 at commit time; 3
  missed pins — cross-check, sg109 generation, diff-impact oracle — caught by
  the full-suite release run and re-pinned before the cut).
- Verification: full-suite counts are cited in the release commit message.
  Remaining failures (test_impact_pipeline, test_sg107_stress,
  test_sg110_claims, test_p2_orchestrator, test_jit_reconcile,
  test_adapter_docs_consistency) are pre-existing — the impact-pipeline and
  stress sets were verified byte-identical before and after this release's
  source changes via a stash-diff baseline, and test_adapter_docs_consistency
  already fails at 8d28a36, before this release's first commit.
