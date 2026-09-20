# Core capabilities: evidence-first CLI and MCP

- Work ID: `2026-09-20-core-capabilities`
- Status: DELIVERED — implementation and bounded acceptance verified; global assurance/benchmark gates remain explicitly unclosed.
- Next safe action: publish the verified workspace changes to the current upstream as explicitly requested by the user. Separately scope CBM/SQLite-journal coverage and the four missing-test-evidence cases before claiming global release safety. No global installation authorized or performed.
- Main is the sole writer of this record. The user's subsequent `commit, push` request authorizes this delivery's commit and push, without force-push or unrelated temporary files.

## Context

The user approved the preceding recommendation to concentrate SOT-Graph on 15 capabilities: search, usages, pack, scope-receipt, post-change diff receipt, ordinary diff-impact, reconcile, verify, provider cross-check, map, explore, implementations, trace, bundle and doctor. Implement concrete gaps without rebuilding working capabilities or claiming historical quality gates passed.

Baseline: initial `git status --short` returned no changes. Prior record `2026-09-19-evidence-context-roadmap-plan.md` remains historical evidence, not current validation. It reports SG-202 39/44 with missing reference/test evidence, G1 union/direct differences, G3 below threshold and SG-201 blocked on independent human reviews.

Non-goals: automated production refactoring, replacing LSP/compiler semantics, changing human labels/oracles to pass gates, native rewrites without profiling, expanding visualization/export products, collecting fabricated human reviews, deleting legacy CLI commands. Commit and push were excluded during implementation and are now explicitly authorized for publication.

## Approach

Three implementation slices, using existing services and schemas rather than parallel frameworks:

1. Identity/reference/context: resolve explicit targets consistently and fail on ambiguity; preserve typed evidence and unresolved coverage; improve task-relevant pack evidence and honest budget accounting.
2. Change evidence: distinguish direct/transitive/unknown scope; preserve PRE/POST obligations, snapshot invalidation and fail-closed closure; make caller-supplied test results distinguishable from verified execution.
3. CLI/MCP surface: a focused default tool profile, explicit extended/operations access with dispatch enforcement, pack budget parity, truthful effect/heuristic descriptions, and safe exposure of existing doctor/reconcile services.

The default MCP core proposal contains seven tools: search, map, usages, pack, scope receipt, post-change diff receipt and verify drift. Existing non-core capabilities remain accessible through explicit profile selection; availability is not authorization to perform arbitrary writes. Source investigation must determine established configuration conventions before selecting flags.

Invariants: filesystem truth; stable resolved identity within each operation; explicit freshness/known gaps; no fake invocation edges; no zero-results-as-zero-callers inference; no read-only labels on writing operations; repository source is untrusted content; CLI/MCP results have equivalent semantics for equivalent inputs.

## Critical files and ownership

Ownership locked for concurrent implementation (core APIs remain stable unless coordinated):

- CoreContext: `pack.py`, `assurance/identity.py`, `assurance/engine.py`, `extractor.py`, `_vendor/graphify/extract.py`, `reconciler.py` if typed-edge persistence requires it; context/extractor/identity tests only. Anchors: build_bundle pack.py:540; identity resolver engine.py:52 and identity.py:130; extract_python extract.py:294.
- ChangeEvidence: `assurance/receipts.py`, `assurance/resolution.py`, `assurance/impact_pipeline.py`, `diff_impact.py`; receipt/impact tests only. Anchors: scope_receipt receipts.py:547; diff_impact_receipt receipts.py:1158; build_resolution_ledger resolution.py:210.
- FocusedSurface: `mcp_server.py`, `mcp_service.py`, `cli.py`, MCP entrypoint/configuration adapters, MCP/CLI tests. Anchors: registry mcp_server.py:395; dispatch :505; pack_context_bundle mcp_service.py:1517. Does not edit reconciler, pack or assurance implementations.
- Main: this work record, integration decisions and acceptance.
- Test-runner: all test/build execution and terminal smoke verification after worker edits settle.
- Reviewer: one consolidated review of completed implementation, not this plan.

Shared API changes must be communicated before use. No two workers may edit the same file concurrently. A worker with an unknown target must investigate and obtain a scope receipt before mutation, not speculate.

Cross-slice contracts: pack's existing core API remains the shared renderer; Surface implements `max_tokens` by using that API, not a second truncator. Identity fixes belong to CoreContext. Receipt fields are additive and owned by ChangeEvidence; `test_results` remains caller-reported, never promoted to independently verified execution. MCP profile selection applies to both discovery and invocation; operational synchronization is explicit.

