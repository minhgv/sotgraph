# SOT-Graph × CBM Sub-domain — Master Plan (BINDING) — 2026-09-06

> **Status: BINDING.** Tài liệu này chốt lại mục tiêu **không thay đổi** của owner và
> **supersede mọi điều khoản mâu thuẫn** trong `python-c-monorepo-architecture-plan-2026-09-05.md`
> (cụ thể: mục 3.5.7 câu "Artifact retrieval chỉ ở explicit install/update" và P4 "managed
> install explicit, không download-on-query"). Các điều khoản KHÔNG mâu thuẫn — đặc biệt
> toàn bộ contract SOT-only agent surface (mục 3.4, GS-SURFACE 9.1) — vẫn nguyên hiệu lực.

## 1. Mục tiêu bất biến (nguyên văn owner, 2026-09-06)

1. **CBM (codebase-memory) là một sub-domain** của sotgraph: lớp bóc tách dữ liệu
   (extraction layer), ẩn hoàn toàn với người dùng cuối.
2. **Khi cài đặt sotgraph → tự động tải và cài CBM** như một thành phần (engine artifact)
   và tiêu thụ qua **MCP** (stdio, nội bộ). Không thao tác thủ công của admin cho đường mặc định.
3. **CLI/MCP của sotgraph không có sự xuất hiện của codebase-memory** ở bề mặt vận hành
   (help, lệnh, hướng dẫn). Provenance/evidence vẫn được phép nêu nguồn (giữ nguyên mục 3.4).
4. **Sotgraph là lớp bảo chứng tin cậy** (trust verdicts, receipts, compatibility gates)
   và **chủ sở hữu xử lý dữ liệu + điều khiển quy trình** (orchestration, routing, persistence).
   CBM chỉ bóc tách; mọi evidence của CBM vẫn là *candidate/supplemental*, không bao giờ
   tự lên SUPPORTED nếu chưa qua verify của sotgraph.

## 2. Quyết định kiến trúc ràng buộc

| ID | Quyết định |
| :--- | :--- |
| D1 — Trusted bootstrap | sotgraph ship **pin manifest** (`sot_graph/providers/engine_pins.json`): source URL + sha256 + engine_commit + platform cho từng bản release engine. Bootstrap = fetch từ nguồn đã pin → verify sha256 + size cap → stage qua `ArtifactStore.import_artifact` (đường verify sẵn có) → `promote`. **Fail-closed**: sai digest/platform/mạng → từ chối, không bao giờ chạy binary chưa verify. Không download-on-query: bootstrap chỉ chạy lúc install/setup/lệnh tường minh, không chạy giữa query. |
| D2 — CBM qua MCP (nội bộ) | sotgraph spawn engine binary ở chế độ MCP stdio và tiêu thụ qua JSON-RPC (client MCP tối tiểu trong `providers/engine_mcp.py`). MCP là transport nội bộ sotgraph↔engine; **không bao giờ** đăng ký server CBM vào harness nào (giữ SUR-01/02/12). Chế độ FEDERATED_CLI hiện có giữ làm đường fallback có compatibility evidence. |
| D3 — Default store | Engine store mặc định ở `~/.sotgraph/engine-store` (0700, ngoài mọi repo), tự tạo khi bootstrap. Vẫn cho override `--store` cho admin. |
| D4 — Auto at install | `sotgraph setup` và lệnh `engine bootstrap` kích hoạt D1. Pip-install KHÔNG chạy network hook trong build; lần cấu hình đầu tiên (setup/first engine op) mới fetch — đây vẫn thỏa "cài đặt tự động tải" vì không cần thao tác thủ công ngoài việc cài sotgraph. Env `SOT_ENGINE_BOOTSTRAP=off` tắt auto. |
| D5 — Rename user-visible | dist name `sot-graph` → `sotgraph`; tiêu đề/tài liệu; chuỗi hướng dẫn `pip install sotgraph[...]`. Import package `sot_graph` giữ nguyên (internal, đổi sẽ phá compat toàn diện, không lợi ích user-facing — ghi nhận là việc có thể làm sau). |
| D6 — Provenance trung thực | Không xóa tên engine trong evidence/receipts/diagnostics (giữ mục 3.4:171). Bề mặt vận hành sạch, provenance rõ — không giả vờ mọi kết quả do builtin tạo. |

## 3. Phân định trách nhiệm (không đổi)

| Concern | Owner |
| :--- | :--- |
| Extraction: parse AST, semantic candidates, coverage hints | **CBM** (subprocess MCP/CLI, artifact đã verify) |
| Processing: join identity, normalize, rank, persistence SQLite | **sotgraph** |
| Orchestration: routing builtin/external, capability negotiation, lifecycle | **sotgraph** (`assurance/`) |
| Trust: verdicts, compatibility gates, snapshot binding, receipts | **sotgraph** (`assurance/`, `providers/compatibility.py`) |
| Agent surface: CLI `sotgraph`, MCP `sot_*` | **sotgraph only** |

## 4. Giai đoạn

- **P0 (2026-09-06, lượt này):** sửa tài liệu mâu thuẫn; rename D5; module bootstrap D1–D4
  (`providers/bootstrap.py` + `engine bootstrap` + hook vào `setup`); MCP client D2
  (`providers/engine_mcp.py` + `engine mcp-probe`); tests không cần mạng (file:// + stub MCP
  server); build binary cbm thật, publish release private `sotgraph-cbm`, pin digest thật.
- **P1 (kế tiếp):** bật đường MCP làm transport mặc định cho các op có compatibility evidence;
  platform matrix (linux-arm64/x86_64); đối chiếu G-gates (G4/G5/G7 đang BLOCKED).
- **P2:** hiệu năng G6 (managed p50 26.7s vs builtin 0.104s — phải đo lại trên transport MCP
  và tối ưu bootstrap/index); SG-202 (đang 80.95% < sàn 95%); SG-201 human study.
- **P3:** phát hành công khai: public release engine hoặc cơ chế token cho end-user; hoàn tất
  rename sâu nếu owner yêu cầu.

## 5. Chấp nhận (acceptance) P0

1. `pip install -e .` (dist `sotgraph`) xong, `sotgraph setup` trên máy có mạng tự tải engine
   theo pin, verify sha256, promote — không một bước thủ công nào nhắc đến codebase-memory.
2. `sotgraph engine bootstrap --source <file>` hoạt động offline (dev/CI).
3. `sotgraph engine mcp-probe` bắt tay MCP stdio với engine đã promote và liệt kê được tools.
4. Toàn bộ test suite pass; không test nào cần mạng.
5. Grep bề mặt CLI (`--help` mọi lệnh) không chứa "codebase-memory".

## 6. Kết quả nghiệm thu P0 (ghi nhận 2026-09-06, cuối phiên)

- **#1 ĐẠT:** private release `engine-v2026.09.06` (asset `codebase-memory-mcp-darwin-arm64`,
  296 MB) đã publish trên `minhgv/sotgraph-cbm`; fetch API-asset + verify sha256 + promote qua
  ArtifactStore chạy thật thành công (receipt `status: promoted`). Bootstrap từ binary local
  cùng digest: `status: promoted` tức thời. Token qua `SOT_ENGINE_TOKEN`/`GH_TOKEN`.
