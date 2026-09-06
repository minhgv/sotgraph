# M3c operational status/recovery acceptance

Scoped outcome PASS. Baseline `3468796`. Separate two-file implementation owner, independent recovery tester and prior-test owner, read-only reviewer; main full acceptance. Exact allowlist/hashes in file-hashes.json plus runbook and this evidence directory. No actual user registration/native execution.

Added operational config-status/config-doctor (store optional), canonical registration identity, expected/current safe artifact digests, validated namespace/generation and runtime readiness/quarantine. All refusal reasons/remediation are fixed SOT operations; no raw native next_action or exception text. Readiness explicitly does not grant query permission. Missing/disabled returns before artifact resolution; no automatic repair, prepare, sync, index or deletion.

Version contract: diagnostic responses are schema 2; persisted authority and register/disable response schemas remain 1. Consumers select operation first, then its response version. Diagnostic exits: 0 disabled or ready, 1 valid enabled but unready, 2 refused (including unsupported platform). This intentionally supersedes M3a enabled-registration exit 0. Default unsupported-platform loader remains off without touching config; diagnostics are explicit refusal.

Independent recovery 22 tests plus 49 prior security tests cover fresh module reload, missing/tampered/incompatible assets, synthetic quarantine, digest promotion refusal and verified old-digest rollback preserving namespace, disable preserving notes/evidence/index, and fixed RuntimeError/RecursionError sanitation. Synthetic distinct-digest fixtures do NOT prove native cross-version/schema rollback.

Final full suite **2,130 passed / 4 skipped**; scoped Ruff/Pyright and claims lint PASS. Whole quality gate remains FAIL on the same 10 pre-existing core Pyright errors; coverage/security stages not reached. Raw commands/exits/logs retained. Independent review closed all actionable findings, including all three status exception guards and per-operation version semantics.

Graph reconcile→doctor→diff-impact exits 0; doctor healthy schema 8; snapshot generation 58, closure open, no listed remaining gaps. Scope remains AST heuristic and working-tree bounded, not release closure. No platform support promotion, remote CI, push or publication.

Rollback: disable valid registration through SOT, or restore known-good private authority before disabling malformed authority. Preserve runtime/index/artifact/evidence resources. Revert this status-only checkpoint if response v2 migration is unwanted. M4 live GS-SURFACE matrix and M5 genuine native version/schema drill remain unproven.

Audit note: M3b evidence commit retained original failing pytest output with one trailing-whitespace line. Its diff-check reported that raw-log formatting issue; production/test source whitespace checks passed. Historical raw evidence was not rewritten to conceal it.
