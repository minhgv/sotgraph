# M3a trusted configuration acceptance

Outcome: scoped configuration/admin implementation PASS; normal CLI/MCP dispatch is NOT wired yet (M3b). Baseline HEAD `7ca8634`. Separate implementation author, test author and read-only reviewer; main ran final acceptance. File ownership and hashes are in `file-hashes.json`; commands/exits/logs remain beside this receipt.

Implemented fixed OS-account-home config (not HOME/XDG/repo supplied), canonical project hash binding, selected artifact digest/generation pin, exact existing ArtifactStore/installation validation, bounded duplicate-key-rejecting JSON, private atomic persistence and directory locking. Missing/disabled defaults off; unsafe/malformed config refuses. Queries do not create config, prepare/index, spawn or write ledger. Explicit register/disable/config-status are SOT administration only.

Independent 49-case security suite uses real artifact/evidence fixtures with native launch/preparation forbidden. It covers restart, wrong protocol/digest, promotion/tamper, ownership/link/overlap/size/schema, default-home injection, unsafe concurrent mkdir, unsupported platform and preservation. Final full suite: **2,027 passed / 4 skipped**. Scoped Ruff/Pyright and claims lint PASS. Initial optional-pwd type error retained in initial receipt and fixed by narrowing.

Whole quality gate **FAIL** at the same 10 existing core Pyright errors already proven byte-identical to baseline in M1; no affected core file changed here. Coverage/Bandit/pip-audit were not reached. No whole-gate PASS claim.

Independent review closed malformed-account-home and first-registration mkdir-race findings. Concurrent artifact promotion refuses through exact identity-bound registry/factory gates. Corruption in any project entry deliberately refuses both load and disable without rewriting unvalidated authority; administrator restoration from a known-good private configuration is documented. Unsupported platforms remain implicit-off; explicit admin refuses. Darwin-only testing does not establish Windows managed support.

Main graph sequence reconcile/doctor/diff-impact exits 0. Doctor healthy schema 8. Impact snapshot generation 58, AST heuristic, 75 callers / 92 candidate tests / 0 APIs, HIGH score includes full dirty-tree evidence and unrelated pre-existing plan; closure remains **open**, remaining gaps empty. Full suite covers the tested repository, not compiler-exact impact or remote acceptance.

Rollback: disable registered binding using SOT while retaining notes/evidence/index/artifacts; revert this scoped code checkpoint if needed. No actual user registration was performed: tests used private scratch authority only. No native measurement, remote action, push, release or global default change.
