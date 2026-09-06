# M3b managed read dispatch acceptance

Outcome: scoped shared dispatcher + ordinary CLI/MCP policy integration PASS. Baseline HEAD `819560e`. Shared implementation froze before separate CLI/MCP writers; independent shared tester, adapter tester, shared reviewer and adapter reviewer. Main ran full acceptance; no author self-commit.

Allowlist/hashes: `file-hashes.json` (orchestrator, CLI, MCP service, two new test files), trusted opt-in runbook and this receipt directory. User's pre-existing untracked plan excluded. Managed reads reuse the installed adapter and existing exact runtime/normalization gates; no legacy executable discovery or duplicate runtime. Direct typed `search_symbols` maps only to allowed native `search_graph`; generic legacy capability selection initially rejected real installed adapters and was repaired after independent real-fixture tests exposed it.

Search now supports builtin_only/prefer_external/require_external across CLI/MCP. Managed candidates remain separate from builtin truth. Explicit builtin policy bypasses authority loading/native execution; required failures refuse; preferred failures retain reasons. Native usages is **unsupported** and deliberately falls back/refuses without invoking another native tool. No new native capability is claimed. Explicit repository denies narrow administrator permission; bounded single-read nofollow TOML cannot choose executable/registry.

Tests: shared 45 + adapter 36 independent cases; final **2,108 passed / 4 skipped**. Scoped Ruff/Pyright and claims PASS. Initial full run 2 failed / 2,106 passed exposed a historical policy-field contract regression; repaired without changing historical tests. `policy.builtin_only` describes requested policy, while `managed.status/reason` describe execution. Initial logs and final logs both retained. Existing fallback note substrings preserved with request-scoped truthful wording.

Whole quality gate remains **FAIL** at the same 10 baseline core type errors; later coverage/security stages not reached. New files/modified files scoped types PASS. Independent reviews closed path/NUL/bounds, config reread, real adapter capability, error metadata and explicit legacy-policy conflict findings. Optional MCP error details preserve builtin shape and never expose caught backend diagnostics.

Read-only means no graph/ledger/schema/JIT/reconcile/index writes for external-policy queries. SQLite read-only WAL access may create WAL/SHM sidecars; DELETE-journal byte-stability tests do NOT prove filesystem immutability for WAL databases. Runtime locks/quarantine remain unchanged. No actual user authority was registered; tests use scratch.

Final graph sequence reconcile → doctor → diff-impact exits 0; healthy schema 8, snapshot generation 58, closure **open**, no listed remaining gaps. This is AST/scoped impact, not compiler-exact or release closure. File hashes bind final tested code. No native benchmark run, remote action, push or preferred/default promotion.

Rollback: revert shared/adapter checkpoints or SOT engine disable the explicit registration; preserve artifacts, runtime namespaces, builtin notes/index/evidence. M3c operational status/recovery and M4 live surface matrix remain separate goals.