Surface contract locked: `sotgraph mcp --profile core|full|ops`, default core, `SOT_MCP_PROFILE` fallback with explicit flag precedence and invalid values rejected. Full includes existing non-operational tools plus doctor; ops adds reconcile/provider sync. Existing pack service already supports max_tokens, so the parity change is schema/dispatch wiring, not a new core budgeting API. Existing bundle output-path validation must be reused.

Consolidated repair ownership: RepairContext owns engine.py/pack.py/vendored extractor and context regressions (R-01/03/04/05); RepairEvidence owns receipt/normalization/binding plus the snapshot producer after an additional PRE receipt and its tests (R-02/06/07/08); RepairSurface owns the actual adapter-documentation checker, its tests and existing changelog (R-09). No shared writes; no mid-wave validation. Reviewer is not re-invoked.

## Verification

- AC-01 Search: ambiguous targets are not silently selected; identity and source anchors remain grounded.
- AC-02 Usages: typed references and unresolved cases remain distinct; relevant test evidence is discoverable without fabricated call edges.
- AC-03 Pack: bounded serialized output, explicit omissions and deterministic target selection; CLI/MCP token-budget semantics are documented and exercised.
- AC-04 PRE scope: direct and transitive scope are distinguishable without hiding unknown coverage.
- AC-05 POST receipt: PRE obligations/snapshot gaps remain visible; unproven test input cannot masquerade as verified execution; failures block assurance appropriately.
- AC-06 Ordinary diff: existing blast-radius/API/test candidate behavior remains operational and distinguishable from assurance.
- AC-07 Reconcile: explicit write authorization/profile, project locking and bounded repository paths; existing synchronization semantics reused.
- AC-08 Verify: no hidden refresh on audit; audited coverage and remaining limits are honest.
- AC-09 Cross-check: no external evidence is not reported as agreement; provider distinctions are preserved.
- AC-10 Map/profiles: core profile lists exactly the intended seven tools; nonlisted tools cannot be called through hidden dispatch; explicit extended access remains available.
- AC-11 Explore: selected graph identity is passed consistently; existing node-id semantics remain explicit.
- AC-12 Implementations: preserve supported type relationships and disclose unresolved limitations; no fabricated dispatch completeness.
- AC-13 Trace: heuristic evidence is not described as complete execution proof.
- AC-14 Bundle: file-writing effect and output boundaries are explicit; source content remains untrusted.
- AC-15 Doctor: expose/reuse actual health diagnostics without duplicating incompatible health logic or unrestricted paths.
- AC-16 Acceptance: focused checks, live CLI/MCP smoke, configured final suite and one consolidated review; record exact commands/results and any remaining gate failures.

## Execution checklist