- **#2 ĐẠT:** `engine bootstrap --source` (local path/file://) đã verify + promote; đầy đủ
  test phủ (fail-closed khi sai digest, sai platform; tự dọn temp).
- **#3 ĐẠT MỘT PHẦN — giới hạn trung thực:** client MCP stdio pass toàn bộ test với stub
  (handshake, tools/list, tools/call, malformed, fail-closed). Với binary thật: spawn sạch,
  đường lỗi được kiểm soát (bounded stderr tail, không lộ hướng dẫn vận hành engine). Tuy
  nhiên **bắt tay dương tính chưa đạt trên máy này** vì engine áp dụng admission exact-build:
  daemon CBM 0.10.8 (build `996bad5…`) của người dùng đang active nên binary pin (submodule
  HEAD, version `dev`, build `8953ad08…`) từ chối khởi động MCP ("conflicting CBM process").
  Không đụng tiến trình của người dùng (SUR-08). `CBM_CACHE_DIR` cách ly không hiệu lực vì
  engine canonicalize về per-account path.
- **#4 ĐẠT:** full suite **2223 passed / 5 skipped / 0 failed** (197.6s); `tests/conftest.py`
  đặt `SOT_ENGINE_BOOTSTRAP=off` toàn suite (hermetic); 15 test mới cho bootstrap + MCP.
- **#5 ĐẠT:** quét `--help` 36 lệnh top-level + mọi subcommand: 0 occurrence "codebase".
  Đã xóa 2 điểm leak help cũ (`cli.py` providers sync, `admin.py` docstring).

