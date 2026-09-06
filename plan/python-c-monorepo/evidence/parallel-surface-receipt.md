# Parallel GS-SURFACE receipt

## Final freeze — corrected error assertion, scoped tests green

Coordinator expanded ownership to exactly `tests/test_mcp_receipt_tools.py:132`. Changed obsolete `assertFalse(result.isError)` to `assertTrue`, preserving every payload assertion. This aligns the test with the intended public error contract; the preceding **61 passed / 1 failed** run is retained below.

Final actual validation:
- `.venv/bin/python -m pytest -q tests/test_gs_surface_catalog.py tests/test_gs_surface_lifecycle.py tests/test_mcp.py tests/test_mcp_modern.py tests/test_mcp_prompts.py tests/test_mcp_receipt_tools.py tests/test_adapters.py tests/test_adapter_docs_consistency.py`: **exit 0; 62 passed, 1 existing Hypothesis warning; 3.07s**. Log `/tmp/gs-surface-corrected-pytest.log`.
- `.venv/bin/python -m ruff check src/sot_graph/mcp_server.py src/sot_graph/adapters/claude.py tests/test_gs_surface_catalog.py tests/test_gs_surface_lifecycle.py tests/test_mcp_receipt_tools.py`: **exit 1**, only two existing F401 unused imports (`json`, `os`) in the newly authorized existing test, lines10–11. Log `/tmp/gs-surface-corrected-ruff.log`.
- Verified baseline with `git show HEAD:tests/test_mcp_receipt_tools.py | .venv/bin/python -m ruff check --stdin-filename tests/test_mcp_receipt_tools.py -`: **exit 1, identical two F401 findings**. Log `/tmp/gs-surface-baseline-ruff.log`. Left untouched because ownership permits only the obsolete assertion.
- Ruff on the original four owned production/new-test files: **exit 0; All checks passed**.
- `git diff --check -- src/sot_graph/mcp_server.py src/sot_graph/adapters/claude.py tests/test_mcp_receipt_tools.py`: **exit 0**.

Additional frozen SHA-256: `tests/test_mcp_receipt_tools.py` = `f547176a49a20352adab6046f75609cd2f38228c5fcf0dd34a21963bb0403bf4`. All latest hashes below remain valid. Final delta frozen for main full-suite rerun and independent review. No full suite, native workload, shared DB mutation, commit or push in this validation.

## Historical exception-contract delta — legacy assertion failure

After coordinator reported its frozen full-suite baseline (1940 passed, 4 skipped, exit 0), the exact exception handler now returns `CallToolResult(isError=True)` for both service and internal errors. Existing `_error` sanitization, generic internal message, and `_ensure_schema_shape` remain unchanged; structured content is retained only for tools that previously provided it. Four added real-session regressions cover service/internal exceptions across schema/nonschema tools, private chained-cause diagnostics not appearing in client responses, exact payload fields and healthy subsequent invocation.

Before edits, read-only search/pack/explore/usages were repeated for `create_server`: snapshot58, AST heuristic, partial bundle `bundle:edb8933313d5`. No reconcile or database writes.

Actual latest commands:

- Same eight-file scoped pytest command below: **exit 1; 61 passed, 1 failed, 1 existing warning; 3.16s**. Log `/tmp/gs-surface-final-pytest.log`. All 17 GS cases pass. Sole failure: existing `tests/test_mcp_receipt_tools.py:132` explicitly asserts `isError=False` for a service error, contradicting the newly requested error contract. This file is outside current ownership; reported to coordinator for permission or main-thread update. No expectation weakened and no production workaround.
- Same four-file Ruff command below: **exit 0; All checks passed**. Log `/tmp/gs-surface-final-ruff.log`.
- Production `git diff --check`: **exit 0**.

Latest frozen code hashes supersede the earlier table for two changed files:
- `src/sot_graph/mcp_server.py`: `bd64ad6be0e7885311680a330696c055626c615b7497eeea7d1d1bc8571a84cc`
- `tests/test_gs_surface_catalog.py`: `35b7990980b11cae5ad3d6152a1eeb37fdc17845e11a38f662080519a42f7e3e`