- [x] T-00 Lock source anchors, PRE receipts, contracts and ownership. AC-01–AC-16.
- [x] T-01 Ground search identity/ambiguity behavior. AC-01. Scoped-first resolution passed regressions and an actual CBM class-qualified lookup.
- [x] T-02 Improve typed usage/reference evidence and unresolved disclosure. AC-02. Typed references and context-manager paths implemented; dynamic cases remain unsupported.
- [x] T-03 Improve pack context and budget contract. AC-03. Scoped target precedence and reference neighbors implemented; MCP budget parity wired.
- [x] T-04 Preserve reconcile semantics and explicit operational writes. AC-07. Shared dispatch and ops-only invocation verified; audited freshness restored by explicit reconcile.
- [x] T-05 Verify audit purity/coverage. AC-08. Repeated audit detected a stale fixture without refresh; explicit reconcile restored audited freshness. CBM/SQLite-journal coverage remains distinct.
- [x] T-06 Distinguish direct/transitive PRE scope. AC-04. Final receipt regressions passed; unresolved coverage remains disclosed.
- [x] T-07 Strengthen POST evidence provenance and closure. AC-05. Binding/failure behavior verified; whole-worktree POST remains STALE rather than falsely closed.
- [x] T-08 Preserve ordinary diff-impact contract. AC-06. Full-suite regression and actual working-tree invocation completed.
- [x] T-09 Verify cross-provider uncertainty behavior. AC-09. Actual MCP cross-check reported zero external evidence/agreements and kept local definitions/pairs under builtin_only.
- [x] T-10 Implement focused MCP profile and map access. AC-10. Shared discovery/invocation allowlist implemented.
- [x] T-11 Preserve explicit explore identity. AC-11. Node-id contract retained and limitations disclosed.
- [x] T-12 Verify implementation relationship limits. AC-12. Existing relationship service retained; completeness claims removed from surface.
- [x] T-13 Disclose trace heuristic boundaries. AC-13. MCP descriptions updated.
- [x] T-14 Declare and bound bundle file effects. AC-14. Existing output confinement reused; write annotations explicit.
- [x] T-15 Expose safe doctor diagnostics. AC-15. CLI/MCP share collect_doctor_diagnostics.
- [x] T-16 Execute final validation and runtime smoke. AC-01–AC-16. Full suite: 2608 passed, 5 skipped; actual CLI/MCP behavior exercised. Assurance/benchmark limitations are not converted to PASS.
- [x] T-17 Consolidated implementation review and one repair pass if needed. AC-16. One review only; all reported defects repaired and covered by final verification; no second approval claimed.
- [x] T-18 Reconcile acceptance and hand off exact evidence/limitations. AC-01–AC-16. Evidence mapping and residual gates recorded below.
- [x] T-19 Post-smoke documentation cleanup: README, existing MCP guide and changelog; no generated context files. AC-10, AC-16. Byte-budget claims corrected and focused checks rerun.
- [x] T-20 Remove or archive confirmed owned verification scratch. AC-16. Reviewer scratch archived under ignored .sot; runners cleaned their fixtures. Unknown tmpaqw276aw preserved.
- [x] R-01 Reject scoped pack misses even with a literal locator decoy. AC-01, AC-03. Literal fallback guarded; nonvacuous build_bundle regression added.
- [x] R-02 Preserve failure blocking through test-report normalization. AC-05. Label-explained failures survive canonicalization; real contradictory counts remain invalid.
- [x] R-03 Handle scoped-identity query errors without UnboundLocalError. AC-01. Resolution label initialized before the guarded query.
- [x] R-04 Escape SQL LIKE wildcards in scoped names/paths. AC-01. Literal paths and case-sensitive scoped FQN suffixes implemented; wrong-sibling regressions added.
- [x] R-05 Align chained-reference evidence with its documented contract. AC-02. Comment now describes conservative first-hop evidence; no invented deeper receiver resolution.
- [x] R-06 Keep unstructured PRE binding status and reasons consistent. AC-05. Unstructured digested input remains unverified.
- [x] R-07 Bind real snapshot receipts to repository identity. AC-05. Existing canonical repo_root serialized; legacy missing-root receipts remain advisory/unverified.
- [x] R-08 Remove incidental list/tuple assertions from scope tests. AC-04. Both field-copy assertions deleted; actual truncation/gap tests retained.
- [x] R-09 Migrate adapter documentation checker to actual registry. AC-10. Service-free inventory and checker migration verified, including the final description-only rerun.
- [x] R-10 Repair repository-local test isolation and classify residual failures. AC-16. Four isolated checks and all 14 lifecycle cases passed under corrected allowed scratch roots.
- [x] R-11 Resolve post-repair class-qualified scoped lookup regression. AC-01, AC-03, AC-16. Direct negative substring offsets passed unchanged regressions and active-CBM scoped lookup.
- [x] R-12 Remove introduced static-check regressions only. AC-15, AC-16. Zero introduced lint/type diagnostics; five pre-existing pyright errors remain disclosed.
- [x] R-13 Persist MCP-minted PRE receipts for pure MCP POST lookup. AC-05, AC-10, AC-16. Digest-addressed storage is required, failures structured, write effect disclosed; real service workflow and storage-failure regressions added.
- [x] R-14 Correct misleading hard-byte-cap descriptions without changing renderer behavior. AC-03, AC-16. Schema descriptions/README/changelog aligned; 27 focused checks and adapter checker passed.
- [x] P-01 Do not assert absence, receipt `c89ca4051ea0`.
- [x] P-02 Run targeted tests and attach POST evidence, receipt `c89ca4051ea0`.
- [x] P-03 Do not assert absence, receipt `751c6345764e`.
- [x] P-04 Run targeted tests and attach POST evidence, receipt `751c6345764e`.
- [x] P-05 Do not assert absence, receipt `477d814bcd09`.
- [x] P-06 Run targeted tests and attach POST evidence, receipt `477d814bcd09`.
- [x] P-07 Do not assert absence, receipt `b1527a9603b8`.
- [x] P-08 Run targeted tests and attach POST evidence, receipt `b1527a9603b8`.
- [x] P-09 Do not assert absence, receipt `cacdcc25b738`.
- [x] P-10 Run targeted tests and attach POST evidence, receipt `cacdcc25b738`.
- [x] P-11 Do not assert absence, receipt `19d744f407fd`.
- [x] P-12 Run targeted tests and attach POST evidence, receipt `19d744f407fd`.
- [x] P-13 Do not assert absence, receipt `dd1ad2286779`.
- [x] P-14 Run targeted tests and attach POST evidence, receipt `dd1ad2286779`.
- [x] P-15 Do not assert absence, receipt `ee20b63726b3`.
- [x] P-16 Run targeted tests and attach POST evidence, receipt `ee20b63726b3`.
- [x] P-17 Do not assert absence, repair receipt `99deb3b09591`.
- [x] P-18 Targeted tests and POST evidence, repair receipt `99deb3b09591`.
- [x] P-19 Do not assert absence, repair receipt `d4aefa64f222`.
- [x] P-20 Targeted tests and POST evidence, repair receipt `d4aefa64f222`.
- [x] P-21 Do not assert absence, repair receipt `ea75864f0cfa`.
- [x] P-22 Targeted tests and POST evidence, repair receipt `ea75864f0cfa`.
- [x] P-23 Do not assert absence, repair receipt `e59ad56eaefa`.
- [x] P-24 Targeted tests and POST evidence, repair receipt `e59ad56eaefa`.

