# Three-Gate Baseline — risk classification vs real outcomes

Repos: 1/1 | Commits labeled: 284 | Adverse = reverted, fixup

## sotgraph — 284 commits (107 fully observed, window 14d)

| Risk | n | ✅ clean | 🔧 fixup | ⛔ reverted | 🔁 retouched | P(adverse) |
|---|---|---|---|---|---|---|
| 🔴 HIGH | 45 | 1 | 38 | 0 | 6 | 84% |
| 🟡 MEDIUM | 41 | 13 | 17 | 0 | 11 | 41% |
| 🟢 LOW | 21 | 15 | 1 | 0 | 5 | 5% |

Monotonic adverse (LOW ≤ MED ≤ HIGH): **yes**

<details><summary>Adverse-outcome commits</summary>

- 🔧 `4f0133a` [MEDIUM] feat(freshness): JIT staleness-gated auto-reconcile before queries — follow-up fix b5cd002 shares file(s): src/sot_graph/cli.py, src/sot_graph/mcp_server.py
- 🔧 `2737e25` [HIGH] fix: cross-platform CI — py3.10 digest, bandit nosec, windows portability — follow-up fix d3ade86 shares file(s): scripts/diagnose_native_latency.py, tests/test_engine_bootstrap.py, tests/test_engine_mcp.py
- 🔧 `0e4413a` [HIGH] feat!: P1 engine runtime namespace, MCP default transport, sotgraph migrations — follow-up fix 626cfe9 shares file(s): src/sot_graph/providers/bootstrap.py, src/sot_graph/providers/engine_mcp.py, tests/test_gs_surface_catalog.py
- 🔧 `ac26089` [HIGH] feat!: trusted engine bootstrap, internal MCP client, dist rename sot-graph->sotgraph — follow-up fix 626cfe9 shares file(s): src/sot_graph/providers/bootstrap.py, src/sot_graph/providers/engine_mcp.py
- 🔧 `1979890` [HIGH] feat!: establish independent repository development with sotgraph CLI — follow-up fix 2737e25 shares file(s): scripts/check_repository_identity.py, src/sot_graph/pack.py, tests/test_completion_surface_packaging.py
- 🔧 `d052ad9` [HIGH] Migrate native history to private pinned submodule and document isolated setup — follow-up fix 2737e25 shares file(s): tests/test_completion_surface_provider.py, tests/test_native_source_verifier.py
- 🔧 `ffa43b1` [HIGH] fix(surface): isolate lifecycle evidence and freeze v2 run — follow-up fix d9bb138 shares file(s): scripts/check_surface_lifecycle.py, tests/test_surface_lifecycle_runner.py
- 🔧 `efbdae9` [HIGH] test(surface): freeze reproducible isolated administrator lifecycle — follow-up fix ffa43b1 shares file(s): scripts/check_surface_lifecycle.py, tests/test_surface_lifecycle_runner.py
- 🔧 `8de4f21` [MEDIUM] test(surface): cover provider isolation and poisoned harness resources — follow-up fix 2737e25 shares file(s): tests/test_completion_surface_harness.py, tests/test_completion_surface_provider.py
- 🔧 `5b171bc` [HIGH] feat(recovery): expose safe managed operational diagnostics — follow-up fix 2737e25 shares file(s): tests/test_engine_trusted_config.py, tests/test_managed_config_recovery.py, tests/test_trusted_managed_config.py
- 🔧 `02ac075` [HIGH] feat(dispatch): share trusted managed read policy — follow-up fix 2737e25 shares file(s): src/sot_graph/assurance/orchestrator.py, tests/test_managed_read_dispatch.py
- 🔧 `af69288` [HIGH] feat(config): persist trusted managed opt-in outside repositories — follow-up fix 2737e25 shares file(s): tests/test_engine_trusted_config.py, tests/test_trusted_managed_config.py
- 🔧 `a61a62d` [HIGH] feat(provider): bind managed execution without circular freshness — follow-up fix 8131295 shares file(s): src/sot_graph/providers/codebase_memory.py, tests/test_cbm_managed_provider.py
- 🔧 `d96cb4b` [HIGH] feat(runtime): gate managed preparation sync and read execution — follow-up fix cd62f30 shares file(s): src/sot_graph/providers/managed.py, tests/test_managed_execution.py
- 🔧 `5ca43aa` [HIGH] feat(runtime): isolate owned profiles and preserve quarantine state — follow-up fix cd62f30 shares file(s): src/sot_graph/providers/runtime.py, tests/test_managed_runtime.py
- 🔧 `5c859c4` [HIGH] fix(pack): prioritize contracts and relevant tests within token budgets — follow-up fix 4a1265e shares file(s): src/sot_graph/pack.py, tests/test_pack_sg202_priority.py
- 🔧 `de021da` [HIGH] feat(extractor): type-checking declaration universe + lambda/comprehension call ownership — impact recall 0.9609→0.9798 (advisor P1-1, P1-2) — follow-up fix 4a1265e shares file(s): src/sot_graph/_vendor/graphify/extract.py, src/sot_graph/extractor.py
- 🔧 `d60f8c4` [MEDIUM] feat(map): SG-201 production-source repo-map filters — category classification, cross-root isolation, deterministic ranking, echoed filter scope — follow-up fix b5cd002 shares file(s): src/sot_graph/cli.py, src/sot_graph/mcp_server.py
- 🔧 `1254bdc` [MEDIUM] feat(pack): SG-202 honest pack completeness — PARTIAL on truncation, explicit ambiguity resolution, per-category accounting — follow-up fix 5c859c4 shares file(s): src/sot_graph/pack.py, tests/test_sg202_pack_completeness.py
- 🔧 `6e408ab` [HIGH] feat(providers): SG-203 canonical cross-provider identity joins — Closes #6 — follow-up fix 55c479d shares file(s): src/sot_graph/providers/identity_join.py, tests/test_identity_join.py, tests/test_providers_cross_check.py
- 🔧 `40784b5` [HIGH] test(claims): SG-110 registry/lint suite — traces, drift, absolutes — follow-up fix 66f4295 shares file(s): tests/test_sg110_claims.py
- 🔧 `cb3e259` [MEDIUM] fix(mcp): degrade assurance after transport truncation; unify diff default to HEAD — follow-up fix b6a7991 shares file(s): src/sot_graph/mcp_server.py, tests/test_mcp_receipt_tools.py
- 🔧 `9d313e2` [HIGH] fix(debt): close audit-P2 debt — honest receipts, cancellable drift, cached rehome, batched BFS, incremental embed (R5) — follow-up fix 2cc3f50 shares file(s): src/sot_graph/cli.py, tests/test_verifier.py
- 🔧 `1a758c2` [HIGH] feat(surfaces): CI-native diff-impact bot, MCP prompts, provider cross-check (R4) — follow-up fix 9d313e2 shares file(s): src/sot_graph/cli.py, src/sot_graph/mcp_service.py
- 🔧 `18beb88` [HIGH] perf(polish): land G10 — batched staleness, offline d3, vault collisions, query fixes, refreshed benchmarks — follow-up fix 1797929 shares file(s): pyproject.toml, src/sot_graph/diff_impact.py, tests/test_diff_impact.py

</details>

## Labeler vs hand labels

| Class | labeled | precision | recall | pass≥0.9 |
|---|---|---|---|---|
| reverted | 0 | n/a | n/a | ✅ |
| fixup | 7 | 88% | 100% | ❌ |

