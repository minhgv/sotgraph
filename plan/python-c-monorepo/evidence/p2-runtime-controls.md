# P2 prerequisite — SOURCE-VERIFIED native runtime controls + live confirmation (2026-09-06)

Provenance: binary `~/.local/bin/codebase-memory-mcp` sha256 `996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435` (= release v0.10.8 content, see `provenance-upstream.md`). Source read at tag **`46ae198fc11cda80e817acbc5f5908d7c2de7032`** (v0.10.8) in clone `/tmp/sot-p0-scratch/codebase-memory-mcp` via `git show 46ae198f:…` / `git grep … 46ae198f` — read-only, no worktree mutation, no branch touched. **Control flags cited below are read from that exact release tree, which is the tree matching the binary content** (not candidate main `3c7427e`). Scratch namespace: **`/tmp/sot-p0-scratch/p2-Dyk1ROQZ`** (mktemp -d; `mkdtemp` not present on macOS — correction to plan wording). Tracked receipts (repo, not /tmp-only): **`p2-runtime-receipts.json`** (exact argv per run, env mode, rc, monotonic timings, hashes), `p2-daemon-log-scenarios-a-c.sanitized.txt` (sha256-16 `c6421dc512a52f14`), `p2-daemon-log-negctrl.sanitized.txt`, `p2-a1-index-stdout.json` (`2ea3c26b1a711af1`), `p2-b1-search-stdout.txt` (`309222431565c34c`).

## 1. Exact controls (source anchors at 46ae198f)