- [x] P-25 Targeted tests and POST evidence for new inventory, receipt `540582db8659`.
- [x] P-26 Do not assert absence, snapshot repair receipt `4e74def9548f`.
- [x] P-27 Targeted tests and POST evidence, snapshot repair receipt `4e74def9548f`.
- [x] P-28 Do not assert absence, MCP scope persistence receipt `3e7ff350ac6a`.
- [x] P-29 Targeted tests and POST evidence, MCP scope persistence receipt `3e7ff350ac6a`.

## Evidence and handoff

- Initial working tree clean (`git status --short`, exit 0, no output).
- Relevant SOT-Graph skill loaded. Existing prior work record inspected before starting this distinct work ID.
- Investigation assigned to configured Gemini-medium scout; no tests/builds or writes authorized for the scout.
- No current benchmark pass is claimed. Previous test/gate counts are historical only.
- PRE `build_bundle`: `c89ca4051ea0de71a6ebef3ab6869481eaf836f3c8c27fd5bf8509d32088d2f9`, correct pack.py:540 anchor, UNIQUE, UNVERIFIABLE (snapshot/dynamic/provider/coverage gaps), not BLOCKED.
- PRE `diff_impact_receipt`: `751c6345764ebbcd29bab6094a7dff090018be5ad083e9dc3d06ab0683c0411a`, correct receipts.py:1158 anchor, UNIQUE, UNVERIFIABLE (snapshot/truncation/dynamic/provider/coverage gaps), not BLOCKED.
- PRE `pack_context_bundle`: `477d814bcd093df889969f40e9055e62020044ec0d1e13d16c073922df74c705`, correct mcp_service.py:1517 anchor, UNIQUE, PARTIAL (dynamic/provider/coverage gaps), not BLOCKED.
- Discovery exposed a concrete identity defect: scope target `src/sot_graph/pack.py::build_bundle` selected a literal-named variable in `evaluation/exit_gates/fixtures/sg202_gt_subset.json` rather than the requested code symbol. Receipt `bd579a3834fa` is rejected as edit proof and becomes a regression case for CoreContext.
- Scoped method form `src/sot_graph/mcp_service.py::McpService.pack_context_bundle` yielded NOT_FOUND; bare method lookup resolved the verified source. Receipt `6edb5137d993` is rejected as edit proof.
- All PRE coverage claims remain bounded; no zero-caller or whole-repository completeness claim is permitted. Workers must obtain bounded receipts/references for additional edited core symbols and report new confirmations.
- ChangeEvidence implementation returned: direct/transitive/unknown scope metadata, PRE binding checks, caller-reported test evidence validation, no verified-execution claim. Source: assurance/resolution.py, impact_pipeline.py, receipts.py; focused tests added in five existing test files. No test acceptance yet.
- Current-state scope receipts `b1527a9603b8`, `cacdcc25b738`, `19d744f407fd` minted after edits are not POST proof and are not retroactive PRE proof. Worker was instructed to correct this wording and report pre-edit evidence. Actual POST diff receipts remain owed.
- Procedure limitation confirmed by ChangeEvidence: no additional pre-edit scope receipt was obtained for resolution.py changes beyond Main's diff_impact_receipt PRE. Current-state mints cannot repair this retrospectively. Consolidated review must inspect those callsites explicitly; no stronger pre-edit coverage claim will be made. Incorrect POST/deferred-version wording was corrected by the worker.
- FocusedSurface source settled: core/full/ops profiles (7/24/26 tools), discovery+dispatch enforcement, flag/env precedence and rejection, shared doctor diagnostics, ops-only reconcile/provider-sync, pack max_tokens schema parity, effects and heuristic disclosures, five adapter capability templates. Source edits confined to assigned surfaces.
- Worker independently ran checks despite the requested no-validation wave: reports 22 profile tests, 75 migrated surface tests, 28 post-parity tests and real stdio smoke passing. These are worker-reported, not Main acceptance; mandatory test-runner validation remains owed. Runtime smoke covered mutation/delete/add followed by reconcile and clean drift, hidden RPC denial and invalid profile rejection.
- Documentation cleanup authorized only after this runtime smoke report; existing README/MCP guide/changelog owned by FocusedSurface for cleanup. No generated harness context files will be regenerated.
- CoreContext frozen: assurance/engine.py scoped-first identity and class-qualified targets; pack.py explicit scoped selection/reference neighbors; extractor.py and vendored Python extractor typed references/context-manager protocol handling. Two new behavioral test files (24 cases); identity.py/reconciler.py unchanged.
- Engine PRE receipt: `dd1ad22867795fff5b9c84f5b8fdf72fcc70a01c39af9c3ba2760a240b40a257` minted before edits; now invalidated by intended source changes. Current-state scope `ee20b63726b388fdf69163a4d10b49c4039a5a764367b50f8b07d584e684b7b9` is not POST proof. Worker did not obtain separate pre-edit receipts for extractor paths; this procedural gap is disclosed, not retroactively repaired.
- One worker test expectation was corrected from CBM bare method name to vendored-extractor class-qualified identity; official validation will exercise the resulting target/path behavior. Dynamic receivers, string monkeypatch targets and class-body references are not claimed resolved.
- AcceptanceRunner assigned full Python suite, focused checks, real stdio/CLI smoke, current working-tree POST evidence and bounded SG202 replay. Explicit `--working-tree` is required; an earlier worker diff used HEAD-only and is rejected as proof for these source edits.
- Execution-path limit confirmed: scoped identity fixes are query-time and provider-independent. New typed references/context-manager extraction belongs to the builtin Python extractor (fallback/gap-fill under this repository's codebase-memory primary configuration); equivalent CBM engine extraction is not implemented or claimed.
- Tool provenance: PATH `sotgraph` resolves to an installed release, not this working tree. Acceptance commands must use `.venv/bin/python -m sot_graph` / `sot_graph.cli`. Global installed CLI is intentionally not modified by this workspace implementation.
- CoreContext reports shared graph reconcile complete (0 conflicts); acceptance runner is instructed to use workspace code and explicitly include working-tree edits in POST proof.
- Documentation cleanup completed in README.md, docs/SOT_GRAPH_GUIDE.md and CHANGELOGS.md: profile counts/startup/precedence, full-profile migration, operational tools, effects and pack caps. No generated context files changed.
- ConsolidatedReview assigned the single final implementation review on frozen source/tests/docs, including explicitly missing pre-edit subreceipts, provider-specific extractor limits and real POST closure evidence. AcceptanceRunner and reviewer exchange findings; Main will perform one consolidated repair pass if needed.
- Verification interruption: AcceptanceRunner job reported provider DNS failure (`ENOTFOUND daily-cloudcode-pa.googleapis.com`) without a final test receipt. On user-requested continuation, the same agent remained active on integration checks; instructed to recover existing logs, avoid duplicate commands and persist incremental evidence. This is an agent transport failure, not evidence that tests passed or failed. Consolidated review continues in its original single invocation.
- Pre-repair independent runner receipt recovered: focused 357 passed/3 failed; full excluding two OMP files 2557 passed/13 failed/5 skipped; the two OMP files separately 17 passed. Some full-log anchors were initially log offsets; runner corrected source anchors. These failures are not accepted or suppressed.
- Single consolidated review found pack scoped-decoy fallthrough; normalized failure reports downgraded block to warn; scoped query error UnboundLocalError; unescaped LIKE wildcards; chained-reference comment/behavior mismatch; unstructured PRE status inconsistency. Runtime-correlated addendum identified missing serialized repo identity making foreign PRE checks ineffective, two incidental list/tuple test assertions, and the adapter documentation checker still parsing the old registry syntax.
- Repair PREs minted from workspace source before repair: pack `_find_target` `99deb3b0959152d086621f0a39f615c2f3dc6770d7614bae5e40faad92f88df4` PARTIAL; engine resolver `d4aefa64f222aed9319fa675d9f2120f1f2b8a6f2df50b24a4db21162978c071` UNVERIFIABLE; safe_commit_verdict `ea75864f0cfa8d4badfb36461082b7c2a2d67f21816ad141f6c80dfe751d9743` UNVERIFIABLE; pre_receipt_binding `e59ad56eaefa03f42c6350f07264e22aa69bc0ea4e6481a10e5ddb1d68aa051d` UNVERIFIABLE. Correct source anchors, no BLOCKED result; known dynamic/enumeration/parser/provider/snapshot gaps retained.
- Test harness investigation: placing temporary fixtures under repository .sot lets git discover the enclosing repository and triggers .sot path exclusions/trust rules. Before source repair, runner is checking environment-suspect failures with a repository-local `.tmp-corecap-validation` fixture root and GIT_CEILING_DIRECTORIES set to that root. Logs remain under .sot; no access outside allowed directories.
- Corrected harness results: non-git CBM snapshot, file-journal exclusion, MCP diff-impact sync/async and ordinary snapshot checks pass with isolated git discovery. All 14 lifecycle tests pass under new `~/.omp/tmp/corecap_lifecycle` scratch outside the checkout (inside the allowed global config directory). The foreign-PRE test still fails and remains a genuine repair target. Final runner will use a unique ~/.omp/tmp fixture root, with logs/receipts retained in the repository.
- All verification processes stopped before the consolidated repair batch. Nine source/test repair items assigned across three non-overlapping workers; runtime-environment repair R-10 DONE, no unrelated production fixes required.
- RepairSurface new inventory PRE: `540582db86594826bc51c5b7f131703e2cc0547d4496da02dfbf946c908f22e8`, ABSTAINED because the additive symbol does not yet exist; not caller-coverage proof. Existing registry insertion location verified by worker; Main approved a deterministic service-free reader only if importing the module remains SDK-optional and side-effect-free.
- Snapshot repair PRE `4e74def9548fecd9a767974e81782faa514d88684342be198d0a71a2dd13c0e4`: UNIQUE targets capture_worktree_snapshot (snapshot.py:229) and WorktreeSnapshot.as_dict (snapshot.py:142); 27 observed direct callers, dynamic/parser/snapshot coverage gaps, not BLOCKED. Main approved before producer mutation: serialize existing canonical repo_root, preserve descriptor digest formula, let new receipt digests cover added field; legacy snapshots without repo identity remain unverified, not silently bound.
- RepairSurface R-09 frozen: service-free deterministic tool_inventory in mcp_server.py, lazy registry-backed scripts/adapter_docs_check.py, consumer/profile/phantom-name regression and existing changelog entry. Incidental size and forever-absent-name assertions removed. Optional MCP SDK is not required by the inventory path. Final independent validation remains owed.
- Additional RepairContext PREs: `_scoped_identity_candidates` engine.py:40 → `116a0cc8b89097a57d4f02ef75b4217ad206046499497fec0f9e29037f44d6be`; scoped pack resolver union → `d7a275aaf1b1a2f61008a91ee30535c3486c787128c427f093040afbbb9d8386`. Worker reports zero additional omp_confirmations, measured coverage with generated/unresolved-edge gaps. Vendored extract_python receipt `328b1f24620ed4966a4b8e4043e15f0d2cf78cd24651133809ca12375e317fc8` has no source anchors because vendor is outside the journal; not edit-proof. Its repair is comment-only, with registry dispatch as bounded source evidence.
- AcceptanceRunner removed its obsolete repository-local `.tmp-corecap-validation` fixtures; retained logs and durable validation receipt. Final reconcile must not include throwaway fixture source.
- RepairEvidence frozen without validation: resolution.py normalization/binding repaired, snapshot.py serializes existing repo_root, producer/foreign-repo/pipeline round-trip regressions added. Descriptor digest formula and stored receipt payloads unchanged; no MCP schema changes. These repairs await the final independent suite and real CLI/MCP proof.
- RepairContext frozen without validation: all four findings repaired, including decoy-present/scoped-missing regression, broken-query handling, underscore path/name collisions, path:line wrong-node selection and wrong-case scoped suffix tests. Additional chain test documents conservative supported evidence; no dynamic inference expansion.
- FinalAcceptance assigned a complete Python suite (no OMP exclusions), workspace import provenance, configured available static checks, actual stdio/CLI scenarios, current working-tree POST receipts and bounded original-oracle SG202 replay. Fixture roots use unique allowed ~/.omp/tmp directories; logs/evidence remain in repository. No second Reviewer invocation.
- Final verification ownership split: FinalAcceptance owns full pytest/static/adapter checks and `.validation.json`; RuntimeProof owns isolated real CLI/MCP smoke, workspace graph reconcile/POST, risk log, SG202 replay and separate `.runtime.json`. Both use separate unique ~/.omp/tmp fixture roots; no shared artifact writes. Source remains frozen.
- Integrated changelog cleanup is complete: scoped lookup fixes (bare-name behavior unchanged), builtin-only reference/protocol evidence, repository-bound PRE serialization and legacy advisory status. Binding `unverified` is kept distinct from graph assurance `UNVERIFIABLE`.
- Final full suite (all tests including OMP): 2603 passed, 3 failed, 5 skipped (2611 total), 773.97 seconds. Failures are the existing class-qualified engine resolution, underscore-name suffix resolution and class-qualified pack scenarios in tests/test_scoped_identity.py:126/157/189. Source remains unaccepted; RepairContext is diagnosing exact SQL/backend/fixture behavior before editing. RuntimeProof was instructed to freeze dependent operations, not use bare-name fallbacks to hide the failure.
- R-11 root cause confirmed: SQLite length(integer) measures decimal text length, so `substr(fqn, -length(?))` with an integer length bound sliced only the final digits' count of characters. RepairContext is applying direct negative integer starts in engine/pack; real SQLite fixtures and existing expectations remain unchanged.
- Static baseline comparison: five pyright errors/three warnings pre-exist in freshness.py/graphstore.py/claims.py/holdout; three introduced errors remain in mcp_server.py (possibly unbound result) and mcp_service.py (_DoctorView borrowed Database methods). Three introduced test lint issues (Optional import and two unused imports) assigned for bounded correction; unrelated baseline diagnostics are not suppressed or fixed.
- RuntimeProof confirmed a real end-to-end gap: MCP scope returns a PRE digest without storing it, so subsequent MCP POST returns not_found. Profiles 7/24/26 verified. All runtime operations frozen before repairs. RepairSurface will persist via existing ReceiptStore, declare the write effect and add pure MCP workflow coverage; no CLI seeding or unknown-digest fallback.
- Pre-correction SG202 replay: 90 attempted, 44 measurable, 32 full successes (72.73% measurable, 35.56% all); gate FAIL. Artifact `.sot/tmp/corecap/replay.json` captures the defective scoped-suffix state and is not final benchmark evidence. RuntimeProof reported graph reconciliation with zero drift/parse failures and bounded risk history.
- R-11 source correction settled: only the two suffix SQL bindings changed, with all class/case/wildcard regression expectations retained. R-12 test-only lint fixes settled: imported Optional where used and removed two unused imports, no suppressions. Surface type/persistence fixes remain pending; runners remain frozen.
- R-12/R-13 source/docs frozen: private _ReadOnlyDoctorView adopts an existing read-only connection without schema initialization/migration; dispatcher raises unhandled_tool instead of an unbound result. MCP scope now stores PRE via existing ReceiptStore before returning the digest, verifies the address and raises receipt_store_write_failed on storage failure; unknown digest lookup still fails. ToolAnnotations/README/changelog disclose the write.
- Valid MCP scope PRE `3e7ff350ac6acba3bba4fae5d39877fb98d6ec37e1b8128278cab258e4a8ce3c`: PARTIAL, anchored mcp_service.py:1922, known dynamic/enumeration/parser/provider gaps, not BLOCKED. Earlier class-less ABSTAINED receipts were discarded, not accepted as target proof.
- Final runners explicitly received SOURCE_FROZEN: focused repaired tests precede the full suite; independent real MCP smoke must mint PRE and consume its returned digest without CLI seeding. Prior failing suite/replay results remain historical evidence, not overwritten as success.
- Final focused verification: 154 passed, 0 failed, 53.81 seconds. Final full suite: 2608 passed, 5 skipped, 4 warnings, 760.45 seconds; raw log `.sot/tmp/corecap/pytest_full_run2.log:225` independently checked. Exact argv and environment are in `docs/plans/2026-09-20-core-capabilities.validation.json`.
- Static checks: adapter-doc checker passed; no introduced Ruff diagnostics or pyright errors. Pyright's raw exit remains 1 for five baseline errors/three baseline warnings; baseline comparison is a separate successful delta check, not a clean global type-check. The validation artifact was corrected to preserve raw exits, exact arguments and real timestamps.
- Actual MCP RPC proof: profiles 7/24/26, hidden mutator denial, PRE storage/digest-to-POST flow, doctor health data, bundle path_traversal refusal, successful bounded pack plus token/byte overflow handling, and cross-check with no invented external agreement. Raw RPC log: `.sot/tmp/corecap/mcp_rpc_executions.json`. CLI bundle explicit output paths remain allowed by design; that is not the MCP boundary.
- SG202 original-oracle replay: 40/44 measurable successes (90.91%), 40/90 roster tasks (44.44%), four remaining missing-test-evidence cases. The 95% measurable gate still FAILS; historical baseline was 39/44, and the defective intermediate state was 32/44. No labels or thresholds changed.
- Whole-worktree POST remains STALE, not closed: CBM read-through freshness can be clean while SQLite file_journal has only about 30 entries and cannot certify all changed paths. Dynamic/parser/budget gaps remain explicit; legacy PRE snapshots without repository identity bind as unverified. This is a residual assurance limitation, not proof of global safety.
- Reviewer confirmed ownership of 14 .review_tmp diff artifacts and archived them under `.sot/tmp/corecap/review_scratch_diffs/`; no second review was performed. Root `tmpaqw276aw/` is not reviewer-owned and is preserved unless provenance establishes it is this task's disposable fixture.
- Byte-budget correction: actual MCP max_bytes=1024 returned 2416 compact JSON bytes with completeness PARTIAL, limits.truncated and byte_cap_unreachable. This is a best-effort source/YAML budget with an identity floor, NOT a hard response cutoff. max_tokens overflow was refused with BUDGET_TOO_SMALL. Only schema description text/README/changelog changed after the full suite; the subsequent focused profile/schema suite passed 27 tests and adapter_docs_check exited 0.
- Active-backend identity proof: exact src/sot_graph/mcp_service.py::McpService.pack_context_bundle resolved UNIQUE/PATH_SCOPED_TARGET to cbm:22388, mcp_service.py:1640–1693, through the active CBM read-through adapter. Probe digest 8088cb722d66729e92d694ad972aacea24d14344b73d2802767f71ca36f351fd is a validation observation, not retroactive PRE edit proof.
- P-01–P-29 confirmations are fulfilled as bounded no-absence acknowledgements plus attached test/POST evidence, NOT as global graph closure. Seventeen tracked PRE/current-state digests have actual working-tree POST attachments in `.sot/tmp/corecap/post/` and the runtime artifact. After review-scratch cleanup, 36 changed paths remain uncertified by the SQLite journal; final POST status remains STALE. Current-state-only scopes are never relabeled pre-edit evidence.
- Publication authorization: the user requested `commit, push` after delivery. The branch is `main` with upstream `origin/main`; the implementation, tests, documentation, work record and two authoritative JSON receipts are in scope. The JSON receipts require explicit staging because `.gitignore` ignores `*.json`. Unknown `tmpaqw276aw/` and ignored raw runtime artifacts remain outside the commit. Publication does not change the recorded assurance limitations; Git command results are reported in the session handoff.

### Final acceptance mapping

| Criteria | Observable evidence | Boundary |
|---|---|---|
| AC-01–AC-03 | Scoped/typed-reference regressions, active-CBM qualified lookup, actual MCP token refusal and byte-floor disclosure | Dynamic references remain unsupported; max_bytes is best-effort |
| AC-04–AC-06 | Full receipt/impact tests, real PRE-to-POST flow, foreign/legacy binding cases, strict gate exit 2 for reported failures | Caller test claims are not verified execution; whole-worktree POST is STALE |
| AC-07–AC-10 | Ops gating, explicit reconcile/audit, absent-provider cross-check, seven-tool core and 24/26 extended profiles | Clean audited CBM drift does not establish SQLite-journal coverage |
| AC-11–AC-14 | Existing-service regressions, explicit node identity, heuristic descriptions, actual MCP bundle escape refusal | No fabricated dispatch completeness; CLI explicit output paths remain allowed |
| AC-15–AC-16 | Real MCP doctor, 2608-pass full suite, 27-pass final metadata checks, one review and consolidated repairs | Five baseline type errors; SG202 40/44 below 95%; no release-safety approval |

Authoritative receipts: [validation](2026-09-20-core-capabilities.validation.json) and [runtime](2026-09-20-core-capabilities.runtime.json). The executable entrypoint is `PYTHONPATH=src .venv/bin/python -m sot_graph`; the global pipx command was not updated.

## Assumptions and contingencies

- Preserve established configuration patterns. If introducing a default core profile changes existing MCP discovery, provide explicit full access and migrate tests/documentation together rather than silently removing capabilities.
- Graph receipts with BLOCKED status must be resolved before the corresponding edit. Each confirmation becomes its own tracked task referencing the receipt digest.
- If reference gaps require unresolved dynamic semantics, keep PARTIAL/unknown instead of guessing; report any acceptance criterion not met.
- Human study remains externally blocked; this work cannot manufacture independent reviews.
- Read/write access stays inside this repository and ~/.omp. Logs/receipts stay in the repository; fixture roots requiring an outside-checkout trusted layout use newly created unique directories under ~/.omp/tmp with cleanup limited to those created paths.
- Do not widen unrelated historical G3/SG201 work into a new automatic release decision.
