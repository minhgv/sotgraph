# Experimental local managed engine runbook

No supported native release platform is certified. Darwin arm64 local build and release acceptance are measured; remote CI is configuration only. Default Python-only behavior is unchanged. Source manifest binds v0.10.8 at `46ae198fc11cda80e817acbc5f5908d7c2de7032`; release runtime compatibility binds exact `2412e017…`, not installed/ad-hoc-signed or locally built digests.

## Trusted local administration

Use `sot --root REPO engine --store ABS_PRIVATE_STORE ACTION`. Store must be disjoint from repository/runtime and not symlinked. No download or PATH discovery occurs.

1. `import --source ABS_BINARY --manifest ABS_MANIFEST` stages immutable verified bytes. Manifest schema: schema_version=1, name, digest, platform, protocol=`artifacts-v1`, engine_commit. This does not select or execute the artifact.
2. `promote --digest SHA256` selects an existing verified artifact. No repository or harness configuration changes.
3. `doctor` / `status` verify artifact identity without native execution. Artifact compatibility and runtime freshness are explicitly not inferred.
4. `prepare`, `probe`, `sync`, `search QUERY`, `runtime-status` require explicit `--runtime-root`, `--registry`, `--protocol`, optional `--generation`. Registry must be bounded trusted administration outside the repository; operation records must match exact artifact/protocol. Never trust repository-supplied records as administrator evidence.
5. Only `sync` requests indexing. `search` accepts one SOT query, not arbitrary native operations/arguments; measured table schema is normalized and every subject source-verified. Native payload is not exposed. Index HEAD binding remains unavailable: freshness stays unknown even for verified source anchors.

## Recovery and rollback

- Missing/tampered artifacts: preserve existing store; verify administrator source/manifest, explicitly import and promote. Never silently adopt/repair unknown files.
- Timeout: inspect `runtime-status`. A quarantined generation is never cleared automatically. Use a NEW explicit generation; preserve old namespace for investigation. Never signal unrelated/global workers.
- `rollback --digest PREVIOUS_VERIFIED_SHA` selects an existing artifact and preserves notes, evidence and all runtime namespaces. Binary downgrade does not authorize opening a newer index: select the old compatible generation or rebuild into a new namespace.
- `uninstall --digest EXACT_SELECTED_SHA` performs safe logical uninstall: verifies selected artifact and owned pointer, removes only that pointer under store lock, preserves binary/manifest/runtime/source/notes/evidence. It never signals a worker. A subsequent explicit promote/rollback reactivates retained bytes. Store reclamation remains manual administrator work, not destructive uninstall.

## Release checklist / known gaps

- [x] Exact upstream source and generated parsers retained; inventory verifier.
- [x] Scratch build and local release artifact operation capture.
- [x] Python wheel/sdist separate from native source; experimental path-filtered CI.
- [x] Local import/promote/prepare/sync/search and safe refusal evidence.
- [x] Same-artifact rollback and invalid-digest refusal preserve real notes DB bytes/source.
- [x] Distinct release/build artifact pointer upgrade/rollback: four operations exit 0; full repository/notes DB/runtime bytes preserved (`evidence/continuation-native/distinct-artifact-rollback.json`). Built runtime not executed; not a cross-schema downgrade proof.
- [x] Nonempty evidence-bearing ledger preservation drill through uninstall/rollback, using explicitly synthetic test evidence via production DB API; notes/run/evidence DB bytes identical. Native cross-schema downgrade is not certified.
- [ ] All GS-SURFACE scenarios/harness coexistence tested behaviorally.
- [ ] Remote native CI actually executed; supported platform matrix approved.
- [x] License inventory text review complete (`license-review.json`): permissive/public-domain families, 7 tooling filename matches, every upstream notice unchanged. Legal opinion/per-file provenance certification remains external.
- [x] Four controlled language cells measured5index invocations and30queries each provider, CPU/RSS receipts; performance FAIL all cells. Cold-cache/incremental and detached-worker resource limitations explicit; representative quality/support certification not claimed.
- [x] Independent final reviewer CLEAN (`independent-review.json`); full post-administration suite receipts retained. Final post-repair run follows sequential benchmark.

Do not promote G4–G7 from this partial checklist. Existing evidence paths distinguish successful, refused and aborted runs. No global provider preference is changed.