## 7. Mở P1 (theo thứ tự ưu tiên)

1. **Engine version coexistence:** chiến lược pin khớp phiên bản daemon đang chạy (build
   0.10.8/`996bad5` — cần tag/build nguồn trong mirror) HOẶC cơ chế namespace theo account
   cho managed engine; kèm decision upstream-vs-mirror provenance.
2. Bật MCP làm transport mặc định cho các op có compatibility evidence (hiện FEDERATED_CLI
   vẫn là đường có evidence; MCP probe là bước 1).
3. Platform matrix (linux-arm64/x86_64), CI build + release tự động theo tag.
4. Rename sâu P1: adapters MCP key `sot-graph` → `sotgraph` kèm migration chống duplicate
   (SUR-08), `~/.config/sot-graph/managed.json` path, hook marker, skill dir names.
5. G-gates: G4/G5/G7 (BLOCKED), G6 hiệu năng (managed p50 26.7s), SG-202 (<95%), SG-201
   human study.

## 8. Kết quả P1 (ghi nhận 2026-09-06, cuối phiên P1)

- **#1 (§7.1) Engine version coexistence — ĐẠT, 0 dòng C sửa.** Engine đã có sẵn
  `CBM_RUNTIME_DIR` (bootstrap.c:228) được honor trên cả MCP client role (endpoint tự
  phân giải override khi `runtime_parent==NULL`; validate fail-closed tại ipc.c:869-912);
  engine test contract tồn tại sẵn (`daemon_bootstrap_runtime_dir_env_relocates_rendezvous`,
  suite daemon_bootstrap 25/25 PASS). Provenance decision: pin = private mirror
  `minhgv/sotgraph-cbm` theo commit (mirror chưa có tag 0.10.8; upstream không được tham
  chiếu). sotgraph inject namespace env tại mọi điểm spawn (`bootstrap.engine_runtime_env`;
  `EngineMcpClient(store_root=…)`; FEDERATED_CLI `env_extra`).
  **Bài học sun_path (bug bắt từ E2E thật):** rendezvous socket
  `<parent>/cbm-daemon-<uid>/cbm-<16hex>.sock` bị cap 104 bytes → parent tối đa
  ~65 bytes; layout đầu `<store>/runtime/<name>` tràn (105 bytes trên máy này) → engine
  tạo được dir nhưng chết ở `unix_address_set` không kèm diagnostic. Fix: runtime namespace
  tại `<sys-tmp>/sotgraph-engine-<uid>` (0700) — đúng pattern root+sticky mà security walk
  của engine chấp nhận; cache giữ `<store>/cache/<name>` (D3, cold by design).
- **#2 (§7.2) MCP default transport — ĐẠT (code + stub tests).** `SOT_ENGINE_TRANSPORT`
  = `auto` (default) | `mcp` (strict, refuse không fallback) | `cli` (hành vi cũ); giá
  trị lạ refuse controlled. `auto`: managed read (`search_graph`/`index_status`/
  `list_projects` — mapping identity với tools registry thật của engine) thử MCP stdio
  trước, BẤT KỲ lỗi nào → fallback FEDERATED_CLI nguyên vẹn + ghi reason; provenance
  trung thực (D6): `ManagedResult.transport`/`fallback_reason` + receipt
  `transport=mcp|cli (fallback: …)`. `usages` do orchestrator refuse trước transport
  (`unsupported_operation`, có từ trước). Per-op spawn + close; pooling là P2.
- **#3 (§7.3) Platform matrix CI — ĐÃ AUTHOR, chưa vận hành.** Thêm
  `engines/codebase-memory-mcp/.github/workflows/engine-release.yml` (trigger tag
  `engine-v*`; preflight fail-closed refuse tag malformed; build matrix native runners
  macos-14/ubuntu-latest/ubuntu-24.04-arm; release private kèm
  `codebase-memory-mcp-<platform>` ×3 + checksums + `engine-pins.json` sinh tự động đúng
  schema pin manifest) + `docs/RELEASING-ENGINE.md` (checklist owner: commit+push submodule,
  enable Actions, push tag, copy pins). YAML parse OK; chưa actionlint; chưa push/tag.
