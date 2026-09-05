# SG-201 exit-gate measurement — top-map contamination (PILOT)

Scope: PILOT — self-repo corpus (sot-graph); does NOT close the global exit gate

## Provenance
- git HEAD: `8b45686a0ccfc1d02a3645d920366b20ad0f41bb` worktree digest: `e590733defd8540e` (dirty entries: 37, digest truncated: False)
- snapshot binding: scores apply to exactly this HEAD+worktree (content-exact digest)

## Policy (declared)
- selection: ACTUAL rendered map text within declared token budget (default budgets 1024,2048)
- default_categories: production only (the shipped default)
- category_oracle: declared superset oracle (common.ORACLE_*_RULES); over-flagging only, divergences published
- gate: symbol-level fixture+vendor contamination < 2% of rendered symbols, min rendered symbols 50
- landmark_precision@20: NOT measured here — requires human reviewer (plan/sg201-landmark-study-protocol.md)

## Primary run (default filter, largest declared budget)
- rendered symbols / files: 91 / 42
- fixture+vendor symbols: 0 (0.00%)
- fixture+vendor files: 0 (0.00%)
- head-20-files slice contaminated symbols: 0 / 50
- src/ production share: 96.7%
- category breakdown (symbols): {'production': 91}

## Runs

| budget | control(all) | rendered syms | contam syms | contam % |
|---|---|---|---|---|
| 1024 | no | 44 | 0 | 0.0% |
| 1024 | yes | 33 | 6 | 18.182% |
| 2048 | no | 91 | 0 | 0.0% |
| 2048 | yes | 76 | 11 | 14.474% |

## Production-vs-oracle divergences (rendered files)
- none

## Gate
- verdict: **PASS** (metric 0.0% = fraction 0.0 vs floor <2%, denominator 91 / min 50; budgets with sufficient sampling: [2048])

> Landmark precision@20 >= 90% requires HUMAN reviewers — status PENDING_HUMAN_EVIDENCE. Any automated proxy is reported separately and never substitutes the gate.
