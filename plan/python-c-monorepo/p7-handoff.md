# P7 local rollback and release hygiene — 2026-09-06

No G7 promotion. No commits/push/merge. Historical P0–P4 handoffs, ADR, golden and unrelated user plan preserved.

`operations-runbook.md` documents exact support window (experimental measured Darwin arm64 only), explicit trusted administration, failure recovery, immutable quarantine, artifact rollback versus index schema downgrade, no global worker signaling and known gaps.

Real rollback evidence in `evidence/continuation-native/rollback-drill.json`: a real SOT database with sentinel user note and builtin index was byte-hashed before and after invalid-digest refusal (exit 2) and same-artifact rollback (exit 0); source/DB unchanged.

`distinct-artifact-rollback.json`: import locally built distinct digest, promote it, rollback signed release digest, status. **All four exit 0**, every hashed repository/notes database/runtime file preserved. Built artifact not executed without its own compatibility registry. This proves pointer rollback across distinct real artifacts; not cross-version native schema downgrade. Additional `evidence-bearing-rollback.json` creates explicitly labeled synthetic preservation evidence through production DB API, then logical uninstall/rollback both exit 0 preserve full DB bytes including note/run/evidence. It is NOT native correctness evidence. Actual native ledger sync records one run but no fabricated evidence when native HEAD binding is unavailable (`ledger-uninstall-rollback.json`).

Public surface snapshot and final tests live in the same evidence directory. Independent review arranged by coordinator. Remote native CI has not run: workflow configuration cannot establish platform support. Full GS-SURFACE/harness and evidence-bearing cross-schema rollback remain missing. G4/G5/G6 predecessor constraints remain strict. Do not advertise release completion from local drills.
