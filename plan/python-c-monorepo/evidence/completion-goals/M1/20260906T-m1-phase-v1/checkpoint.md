# M1 diagnostic freeze checkpoint

Scope: standalone diagnostic and mocked tests only; no production or native source edits. Author: delegated implementation agent; independent tester: separate test owner; independent reviewer closed all actionable runner findings. Main coordinated acceptance and local commit.

Allowlist: `scripts/diagnose_native_latency.py`, `tests/test_diagnose_native_latency.py`, and this M1 run directory. Pre-existing untracked `plan/remaining-work-phased-plan-2026-09-05.md` is excluded.

Baseline HEAD: `1c90ccba02bcfc27d9f37ef6f95615c1fad9ec81`. Frozen command and input hashes: `manifest.json`. Historical evidence is unchanged. Measurement has not run at this checkpoint.

Acceptance: full pytest 1,978 passed / 4 skipped; claims lint passed; final standalone Ruff/Pyright passed; 34 independent mocked diagnostic tests passed. Type-only narrowing followed the full-suite run and was checked by the final scoped run. Commands, exits, original failures and logs are retained under `acceptance/`.

Whole quality gate is **FAIL**, not PASS: it stops at 10 Pyright errors in existing `codebase_memory.py`, `installation.py`, and `managed.py`. `baseline-type-verification.json` proves those files are byte-identical to HEAD. Coverage, Bandit and pip-audit stages were not reached. New-file type errors from the first scoped run were fixed without blanket ignores; final scoped checks pass.

Graph sequence: reconcile exit 0; doctor healthy schema 8, no orphaned nodes; diff-impact exit 0, snapshot generation 58, AST heuristic scope, no callers/APIs reported, no remaining gaps, closure decision **open**. Working-tree impact includes the unrelated pre-existing plan and logs; that is not a clean release closure or a complete compiler proof.

Native lifecycle audit: pinned source `46ae198f` uses connection-owned non-permanent daemon lifetime (`main.c:1555–1600`, `daemon/runtime.h:336–340`). Retained historical daemon log has ordered start/stop generations but no timestamps. It cannot apportion bootstrap/request/close wall time. This is a diagnostic limitation, not evidence of a leak, idle time or a performance fix.

Code acceptance is scoped; product/performance acceptance remains pending measurement and attribution. No G6 promotion. Scratch is ephemeral and never globally cleaned; copied inventories remain durable. Rollback: revert the standalone harness/test checkpoint; no production behavior or installed artifacts changed. Commit identity is provided by Git history; the manifest must precede measurement.
