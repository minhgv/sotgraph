# P2 Handoff — Managed lifecycle + provider binding (2026-09-06)

File này tự đủ (self-contained): baseline, code đã implement, bằng chứng test + native thật, blocker, quyết định mở, điều kiện resume. Không cần đọc lại hội thoại. `p0-handoff.md`, `p1-handoff.md` giữ nguyên như lịch sử bất biến; `status.md` là bảng trạng thái sống. **Tóm tắt: code managed lifecycle ĐÃ implement + test mocked (receipt main: 203 passed / exit 0 / 33.25s, 8 file, gồm fault-subset + concurrency — chi tiết mục 3); native measured acceptance PASS scope hẹp trên 1 host; G2 KHÔNG được tuyên bố PASS — thiếu bằng chứng gate (mục 6).**

## 1. Baseline & phạm vi

- Branch `feat/python-c-monorepo-phased` @ `a61a62d` "feat(provider): bind managed execution without circular freshness" (2026-09-06 06:24 +0700), tiếp theo 2 commit mới: `8131295` (managed publication failure) → `8d83f64` (ledger concurrency). Chuỗi từ P1 `01518f2`: `9b20bf2` proc env replacement → `50d117b` P1 docs → `840e7a5` docs runtime controls → `86c97fc` adversarial snapshot tests → `5ca43aa` profile isolation + quarantine → `d96cb4b` managed executor → `cd62f30` fix socket budget + listing wire schema → `338082f` acceptance evidence + quarantine tests → `a61a62d` → `8131295` → `8d83f64`.
- Production thay đổi trong P2 (đã commit bởi main): `src/sot_graph/proc.py` (env replacement), `src/sot_graph/providers/runtime.py` (MỚI, 451 dòng), `src/sot_graph/providers/managed.py` (MỚI, 578 dòng), `src/sot_graph/providers/codebase_memory.py` (+476 dòng). Test mới: `tests/test_proc_environment.py` (167), `tests/test_managed_runtime.py` (509), `tests/test_managed_execution.py` (740), `tests/test_cbm_managed_provider.py` (747), `tests/test_monorepo_snapshot_adversarial.py` (230).
- Phiên viết handoff này: KHÔNG chạy native, KHÔNG sửa production, KHÔNG commit; chỉ sở hữu `p2-handoff.md` (MỚI) + `status.md`. `plan/remaining-work-phased-plan-2026-09-05.md` untracked, KHÔNG thuộc sở hữu, giữ nguyên.
- Binary native đối chứng: `~/.local/bin/codebase-memory-mcp` sha256 `996bad5f…435` = release v0.10.8, engine `46ae198f…032` — digest re-verified pre/post run (acceptance doc mục đầu).

## 2. Code đã implement (phân biệt với product gate)