- **#4 (§7.4) Rename sâu P1 — ĐẠT.** MCP server key `sot-graph`→`sotgraph` mọi harness
  kèm migration chống duplicate qua `adapters/migration.py` (chỉ xóa legacy khi chứng minh
  được là của sotgraph — entry chứa `sot_graph`/`sotgraph`; foreign kept nguyên vẹn);
  skill dirs → `skills/sotgraph` (legacy xóa chỉ khi byte-identical template); HOOK_MARKER
  mới + nhận diện marker cũ migrate in-place không đúp; `~/.config/sotgraph/managed.json`
  (read-fallback legacy tại account-home thật + migrate-on-write; không bao giờ xóa file
  legacy). +9 test migration; dogfood surfaces repo đã chuyển (.zcode/.omp/.opencode/.gemini).
  Sót có chủ đích: docstrings/plan-file refs, regex phát hiện legacy
  (check_repository_identity), brand prose, `BEGIN/END SOT-GRAPH` content markers.
  Vụt sót P0 đã đắp: `scripts/ci_smoke.py` + `scripts/check_surface_packaging.py` còn
  tra cứu dist `sot-graph` → đã đổi `sotgraph`.
- **#5 (§7.5) G-gates — KHÔNG THỰC HIỆN** (BLOCKED như ghi tại §7.5); G6 giờ đo được trên
  transport MCP thật (đã khả dụng).
- **E2E thật (trên máy owner, daemon CBM cá nhân 0.10.8 vẫn đang chạy):**
  `sotgraph engine mcp-probe` → **status ok**, handshake `2024-11-05`, engine liệt kê 15
  tools (index_repository, search_graph, query_graph, trace_path, get_code_snippet,
  get_graph_schema, get_architecture, search_code, list_projects, delete_project,
  index_status, check_index_coverage, detect_changes, manage_adr, ingest_traces).
  P0 §6.#3 ("bắt tay dương tính chưa đạt") → **ĐẠT**.
- **Giới hạn trung thực — môi trường agent shell:** exec script shebang trực tiếp bị treo
  trong sandbox agent (binary + explicit-interpreter bình thường; chứng minh bằng stash:
  `test_resolution_cached_per_repo_root` fail y hệt trên pristine HEAD sau đúng 30s
  budget). `test_probe_ok` nay skip-có-lý-do khi shebang exec không khả dụng. Các fail
  nhóm `make_exe`/PATH-fake shebang trong môi trường agent là environmental; chuẩn đối
  chiếu là full suite trong terminal user (P0: 2223 pass).
- **Test cuối phiên (kết thúc P1, có shebang guard):** full suite **2143 passed /
  114 skipped / 0 failed** trong **159s** (trước guard: 2168/81/6 mất 54:55). Diễn biến
  nghiệm thu: (1) phát hiện 81 fail = **77 environmental** (shebang/PATH-fake spawn treo
  trong sandbox agent — stash-verify trực tiếp 18 đại diện fail y hệt trên pristine HEAD)
  + **4 regression thật** (`test_completion_surface_provider.py` SUR-02/10/11:
  `_mcp_dispatch` chỉ bắt `EngineMcpError` nên exception ngoài hợp đồng client — xuất hiện
  khi surface test intercept `subprocess.Popen` — crash dispatch thành
  `policy_unsatisfiable`, vi phạm cam kết "fallback mọi lỗi MCP"). (2) **Fix regression**:
  `_mcp_dispatch` bắt thêm exception ngoài hợp đồng với reason
  `engine MCP transport contract breach: <type>`, close() best-effort; test mới
  `test_auto_transport_contract_breach_falls_back_to_cli`; 12/12 pass sau fix. (3) **Chuyển
  77 environmental thành skip-có-lý-do**: `tests/conftest.py` thêm detect differential
  `shebang_exec_available()` (chỉ kết luận False khi direct exec hỏng mà explicit
  interpreter chạy được — tránh nhầm môi trường chỉ chậm) + `require_shebang_exec()`;
  10 file test dùng fake shebang engine gọi guard. Kết quả: agent shell 0 fail, 114 skip
  (77 environmental + Windows precedent + side-effect cùng helper); runtime toàn suite
  giảm 54:55 → 2:39 do không còn đốt budget 30s/test treo. Probe MCP thật sau guard vẫn
  `status: ok` (protocol 2024-11-05, 15 tools). **Khuyến nghị owner: chạy lại full suite
  trong terminal user làm chuẩn nghiệm thu cuối** (môi trường shebang lành mạnh kỳ vọng
  ~2257 collected, 0 skipped-environmental).
