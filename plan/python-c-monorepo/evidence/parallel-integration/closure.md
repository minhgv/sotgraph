# Parallel batch closure — 2026-09-06

Scope: continued local P4–P7 improvements on `feat/python-c-monorepo-phased`, no commit/push/merge. This receipt supplements rather than rewrites historical phase evidence.

## Independent work and results

- Surface author: `agent_a2a9b2d9-a4c0-40ad-a768-371b9018225f`. Added behavioral catalog/lifecycle tests; fixed unknown-tool and service/internal MCP errors to set `isError=True` while preserving payload shape and internal diagnostic confidentiality. Fixed repeated Claude setup appending duplicate AGENTS instructions. Final scoped suite: 62 passed. Original four-file Ruff passed; expanded Ruff includes two pre-existing F401 imports in `tests/test_mcp_receipt_tools.py`, confirmed against HEAD and left unchanged.
- Verifier author: `agent_b07b2aef-3ad5-473d-812c-5c02472db82c`. Added strict expected-pin/manifest validation, special-file and escaping/looping symlink refusal, and content-bound Git blob SHA-1 checks alongside SHA-256. Final scoped suite: 33 passed; Ruff passed; actual subtree verification passed for 2,050 entries and 1,332,757,092 bytes. This checks consistency with the trusted manifest, not independent publisher authenticity.
- Diagnostic author: `agent_2e4a890e-08b6-4fe3-b60a-7f9613eb6f3c`. Three isolated samples with other test/build workloads paused. Median managed query 8.823 seconds versus same-transport direct native execution 8.665 seconds; three executable hashes total approximately 0.443 seconds. Historical 26.743-second measurement was not reproduced. These are separate diagnostics, not replacement benchmark results or proof of native idle/root cause. No production latency optimization, timeout increase or stat-keyed integrity cache was introduced. Only daemon-log content changed; scratch database content remained stable.
- Independent reviewer: `agent_595208aa-ec4b-45eb-9a18-41bfb623164a`. Final verifier and surface deltas clean after Git blob binding and MCP exception-branch repairs.

## Main integrated validation

`final-exits.json` contains commands, exit codes and durations; logs and JUnit XML are adjacent.

- Final full pytest: **1,944 passed, 4 skipped, 4 warnings**, exit 0; 192.67 seconds external wall time.
- Reconcile, doctor, working-tree diff-impact, and `git diff --check`: exit 0, run sequentially after production freeze.
- Skips: root-only ownership, case-sensitive-filesystem requirement on this host, two Windows-only Job Object tests.
- An earlier integrated suite (before exception-branch expansion) passed 1,940 tests; retained separately, not presented as the final result.

## Gate boundaries

This batch closes additional local correctness/test gaps only. Remote native CI, full platform/harness certification and prior release dependencies remain unproven; no G4/G5/G7 release promotion. Historical G6 performance FAIL remains unchanged. Diagnostic samples do not certify a speedup, preferred-provider rollout or cold-cache/resource completeness. No native source, golden fixtures, historical handoffs or unrelated user plan was modified by this batch.