Other two code/test hashes remain unchanged. No full suite or native workload run by this lane. Final green validation remains pending correction of the obsolete out-of-ownership assertion.

## Earlier frozen delta — post-fix scoped validation

Slot released by coordinator; executed on Darwin with Python 3.14.6, pytest 9.1.1:

- `.venv/bin/python -m pytest -q tests/test_gs_surface_catalog.py tests/test_gs_surface_lifecycle.py tests/test_mcp.py tests/test_mcp_modern.py tests/test_mcp_prompts.py tests/test_mcp_receipt_tools.py tests/test_adapters.py tests/test_adapter_docs_consistency.py` — **exit 0, 58 passed, 1 existing Hypothesis warning, 3.44s**. Includes 13 new GS cases; both previously failing scenarios now pass. Log `/tmp/gs-surface-postfix-pytest.log`.
- `.venv/bin/python -m ruff check src/sot_graph/mcp_server.py src/sot_graph/adapters/claude.py tests/test_gs_surface_catalog.py tests/test_gs_surface_lifecycle.py` — **exit 0, All checks passed**. Log `/tmp/gs-surface-postfix-ruff.log`.
- `git diff --check -- src/sot_graph/mcp_server.py src/sot_graph/adapters/claude.py` — **exit 0**.
- `sot diff-impact --working-tree --provider builtin --json` — **exit 0**, no auto-reconcile requested. Snapshot 58 is stale for edited handlers; closure remains **open**, reconciliation required but deliberately not run. This covers the shared working tree, not solely this lane. CLI unexpectedly persisted a filesystem receipt `.sot/receipts/996f16911c2c5a9e799c41c0985f6a90a3a710a9b42f595e72876e15b037dd51.json`; reported as a tool side effect, not an owned deliverable. No shared database mutation requested. JSON log `/tmp/gs-surface-diff-impact.json`.

Frozen review scope: two production handlers (7 insertions, 1 deletion), two new test files, and this receipt. No full suite or native workload. SHA-256 at freeze:

| File | SHA-256 |
| --- | --- |
| `src/sot_graph/mcp_server.py` | `64821546abad9e2847b8edda271bc6fd684c626a67bf759590fe9aa6efb9e54d` |
| `src/sot_graph/adapters/claude.py` | `c86508463dd236e538ea3eec8caa5484f38f060a63a1431504e63427b934738a` |
| `tests/test_gs_surface_catalog.py` | `c50e92d423353e500334dcc4cf7ed1833fcedbd00ac26ac5d2220c4233e9f1df` |
| `tests/test_gs_surface_lifecycle.py` | `c26c251268dcae5859944dda19210498e948b6948bb99672799a763475bdd987` |

## Expanded handler ownership — historical pre-validation update

After the initial test-only run below, the coordinator authorized only the unknown-tool branch in `src/sot_graph/mcp_server.py` and AGENTS append handler in `src/sot_graph/adapters/claude.py`. The former now explicitly returns `CallToolResult(isError=True)` with unchanged text/structured unknown-tool error; recognized tool results keep their existing path. The latter recognizes the actual version-independent SOT protocol heading as well as the legacy heading, leaving existing user content untouched rather than appending again. No other production handler or managed-native path changed.

Added regressions assert exact unknown-tool payload preservation, a legitimate `sot_notes` nonerror response, preservation of user rules during repeated setup, and byte-identical existing legacy/versioned protocol content. Existing negative expectations remain strict.

Before edits, read-only CLI search/pack/explore/usages were run for both core symbols. Snapshot 58; AST heuristic, partial pack bundles `bundle:3cb925aacf93` and `bundle:8c3fc8f3e747`; indexed callers include stdio and MCP test runners, and `setup_claude`, respectively. Output was bounded; one explore pipeline emitted BrokenPipeError from truncation (not a database write).

**No tests or Ruff rerun after these edits:** awaiting coordinator test slot while exclusive latency measurement runs. Results below are historical pre-fix results, not validation of current code. No DB writes, commit, push or native benchmark.