- **`providers/runtime.py` — profile isolation (commit `5ca43aa`, fix `cd62f30`):** namespace `m-<24hex>` (26 ký tự, `runtime.py:92-93`) sau khi proven root cause socket; preflight `sun_path` ≤103 bytes lúc construct (`runtime.py:153-167`); 5 dir home/cache/runtime/config/tmp; UI-off pre-seed `{"ui_enabled": false}` vào `cache/config.json` TRƯỚC mọi native start (`runtime.py:83-84`); env 7-key replacement (HOME/CBM_CACHE_DIR/CBM_RUNTIME_DIR/XDG_CONFIG_HOME/TMPDIR, PATH=/usr/bin:/bin, TERM=dumb); state machine READY/SYNCING/QUARANTINED **persist qua manifest** — QUARANTINED là vĩnh viễn cho namespace đó (`runtime.py:82`, module doc `:24-50`).
- **`providers/managed.py` — executor (commit `d96cb4b`, fix `cd62f30`):** `ManagedNativeRuntime` với `prepare/query/sync` (`managed.py:140,189,235`); đúng 6 operation: config_set/get_auto_watch + index_repository + 3 query (search_graph/index_status/list_projects) (`managed.py:81-83`); exec lock (`managed.py:84,291`); timeout 30s query / 300s index (`managed.py:95`); **timeout → `runtime_refused` + `cancellation_state="cancellation_unknown"` + quarantine persistent, tái sử dụng bị refuse** (`managed.py:227-232`); sync thất bại → quarantine; receipt không expose native returncode/head; listing wire schema được lọc về đúng shape (`managed.py:432-446`); không inject `project` vào list_projects global-scoped.
- **`proc.py` (commit `9b20bf2`):** tham số env thay-thế (không merge `os.environ`) cho `run_command` — đúng thiết kế `p2-runtime-controls.md` §3.1.
- **`codebase_memory.py` — binding (HEAD `a61a62d`):** `managed_runtime=` param programmatic-only, **KHÔNG wire config/CLI** (`codebase_memory.py:567-572`); protocol `ManagedQueryRuntime` (`:190`); refuse runtime không cùng exact context / repo binding sai lệch (fail-closed, không re-bind); mọi tool ngoài 6 op refuse KHÔNG legacy fallback (`:205-207`); `_ManagedRunShell` returncode luôn None (`:232-241`) → **"without circular freshness"**: native head thiếu/unknown-exit → KHÔNG publish binding, KHÔNG bao giờ fresh; fresh chỉ khi SOT-side head verification khớp (tests `test_native_head_missing_publishes_no_binding_never_fresh`, `test_noop_index_stale_native_head_not_fresh`, `test_matching_native_head_still_publishes_fresh`).

## 3. Bằng chứng test (mocked/contract — đo thật, exit code thật)

- Lệnh của main (nguyên văn, 8 file): `.venv/bin/pytest tests/test_cbm_managed_provider.py tests/test_managed_execution.py tests/test_managed_runtime.py tests/test_cbm_exact_compatibility.py tests/test_cbm_adapter.py tests/test_cbm_snapshot_p2.py tests/test_monorepo_snapshot_adversarial.py tests/test_monorepo_ledger_concurrency.py -q -p no:cacheprovider` → **203 passed, exit 0, 33.25s** (receipt đo thật của main: 7 file trước + `tests/test_monorepo_ledger_concurrency.py` MỚI). Counts: `test_cbm_managed_provider` = 36 (33 tại HEAD `a61a62d` + 3 additions working tree), concurrency = 3. Phiên handoff KHÔNG rerun suite — số liệu = receipt main.
- Ruff scoped (main): `src/sot_graph/providers/codebase_memory.py` + `tests/test_cbm_managed_provider.py` + `tests/test_monorepo_ledger_concurrency.py` = **pass**; gitdiff-check clean; `_UNSET` dưới imports (`test_cbm_managed_provider.py:55`). Còn lại project-wide (pre-existing, ngoài delta): 2× E731 `tests/test_monorepo_snapshot_adversarial.py:212,214` (từ `86c97fc`), 1× F401 `tests/test_cbm_snapshot_p2.py:17`, 1× F841 `src/sot_graph/receipt_explorer.py:445`.
- Toàn bộ test là mocked/fake-runner/real-SQLite-failure-injection — **không test nào gọi binary native thật**. Cancel/quarantine/timeout được test qua timeout cục bộ + fake runner.
- **Review HOÀN TẤT — no blockers** (36 managed + 3 concurrency independently tested). Additions ĐÃ commit: `8131295` (managed publication failure), `8d83f64` (ledger concurrency). Receipt **203 passed REMAINS VALID** sau các commit. SOT health (exit code thật): `sot reconcile` exit 0 (5 updated / 420 unchanged / 0 failed); `sot doctor` exit 0; `sot diff-impact HEAD~2` exit 0 — receipt `583ed0cb4ea4c46003a98af9dd8b0177326c2399295996e793363635668026a6`.

## 4. Bằng chứng native thật (đo trên host, KHÔNG phải suy diễn)

Nguồn: `evidence/p2-managed-acceptance.md` (201 dòng, ngày 2026-09-06) + `evidence/p2-managed-acceptance-receipt.json`, `evidence/p2-managed-fixture-digests.json`, `evidence/p2-managed-registry-records.json`, `evidence/p2-managed-minprepare-receipt.json`, harness `evidence/p2-managed-acceptance-harness.py`.

