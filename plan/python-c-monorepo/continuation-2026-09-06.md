# Authorized continuation — 2026-09-06

Baseline: `feat/python-c-monorepo-phased` at `0428c1b`. No commit, push or merge authorized or performed. Historical P0–P4 handoffs, ADR and golden fixtures remain immutable. The unrelated `plan/remaining-work-phased-plan-2026-09-05.md` is preserved.

## New explicit authorization

The user approved the **full upstream source subtree**, generated sources intact, from release v0.10.8 at `46ae198fc11cda80e817acbc5f5908d7c2de7032`. Measure the actual budget rather than pruning to an invented estimate. This supersedes the old handoff's pending topology approval, not its historical observations. No release platform certification is implied.

## Evidence produced

- `evidence/source-import-manifest.json`: all 2,050 upstream entries, including the 20-byte `Formula` symlink, Git blob identities, file modes and SHA-256. Exact source payload: **1,332,757,092 bytes**. Initial regular-file count excluded that symlink; final manifest includes it.
- `scripts/verify_native_source.py`: offline byte/mode/inventory verification, exit 0 on imported tree. Import used `git archive` against exact release; no subtree commit or generated-source pruning.
- `evidence/native-build.log` and `native-build-receipt.json`: actual scratch `make -f Makefile.cbm -j2 cbm`, exit **0**, 133.33 seconds, Darwin arm64. No installer, UI target, binary execution, or harness registration invoked. HOME/TMP/cache redirected to scratch. This is a scratch source build, not a clean committed-checkout release certification.
- `evidence/source-budget-license-inventory.json`: 161 path-classified generated parser files, 1,249,323,393 bytes; 183 license/notice inventory entries. Inventory is not a legal clearance. Build artifacts **593,302,728 bytes**, including binary **296,408,656 bytes**; isolated cache 0 bytes. Built digest `8953ad08b2815817d3cc3704fddc88611e4d1678ebc4e4b45c4dd0e122b72c13` is NOT automatically compatible merely because source/version match.
- Upstream `.git` count-objects measurement is explicitly a shared multi-revision store, not release-exclusive Git size. No estimate is substituted for that missing measurement.
- Native experimental CI is path-filtered and never runs upstream install/UI hooks. Configuration is not evidence that CI has run. Python package exclusion and default self-analysis exclusion keep the dependency out of the normal Python artifact/index path.

## Fresh verification and blocker

Full Python suite: **1,880 passed, 4 skipped, 4 warnings**, exit 0, 177.46 seconds (`evidence/continuation-tests.log`, XML and receipt). Offline wheel/sdist build exited 0 using cached setuptools and nonexistent CC/CXX; initial missing-setuptools failure (exit 1) retained separately. Verifier Ruff, reconcile, doctor, diff-impact and history inspection exited 0. Diff-impact does not certify untracked imported source. No independent final reviewer was available through the execution tools.

The real native acceptance attempt **exited 2 before spawn**: signed archive `9bd840df…` contains binary `2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf`, while historical acceptance requires `996bad5f…`. Archive bytes independently rehashed and payload streamed from tar (`evidence/continuation-binary-identity.json`). Correction: differing archive, installed/ad-hoc-signed and locally built digests do not themselves contradict provenance. The historical harness is bound to a different artifact; signatures authenticate this archive, while operation compatibility must be freshly measured for its exact payload. Raw failure is retained under `evidence/continuation-native/`. Neither this release binary nor the scratch-built `8953ad08…` inherits the old operation registry. No pin was bypassed, no global daemon contacted.

P5 public installation/status surface, P6 controlled matched benchmark and P7 rollback rehearsal were not completed. They cannot be certified from mocked tests, source build, or historical artifact evidence. Exact-artifact compatibility must be measured before promotion; the identity discrepancy remains unresolved rather than relabeling the release or widening trust.

## Fresh release acceptance update

`evidence/continuation-native/release-acceptance.py` explicitly hashes the signed archive and exact `2412e017…` payload, then reuses the historical capture algorithm with a NEW protocol ID (`p4-release-2412e017-measured-v1`) and freshly captured operation records. It does not modify historical files or reuse the old registry. Actual run: **exit 0, ACCEPTANCE_RESULT PASS**; `release-acceptance-exit.json`, `release-acceptance.log`, `p2-managed-registry-records.json` and `p2-managed-acceptance-receipt.json` under that new directory.

Measured prepare/repeated prepare, sync and three queries all returned `ok`; source/cache query snapshot identical. Unsupported trace operation denied without spawn. Forced deadline reported `cancellation_unknown`, quarantine persisted, reuse refused, readiness marker absent. Final process inventory found no additional native PIDs; no pre-existing process signaled. Timings: capture 45.29s, managed acceptance 52.20s, forced deadline 1.80s. This is bounded experimental acceptance, not a full benchmark or GS-SURFACE certification. The previous exact-pin refusal is retained as historical failure, but **is no longer a blocker** for this new artifact-specific acceptance.

## Promotion constraints

G0–G3 retain their prior scoped PASS evidence; this continuation does not broaden them. G4 remains BLOCKED until installation/GS-SURFACE acceptance and final license/platform review have evidence. G5–G7 cannot promote before G4. Darwin arm64 remains experimental; other native platforms unverified/unsupported by this work. No globally preferred provider or performance claim is authorized by a source build.
