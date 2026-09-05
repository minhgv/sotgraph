# P2 Managed Native Acceptance — FIRST ACTUAL OUTCOME (G2 BLOCKER)

Date: 2026-09-06. Host: macOS arm64 (private local scratch). sot-graph HEAD `d96cb4b`.
Binary: `~/.local/bin/codebase-memory-mcp` sha256 `996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435`
= pinned release artifact of `46ae198fc11cda80e817acbc5f5908d7c2de7032` (digest re-verified pre- and post-run; no copy made).
Scope: this file + `p2-managed-*` artifacts only. NO production edits, NO commits, NO promotion of P2.

## Verdict

**G2 BLOCKER — `ManagedNativeRuntime` cannot run the release binary on macOS arm64 as currently
designed.** Stopped at first blocker per directive. No acceptance, no promotion.

Actual managed prepare (as-shipped executor, profile-served env, no bypass):

```
PREPARE status= runtime_refused  runtime_state= QUARANTINED  cancellation= None  wall=0.30s
ERROR= config_set_auto_watch native receipt invalid (rc=1); native diagnostic withheld
profile_state= QUARANTINED  marker_exists= False
```

Receipt: `p2-managed-minprepare-receipt.json`. Quarantined namespace left frozen on disk
(`/private/tmp/p2-minprep-wyw1684d/managed-minprep-…`), never cleared.

## Root cause (proven, not inferred)

The daemon rendezvous endpoint is a UNIX socket whose path is
`<CBM_RUNTIME_DIR>/cbm-daemon-<uid>/cbm-<16hex>.sock` (`src/daemon/ipc.c:869-935` at 46ae198f).
macOS `sockaddr_un.sun_path` caps at 104 bytes. The profile namespace dir name is
`managed-<generation>-<repo_hash32>-<digest32>` (`src/sot_graph/providers/runtime.py:121`) = 81
chars, so the socket path under the profile-served `CBM_RUNTIME_DIR` is **163 chars > 104**.
`unix_address_set` (`ipc.c:662-680`) fails WITHOUT setting validation detail — exactly matching the
observed empty-detail error the binary prints (`src/main.c:2502-2515`):

```
codebase-memory-mcp: secure CLI coordination could not be created (endpoint)
```

77-byte stderr, rc=1, ~0.02-0.3s (pre-daemon early exit) on EVERY dispatch form
(config get/set, cli index_repository, cli <tool> --args-file — all measured identically).