1. **Chạy đầu: G2 BLOCKER proven** — managed prepare `runtime_refused` + QUARANTINED sau 0.30s. Root cause proven (không inferred): rendezvous UNIX socket path 163 ký tự > `sun_path` 104 bytes (macOS) do namespace cũ 81 ký tự (`ipc.c:869-935`, `main.c:2502-2515` tại 46ae198f); control probe rc=0 khi CHỈ rút ngắn rendezvous parent → binary healthy, blocker là độ dài path.
2. **Fix trên disk (`cd62f30`):** namespace `m-<24hex>`, ctor preflight socket bytes, bỏ inject `project` vào list_projects. POST-FIX RETRY: PASSED (provisional, registry placeholder).
3. **DEFINITIVE MEASURED ACCEPTANCE — PASS scope hẹp:** 6/6 op đo được raw fixture digest (sha256 trên stdout byte-exact; cross-validate `config_set_auto_watch` khớp digest pinned trước đó); registry 6 `TestedCompatibilityRecord` = compatible ×6 (protocol `p2-managed-measured-acceptance-v1`, artifact `996bad5f…`, engine `46ae198f…`); executor: prepare ok READY 6.02s → prepare2 0.0s idempotent zero-native → sync `indexed` 20.06s → 3 query ok ~8.7s → repo+cache full-hash bất biến xuyên query → `trace_path` denied không spawn. Wall sum ghi nhận 96.47s (kèm overhead Python/spawn, không phải pure native time).
4. **Timeout qua executor (n=1):** deadline 1.5s giữa daemon startup → `runtime_refused` + `cancellation_state=cancellation_unknown` + **QUARANTINED persist** + refuse reuse ngay (0.0s). **Daemon terminal sau timeout: UNKNOWN** — không quan sát được daemon thêm nào (pgrep poll đầu đã sạch; exit chưa từng được quan sát; CLI/daemon có thể chết cùng process-group kill). Harness đã phát đúng 1 SIGKILL vào process-group CỦA MÌNH qua `proc._kill_process_group` — có ghi nhận, không bao giờ manual.
5. **Hygiene:** pgrep delta 0; binary digest không đổi; namespace QUARANTINED để frozen, không clear.
6. **Controls nền (`evidence/p2-runtime-controls.md`, source-verified tại 46ae198f + live n nhỏ):** UI off = pre-seed config (KHÔNG phải `--ui=false`); auto_watch false persist; artifact default false; query read-only zero mutation (chỉ daemon log append); cancel SOT = group-SIGKILL, không SIGTERM (`proc.py:181-195`); C1/C1b/C2 n=1 mỗi scenario; negative control no-pre-seed **đã đóng, không bao giờ lặp lại** (deviation port 9749 một lần, closed).
7. Harness note trung thực: budget-guard fix hậu-run **chưa được re-validate bằng native rerun đầy đủ** (`notvalidatedfull` trong acceptance doc).

## 5. Điểm yếu/bất đối xứng bằng chứng native (chính xác, không phóng đại)

- **1 host duy nhất: macOS arm64** (máy dev private scratch). Không platform thứ hai, không native CI.
- Native acceptance đo ở working-tree thời `cd62f30` (doc pin "HEAD `d96cb4b`"); **HEAD hiện tại `a61a62d` (binding layer codebase_memory.py +476 dòng) CHƯA từng chạy native thật** — chỉ mocked tests. Đây là "native head unavailable / no fresh inference" tại HEAD.
- Timeout→cancel: xác nhận an toàn dạng **unknown** (đúng yêu cầu gate "confirmed hoặc báo unknown an toàn") nhưng n=1, và chỉ pre/early-startup; mid-job cancel qua executor trên profile WORKING chưa đo (mid-job đo ngoài executor ở controls C1b/C2, n=1).
- Fixture registry = **self-binding** (digest của chính output op đó, cùng artifact); provenance fixture-suite upstream = future work, ghi trong từng record `tested_by`. Trust policy release-compat = của maintainer.
- Ghi số daemon exit "cause unknown" ở cả retry lẫn definitive → vế "no orphan writer báo success" mới có hygiene pgrep, chưa có xác nhận terminal daemon.

