# Release Notes — v0.3.6 (2026-09)

The three-gate assurance loop is complete: plan-scope → pre-commit gate →
post-commit outcome verdict is now a **queryable lineage chain**.

## `receipt chain` — lineage dossier (W5)

New `sotgraph receipt chain <ref>` (anchor: receipt digest/prefix, file
path, or commit sha) assembles one dossier:

```
- scope  `88c6f7c6` ✓
- diff   `494ab294` target=HEAD
- commit `08c19c90` (via head_child)
- verdict ❓ unknown (clean)
links: scope→diff ✓ | diff→commit ✓ | commit→outcome ✓
```

- `diff_impact` receipts carry `lineage{scope_receipt_digest, head_sha,
  minted_at}`; `head_sha` is the forward anchor — the commit landing the
  diff is expected to be its direct child (matched_via disclosed:
  `head_child` | `target` | `file_subset`).
- Missing links are named with remediation — `complete` is true only
  when all three links resolve. Fail-closed, never fabricated.
- `scope-receipt` now persists content-addressed into `.sot/receipts/`
  (previously print-only — without it the scope→diff link could never
  resolve).
- Fixed: `--pre-receipt <digest>` now populates `pre_receipt_digest` —
  `_resolve_receipt_input` re-attaches `digest` to store-loaded payloads
  (the store strips the key; the filename is the address).

## Commit-outcome monitoring (W0, W3)

- `sotgraph log --outcomes` classifies each commit `clear-fault` /
  `still-hot` / `unknown` (fail-closed before the observation window
  closes) and prints per-risk-level calibration
  (`P(still-hot | level)` measured on the visible slice).
- MCP tool `sot_commit_verdict` mirrors it.
- CI recipe: `docs/CI_RECIPE.md` — `log --since <tag> --outcomes`,
  fail-on-still-hot snippet, dossier query, full three-gate flow.

## Pre-commit gate (W1, W2)

- `scope-receipt` accepts multiple targets; union blast radius merges
  into one task-level scope.
- `diff-impact` receipts carry `safe_commit{verdict: pass|warn|block}`:
  dangling references block, stale evidence blocks, introduced debt
  markers and untouched predicted callers/tests warn. `--gate-strict`
  exits non-zero on `block`; `--test-report` feeds caller-supplied test
  outcomes into the verdict.

## Accuracy foundations (W4)

- Receiver disambiguation: `self.get()` / nested-scope `get()` no longer
  bind to same-named module-level decoys (wrong-edge corpus 5/5 → 0/5).
- `TestImpact.impact_reason` distinguishes `calls_modified_node` from
  `imports_modified_module` — import-only test impact no longer claims
  call-graph evidence.

## MCP hardening

- Server starts degraded when `.sot/sot.db` is missing — tools return an
  actionable `database_unavailable` instead of killing the process.
- Per-operation timeout budget (`commit_verdict` gets ~60s instead of a
  universal 2s).

## Determinism fix

- `receipt_digest` volatile set now strips `minted_at` and
  `graph_freshness` — identical content previously hashed differently
  per call, breaking executor↔MCP↔CLI digest parity and repeat-call
  determinism.

Full test suite: 2437 passed, 0 failed.