### UI off — the control is a PRE-SEEDED config.json, NOT `--ui=false`
- `src/ui/config.c:111-133` `cbm_ui_config_load`: defaults `CBM_UI_DEFAULT_ENABLED` then **if config file absent AND `CBM_EMBEDDED_FILE_COUNT > 0` → `ui_enabled = true`** (release binary embeds UI assets; stub `src/ui/embedded_stub.c:13` = 0). This is why P0 saw a global bind attempt on port 9749 every run.
- `src/ui/config.h:14` `CBM_UI_DEFAULT_ENABLED false`; `src/ui/config.c:148-160` parses JSON keys `ui_enabled` (bool), `ui_port` (int 1-65535); path = `cbm_resolve_cache_dir()/config.json` (`src/ui/config.c:35-41`) → honors `CBM_CACHE_DIR` (isolated).
- `src/daemon/host.c:469` `if (!desired.ui_enabled)` — HTTP listener never started.
- `--ui=` (`src/main.c:1082-1105` `parse_ui_flags`) reaches the daemon as a runtime UI-config mutation (`src/daemon/application.c:2511-2544` → `cbm_ui_config_save`) — i.e. **after** daemon startup ⇒ bind-then-disable race; NOT a from-startup control. (`cli.c:6757` CONFIG_KEYS shows `ui_enabled` default "false" for the `config` surface only.)
- **Verified control: before first invocation, write `${CBM_CACHE_DIR}/config.json` = `{"ui_enabled": false}`.** Live: 0 `ui.*` lines in daemon log across A/B/C runs; negative control without pre-seed → `ui.unavailable port=9749` + `ui.retry_scheduled` (2 invocations).
- **SAFETY DEVIATION RECORDED (one-time, closed):** the negative-control run executed WITHOUT the UI-off pre-seed and therefore **attempted a bind of the global port 9749** — `ui.unavailable port=9749 reason=in_use` + `ui.retry_scheduled` (passive fail; the user's daemon held the port; no interaction with any user process). This violated the assigned no-global-listener precondition before the live run. Raw daemon log tracked at `p2-daemon-log-negctrl.sanitized.txt`. **The negative control must NEVER be repeated**; the no-pre-seed behavior is already proven twice (P0 spike: 18 passive fails; this run).

### auto_watch false — `config set auto_watch false` (persisted `_config.db`)
- Key `src/cli/cli.h:423`; runtime readers `src/mcp/mcp.c:11495-11513` (`auto_watch_enabled` default **true**; `register_watcher_if_enabled` → skip + log `watcher.register.skipped reason=auto_watch_off`) and `src/daemon/application.c:446`.
- Live: `cli config set auto_watch false` rc=0; `cli config get auto_watch` → `false`; daemon log across all index/query runs: **0** `watcher.watch` project lines (P0 with default true saw `watcher.watch`).

### artifact false — default; never pass `--persistence`
- Only artifact flag on `index_repository` is `--persistence` (default false; `cli index_repository --help`). Live A1/A2: `artifact_present=false`; scratch repo file-manifest unchanged.

### Read-only queries — genuine (graph store)
- B1/B2 (n=2 each × search_graph/index_status/list_projects): rc=0; byte+ns-mtime snapshot of `CBM_CACHE_DIR` diff = **only `logs/cbm-daemon.log` appended**; 7.3 MB project `.db` untouched; repo manifest identical. search_graph returned `src/proc.py 262-376 Function proc.run_command` (sanity hit).

### Cancellation — SOT path is group-SIGKILL, not SIGTERM (source + live)
- `src/sot_graph/proc.py:181-195` `_kill_process_group` = POSIX `os.killpg(..., SIGKILL)` (Windows job object first); deadline check `proc.py:336-344`. **run_command never sends SIGTERM**; binary's SIGTERM grace path (`src/main.c:372-375` handler → `request_shutdown`, sigaction `main.c:1110-1119`) must be driven directly.
- Worker reaper: `index.supervisor.reap outcome=killed exit_code=-1 signal=15` (supervisor SIGTERMs worker).

## 2. Experiments (env modes per `p2-runtime-receipts.json`: **replacement-allowlist** = subprocess `env=` dict of exactly 7 keys — HOME/CBM_CACHE_DIR/CBM_RUNTIME_DIR/XDG_CONFIG_HOME/TMPDIR, PATH=/usr/bin:/bin, TERM=dumb, no inheritance; **inherited** = `run_command(env_extra=…)` which MERGES over `os.environ` (`proc.py:294-296`) — the 6 isolation paths are overridden but all other inherited vars REMAIN; applies to C1 and C1b only. Monotonic timestamps via `time.monotonic()`; daemon log has NO timestamps — latency measured externally by bounded log polling, granularity 0.4-0.5s)

| # | Scenario | Result |
|---|---|---|
| A1/A2 | `cli index_repository --repo-path` (30 py files, 964K), n=2 | rc=0; wall 12.79s / 11.35s (incl temp-daemon startup ~8s); nodes 789, edges 3857; `artifact_present=false`; repo manifest unchanged; 0 ui/watch lines |
| B1/B2 | search_graph + index_status + list_projects, n=2 | rc=0 ×6; 25.45s / 25.46s per triple (~8.5s each = daemon startup floor); graph db + config + repo zero mutation (daemon log append only) |
| C1 | run_command deadline 6s (kill pre-job) | `timed_out=True` at 6.01s; daemon terminal via `lifetime_end reason=initial_window_expired` → `daemon.stop` observed ≤12.7s window (coarse; poll granularity) |
| C1b | run_command deadline 9s (kill mid-job) | `timed_out=True` at 9.00s; `supervisor.reap outcome=killed signal=15` + `worker_cancelled` + `daemon.stop`, **terminal 0.82s after kill** |
| C2 | SIGTERM to own CLI pid only at 9.0s (own process group, launched by us) | CLI rc=-15; same reap/cancel/stop chain, **terminal 0.81s** |
| NEG | fresh cache WITHOUT config.json pre-seed, 2 invocations | `ui.unavailable port=9749` + `ui.retry_scheduled` — pre-seed is necessary |

Namespace safety: user daemon PID 47134 alive pre/post (uptime unchanged); `/private/tmp/cbm-daemon-501` 150 files newest 23:48:33 pre == post; `~/.cache/codebase-memory-mcp` newest Sep 3 pre == post. **Signals fired: SIGKILL ×2 to OWNED process groups (C1, C1b deadline path) and SIGTERM ×1 to OWNED CLI pid (C2) — all recorded in `p2-runtime-receipts.json`. ZERO signals/kills to any preexisting or user-owned process.** No process other than preexisting 47134 remained at any check (`pgrep -f cbm-daemon-internal` after every scenario); every owned scratch process exited on its own or via the recorded owned-group signal above.

## 3. Concrete P2 helper settings (non-speculative)

1. **Env handling — P2 must EXTEND `src/sot_graph/proc.py`, not duplicate the runner and not call subprocess directly.** `run_command(env_extra=…)` only ADDS over `os.environ` (`proc.py:294-296`): it overrides the 6 isolation paths but **cannot scrub inherited vars (credentials, proxy tokens, PATH) — it is NOT a full `env -i` allowlist and must not be claimed as one.** Required change: add an additive, backwards-compatible parameter (e.g. `env_mode="replace"` / `env_allowlist: set[str]`) that passes a constructed dict straight to `subprocess.Popen(env=…)` — reusing the existing process-group/job/reader machinery unchanged.
2. Pre-seed `${CBM_CACHE_DIR}/config.json` = `{"ui_enabled": false}` BEFORE first invocation (UI off from startup; never rely on `--ui=false`). **Never run a no-pre-seed invocation — the global-9749 bind attempt deviation is closed (see §1) and must not be recreated by P2 code paths: the helper must assert the pre-seed file exists before launch.**
3. `config set auto_watch false` once per namespace; assert `config get auto_watch` = `false`.
4. Invoke as `<bin> cli <tool> --flag value`; parse stdout as a plain JSON object (CLI mode ≠ MCP envelope). Validate output non-empty: `--json`-style global flag before subcommand is a **silent no-op rc=0** (0-byte stdout / 145-byte stderr, rc=0 — raw bytes NOT retained, see receipts `SILENT-NOOP`) — wrong invocations can look successful. **Golden framing correction:** the P0 golden `wp03-spike-receipts` envelope (`index2.out`, sha256-16 `ad20bee0866f3e24`, MCP `{"content":[…]}` wrapper) was captured with an argv that is NOT recorded (wp03 used shorthand `cli --json index_repository`) — byte-level golden compare is impossible; P2 golden fixtures must pin the exact argv AND raw bytes (as done in `p2-runtime-receipts.json`) and compare parsed content for the CLI-subcommand form (`a1.out` = plain object).
5. Never pass `--persistence true`; never run `install`; per-invocation wall budget ≥ ~9s daemon startup + tool time; deadline via run_command is SIGKILL-group. Hai tình huống mid-job đã quan sát worker reaped và daemon terminal khoảng 0.8s; tình huống pre-job có cửa sổ tới 12.7s. Đây không phải bảo đảm cancellation tổng quát hoặc bằng chứng atomicity cho reindex; mọi run thiếu xác nhận phải giữ UNKNOWN/quarantine.
6. Sau cancel, log chỉ là bằng chứng hỗ trợ: phải gắn sự kiện mới với đúng run/worker/namespace và xác minh ownership cùng terminal state. Không dùng dòng `daemon.stop` lịch sử làm bằng chứng cho job hiện tại. Nếu chưa có xác nhận đủ trong cửa sổ giới hạn → UNKNOWN, quarantine namespace và không tái sử dụng.

## 4. Limits (honest)

- Sample counts (retained): config set/get n=1; index A n=2; read-only query triple B n=2; cancellation C1 n=1 (pre-job), C1b n=1 (mid-job), C2 n=1 (SIGTERM); silent-no-op observation n=1; negative control n=1 invocation pair — **closed, never to repeat**. All n are small; variance unmeasured. Host macOS arm64 only; index repo = 30 copied Python files (sot-graph `src/sot_graph`, read-only copy) — not a large-repo cancel measurement.
- Raw-bytes gap: the silent-no-op stdout/stderr raw bytes were overwritten by the A1/A2 file writes before retention; only observed facts (0-byte stdout, 145-byte stderr, rc=0, hash of stderr `6b99c03531b1638b`) are recorded. Golden argv for the P0 envelope capture is unknown — byte-level golden compare impossible (see §3.4).
- Env honesty: C1/C1b ran with `run_command(env_extra=…)` = **inherited `os.environ` + 6 overrides**, not a full allowlist; all other runs used a 7-key replacement dict. No credential leak into outputs was observed or expected, but inherited-var exposure is structural until proc.py gains an env-replacement parameter (§3.1).
- Daemon log lacks timestamps; latencies are external monotonic-clock + 0.4-0.5s poll granularity (C1 latency only bounded ≤12.7s).
- SIGINT path, non-daemon mode, and reindex-during-cancel DB consistency were NOT measured (partial-commit no-db evidence remains P0 §5.4 only).
- `watcher.register.skipped` log line expected from source (mcp.c:11510) was not observed in one-shot CLI runs — watcher registration path may be session/MCP-mode-only; absence of `watcher.watch` is the live assert. Untested claim marked [INFERENCE]: MCP session mode behaves identically.
- **No further native runs were performed after the coordinator directive; this document and `p2-runtime-receipts.json` were produced purely from already-captured artifacts and release-tag source reads.**