**Control probe (same binary, same 7-key replacement env, same repo, ONLY the rendezvous parent
shortened): rc=0** — `config get auto_watch` returned `true` from an isolated private cache with the
UI-off pre-seed present. The binary is healthy; the blocker is the rendezvous path length produced
by the profile namespace layout. CORRECTED consistency note: the prior pinned receipts used an
ISOLATED `CBM_RUNTIME_DIR` (7-key env, `p2-runtime-receipts.json` env_modes) — NOT the global
default rendezvous; `p2-runtime-controls.md:40` ("`/private/tmp/cbm-daemon-501` 150 files
newest … pre == post") documents that the GLOBAL rendezvous was observed UNCHANGED pre/post
(proving no interaction), not which runtime dir the runs used. Their env value was short-path;
the failing managed env value was long-path (namespace runtime dir). Same env shape, different
path length — that difference is the whole blocker.

## Pre-candidate source confirmations (done before any candidate acceptance)

- `--args-file <path>` transport confirmed at exact release commit: `src/main.c:715-746`
  (precedence: `--args-file` first; file slurped as JSON args) and `src/cli/cli.c:12411`
  (per-tool help form `cli <tool> --args-file <path-to-json>`). Prior pinned receipts covered
  inline-args only; args-file had never been measured. (Measured live here only via the control
  probe path classification; full per-op args-file captures were NOT performed — blocked by the
  coordinator stop directive; see "Not done".)
- Tool schemas at 46ae198f: `index_status` takes `project` (`mcp.c:621+`); `search_graph` takes
  `query/project/format/limit` (`mcp.c:437-459`); `list_projects` takes `offset/limit/
  include_details/metadata_only` and has NO `project` key (`mcp.c:609-617`) — the executor's
  `query("list_projects", {})` injects `project` and its acceptability was NOT measured (blocked).

## Safety receipts (all held — no deviation, no NEG repeat)

- UI-off pre-seed `cache/config.json` = `{"ui_enabled": false}` written by `profile.initialize()`
  BEFORE any native start; verified on disk.
- Spawn primitive: only `sot_graph.proc.run_command` with `env=` 7-key replacement
  (HOME/CBM_CACHE_DIR/CBM_RUNTIME_DIR/XDG_CONFIG_HOME/TMPDIR/PATH=/usr/bin:/bin/TERM=dumb);
  no `env_extra`, no inheritance; isolated rendezvous only (global port and global
  `/private/tmp/cbm-daemon-501` rendezvous untouched).
- Executor fail-closed behavior verified: typed `runtime_refused`, sticky QUARANTINED profile,
  marker never written, zero filesystem changes to repo/cache on refusals (full-hash snapshots),
  `trace_path`/config-op/arg-override queries denied without spawn (earlier full-harness dry run).
- NO signals fired by this work; pgrep pre/post identical (8 == 8, zero new pids); no orphan.
- Registry used for the trial: PROVISIONAL IN-MEMORY LAB RECORDS with clearly-marked placeholder
  fixture digests ("NOT release-compatible evidence", `tested_by` says so in-band); never persisted;
  no measured-support records fabricated; no production trust touched.

## Not done (honest scope)

Per-op capture round, executor sync/query acceptance, prepare-twice idempotence on a WORKING
profile, `--args-file` per-op digest fixtures, and the tiny-timebound `cancellation_unknown`
exercise are UNREACHABLE on this host until the blocker is fixed (prepare refuses in ~0.3s, so the
timeout path cannot be triggered through the executor either). `p2-managed-acceptance-harness.py`
in this directory contains the full design (capture → measured-digest registry → executor
acceptance → control probe → hygiene) but was not run end-to-end; `p2-managed-records.json` from
its single earlier run and `p2-managed-minprepare-receipt.json` are the actual raw receipts.

## POST-FIX RETRY (same day, after production fix landed on disk) — PASSED
(SUPERSEDED by the DEFINITIVE MEASURED ACCEPTANCE section below — provisional placeholder
registry; wall numbers there predate the revision-2 wall-breakdown correction)

Runtime fix verified in source before retry: namespace `m-<24hex>` (`runtime.py:112-121`),
ctor socket `sun_path` preflight (`runtime.py:149-167`, root ≤27 bytes for uid 501), executor no
longer injects `project` into global-scoped `list_projects` (`managed.py:215-226`).

Minimal managed run (`/private/tmp/s-hxlcmsks`, 23-byte 0700 root; prior quarantined namespaces
untouched; provisional in-memory placeholder registry only, never persisted):

```
PREPARE1  status=ok READY          wall=5.93s   (config set/get + db verify + marker commit)
PREPARE2  status=ok  wall=0.0s     idempotent via valid marker, zero native calls
SYNC      status=ok indexed        wall=20.04s  receipt status=indexed, project binding verified
QUERY search_graph  status=ok 8.73s keys=[cols,has_more,rows,search_mode,total]
QUERY index_status   status=ok 8.59s keys=[edges,nodes,not_indexed,parse_partial,project,...]
QUERY list_projects  status=ok 8.66s keys=[has_more,limit,offset,projects,returned,total]
FS_INVARIANT: repo+cache full hashes identical across all queries
HYGIENE: one namespace daemon (pid 74517) observed post-queries, gone by the next poll (exit
itself not observed — cause unknown); pgrep returned to the 8-pid pre-existing baseline; no
signals fired in this run (no deadline kill occurred in it); prior quarantined
namespaces left frozen.
```

Receipts: `p2-managed-acceptance-receipt.json` (sanitized) and `p2-managed-lab-raw.json`
(PRIVATE LAB RAW stdout for diagnosis — sync/search/status/list payloads; not for publication).
Still EXPERIMENTAL: registry digests were clearly-marked placeholders, so this run proves the
EXECUTOR + PROFILE + TRANSPORT end-to-end, NOT release-compatible fixture trust. No promotion.

## DEFINITIVE MEASURED ACCEPTANCE (final; supersedes the provisional runs above)

Runner: `p2-managed-acceptance-harness.py` (committed-capable CLI: `--binary PATH --root DIR`,
trusted inputs, no negative controls; raw stdout bytes stay in run scratch — evidence artifacts
are digest/sanitized/status only; prior lab-raw files removed from this directory).

Measured per-op fixture digests (sha256 over EXACT raw stdout text as delivered by
`proc.run_command`, computed BEFORE sanitization; sanitized fixture copies + redaction map +
explicit raw≠sanitized binding documented per op in `p2-managed-fixture-digests.json`;
raw bytes live only in the run scratch, never published):

| op | raw_sha256 (fixture digest) |
|---|---|
| config_set_auto_watch | `9f876e3f30b0c2cc4bea5ec2d9dd605ba8594060f1fd5c8d5da34ca898f12b5c` |
| config_get_auto_watch | `2ed27c1421e6928dbe13dbfdb5c59e1045b30341fe7ebe05700006bc5ac572c0` |
| index_repository | `059400beff11d4cfe19a8680881fcea348141472dbfc6daef319891e0fd1e778` |
| list_projects | `5e30ecef011cd6613077865b38c4b9049d79ff16f42e74c3ee5f2ed2a500442c` |
| search_graph | `de493eef550e4066374752809a5e80cda4c2fdb59c96278e5dc82c215ce77b04` |
| index_status | `8696ccf4eb276db090aa7a4d8c4c8dfdeeac17289c8c4cffdc7c90952d6e5bda` |

Cross-validation: the `config_set_auto_watch` raw digest `9f876e3f30b0c2cc…` is byte-identical
to the PRIOR pinned receipt's independently recorded `cfgset.out` sha256-16
(`p2-runtime-receipts.json` env_mode replacement_allowlist) — the deterministic `auto_watch=false`
stdout reproduces across runs and evidence generations.

Registry: six ACTUAL `TestedCompatibilityRecord`s (artifact `996bad5f…435`, measured native
version `codebase-memory-mcp 0.10.8`, protocol `p2-managed-measured-acceptance-v1`, engine
`46ae198fc11cda80e817acbc5f5908d7c2de7032`, measured fixture digest per op) — per-op
`registry.assess` = **compatible ×6**. Honesty: the bound "fixture suite" is the op's own
captured raw output of the same artifact (self-binding); upstream fixture-suite provenance is
future work, stated in every record's `tested_by`.

Executor acceptance rerun on measured records (fresh `accept` namespace, root 23 bytes):
`prepare` ok READY 6.02s marker 0600 → `prepare` again ok 0.0s (idempotent, zero native) →
`sync` ok `status=indexed` 20.06s → queries `search_graph`/`index_status`/`list_projects` all ok
(8.67s/8.64s/8.68s; payload sha256-16 `9fc6d4b5fa6d507a`/`21c5cddeaec5beb5`/`6cd5bf31ea6cbc34`)
→ repo+cache full hashes identical across queries → `trace_path` denied without spawn.

Timebound through the executor (fresh `timebound` generation; NO ctor timeout attr exists —
inspected; module constant patched in-process only, restored): 1.5s deadline mid-daemon-startup →
`status=runtime_refused`, `cancellation_state=cancellation_unknown`, profile **QUARANTINED
persisted**, marker absent, immediate reuse attempt refused (`runtime_refused`, 0.0s);
**no additional daemon observed after timeout — spawning/terminal cause unknown** (the first
pgrep poll was already clean; an exit was never observed, and the owned CLI/daemon may have died
with the deadline process-group kill before any daemon was detectable).

Hygiene: final pgrep delta **none**; binary digest unchanged post-run; quarantined namespace
`m-e504e4eafdf6e04539aab1b2` left frozen (never cleared).
Signal accounting (precise): **zero signals to any user/pre-existing process**; however the
timebound deadline itself delivered an OWNED process-group SIGKILL via the runner's own
`run_command` deadline (`proc._kill_process_group`) — a signal WAS fired by the harness path, it
was never manual.

Wall breakdown (revision 2 — the previously reported 42.61s was the CAPTURE-DISPATCH SUBTOTAL,
not the run total; superseded numbers retained above for traceability):

| phase | recorded wall |
|---|---|
| capture (raw dispatches) | 42.61s |
| acceptance (prepare 6.02 + prepare2 0.0 + sync 20.06 + queries 8.67/8.64/8.68) | 52.07s |
| timebound prepare (deadline kill) | 1.79s |
| **all recorded sum** | **96.47s** |

Scope: sums of recorded wall clocks; every wall includes Python/spawn overhead — this is NOT a
pure native-time breakdown; the 15s timebound observation wait and zero-native stages
(idempotent prepare2, no-reuse, denials) are excluded.

Harness note (evidence-only fix, applied post-run): the 150s budget guard previously covered
ONLY the raw capture dispatches; the guard now wraps all executor/timebound phases in
`p2-managed-acceptance-harness.py`, but that guard fix has NOT been re-validated by a full
native rerun (markfix notvalidatedfull).
Result: **ACCEPTANCE_RESULT: PASS — definitive measured native G2-subset acceptance; no
placeholder records remain.** Still not a P2 promotion decision (release-compat trust policy
remains the maintainer's).

## Handoff to production (not implemented here)

Fix candidates for the runtime owner: shorten namespace dir names (e.g. truncated 16-hex
components) or serve `CBM_RUNTIME_DIR` from a short symlink-free 0700 dir outside the long
namespace while keeping HOME/cache/config inside it. After fix, rerun the pinned harness; do not
treat this document as P2 promotion.