## Initial test-only packet (historical)


Date: 2026-09-06. Scope: new `tests/test_gs_surface_catalog.py` and `tests/test_gs_surface_lifecycle.py` only, plus this receipt. No production, workflow, status, handoff, commit, push, shared database write, native execution, or benchmark performed.

## Commands and actual results

Executed from `/Users/giapminh79/code/GitHub/sot-graph` using the existing `.venv`:

- Read-only prerequisite: `sot search 'setup managed installation surface' -n 3 --json` (bounded output). Snapshot 58; tree-sitter AST_HEURISTIC_PARSER. No compiler-completeness claim. Consulted architecture requirements lines 445–466 and mapped bounded source/test ranges.
- `.venv/bin/python -m pytest -q tests/test_gs_surface_catalog.py tests/test_gs_surface_lifecycle.py`: **exit 1; 9 passed, 2 failed, 1 warning; 2.07 seconds**. Warning: existing Hypothesis/norecursedirs configuration. Log: `/tmp/gs-surface-pytest.log` (ephemeral).
- `.venv/bin/python -m ruff check tests/test_gs_surface_catalog.py tests/test_gs_surface_lifecycle.py`: **exit 0; All checks passed**. Log: `/tmp/gs-surface-ruff.log` (ephemeral).
- `git diff --check -- tests/test_gs_surface_catalog.py tests/test_gs_surface_lifecycle.py`: **exit 0** (new files are untracked, so this is not substantive tracked-diff coverage).

## Coverage and concrete failures

- SUR-02: in-memory MCP discovery checks exact tools/prompts/resources/template catalogs. Catalog assertions pass. Native `search_graph` invocation returns structured `unknown_tool` error **but `isError=False`**, failing the negative invocation assertion (`tests/test_gs_surface_catalog.py:77`; production dispatch `src/sot_graph/mcp_server.py:586`). This is an MCP error-signaling gap, **not evidence native execution succeeded**. Later negative invocation cases are not reached after this first failure.
- SUR-08: scratch Claude/ZCode configs contain pre-existing CBM and unrelated entries. ZCode preservation/idempotence passes. Claude repeated setup duplicates appended AGENTS instructions and fails byte-level idempotence (`tests/test_gs_surface_catalog.py:101`). Production `src/sot_graph/adapters/claude.py:139` checks `SOT-Graph Knowledge Reuse Protocol`, absent from the actual template heading. Claude post-idempotence preservation assertions are not reached. Assertions remain failing, without xfail or relaxed expectations; reported to coordinator.
- SUR-04/07: all five harness generators ignore poisoned dependency AGENTS/CLAUDE/SKILL files; generated output contains neither canary nor tested direct native operational command patterns. Scratch matcher loaded with repository `.sotignore` excludes vendored C source while retaining own Python source and permitting explicit file read.
- SUR-03/04: project script allowlist is exactly `sot`; root/engine/setup help has no tested direct native operational instructions. Setup does not change PATH in coexistence tests.
- SUR-12: one scratch CLI sequence imports two synthetic artifacts, selects/upgrades, prepares/probes/syncs/searches/status-checks, injects unhealthy probe and recovers, rolls back selection, rejects wrong-digest uninstall, and uninstalls selection. Mock assertions verify selected-digest compatibility evidence and sync database/command wiring; real search normalization verifies a scratch source anchor. Config, source, notes and scratch database bytes survive uninstall.

## Boundaries

Not full GS-SURFACE certification. Factory/native operations are mocked; sync ledger content, native protocol/readiness, process/listener/network auditing, built-wheel installation, shell completion installation, private executable launch digest enforcement, real harness auto-discovery, cross-schema rollback and supported-platform matrix are not certified here. No real CBM entry/process was touched. HOME/config/workspace/store/SQLite are scratch; subprocess spawn/run are forbidden in tests. Existing production changes belong to other lanes and were neither reverted nor edited. G4/G5/G7 are not promoted. No reconcile/doctor/note insertion was run because this packet forbids shared database writes.