## 6. Trạng thái gate G2 — KHÔNG PROMOTE

Yêu cầu G2 nguyên văn (`execution-plan.md` §3): query không đổi source/index generation/ledger; không đụng global daemon/config; cancellation confirm HOẶC unknown an toàn; no orphan writer báo success.

- Đã có bằng chứng (scope hẹp): query read-only zero-mutation (full-hash invariant); isolation global (pgrep pre/post, global rendezvous untouched, user daemon không đụng); timeout → `cancellation_unknown` + quarantine persistent — **gate CHO PHÉP unknown an toàn; xác nhận terminal daemon KHÔNG bắt buộc**.
- **2 gap G2 còn lại (chỉ 2, không bịa thêm):**
  1. **Live acceptance của provider hiện tại:** measured native acceptance là executor-layer, TRƯỚC binding layer — cần 1 lần chạy live qua provider tại tip committed (`8131295`/`8d83f64`).
  2. **Isolation/orphan unsafe-success proof theo định nghĩa gate:** bằng chứng có định nghĩa rằng không orphan writer nào báo success (hiện mới có hygiene pgrep delta 0).
- **Hạn chế giai đoạn sau — KHÔNG phải blocker G2:** 1 host macOS arm64 (đủ nếu khai báo scope host trung thực); public CLI/installer = phạm vi **P4/P5**, không phải điều kiện G2 (programmatic-only là đúng scope hiện tại); policy trust registry (self-binding) = quyết định maintainer về sau; G0-B3 + 11/15 native tool UNKNOWN = P3/later; SIGINT/non-daemon = việc khác, không thuộc G2.
- Kết luận trung thực: **P2 code implemented + measured native subset PASS (1 host, executor layer); G2 = CHƯA PASS (đúng 2 gap trên), KHÔNG promote; P3 KHÔNG bắt đầu theo chuỗi promotion.**

## 7. Quyết định mở (cho maintainer/phiên sau)

1. Đóng đúng 2 gap G2 (mục 6): live acceptance qua provider tại tip `8d83f64` + isolation/orphan unsafe-success proof; khai báo scope host trung thực (1 host đủ nếu honest).
2. Rerun `evidence/p2-managed-acceptance-harness.py` (pinned `--binary`/`--root`) tại tip mới khi được phép chạy native.
3. Surface công khai (CLI/installer) giữ hẹn P4/P5 — không thuộc điều kiện G2.
4. Fix lint tồn: 2× E731 adversarial test + F401 `uuid` (không chạm production nếu làm).

## 8. Điều kiện resume

- Bắt đầu từ bằng chứng trên disk: `status.md`, file này, `evidence/p2-managed-acceptance.md` + receipts, tests chạy được (receipt main: 203 passed / exit 0 / 33.25s — mục 3). Không promote theo tên; gate chỉ pass khi có receipt thật.
- Nếu tiếp G2: owner A = native rerun tại HEAD + đa host/terminal-daemon evidence; owner B = policy trust registry; không hai owner cùng file; native chỉ trong scratch namespace 7-key env + UI-off pre-seed, không bao giờ lặp negative control no-pre-seed.
- Nếu sang P3 (sau khi G2 được tuyên bố đúng thủ tục): snapshot/ledger integrity theo `execution-plan.md` §4; adversarial suite nền đã có `tests/test_monorepo_snapshot_adversarial.py` (unborn head, linked worktree, mutation giữa captures, failed-sync supersede, binding rollback).
- Ràng buộc bất biến: không đổi `p0-handoff.md`/`p1-handoff.md`; golden `tests/fixtures/cbm_golden` không đổi; tổng ước lượng 26–47 engineer-days giữ nguyên từ tài liệu gốc. (Commit có authorization rõ của user — không còn cấm commit.)
