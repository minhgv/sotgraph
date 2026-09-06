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
