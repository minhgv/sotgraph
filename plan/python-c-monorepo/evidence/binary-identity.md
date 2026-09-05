# Binary identity — wrapper vs payload (static analysis, KHÔNG thực thi)

Phân tích ngày 2026-09-05. Binary chưa bao giờ được chạy trong đợt này.

## Đối tượng

- Path: `~/.local/bin/codebase-memory-mcp`
- Loại (`file`): Mach-O 64-bit executable arm64
- Size: 295,457,616 bytes
- SHA-256: `996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435`
- mtime: Aug 25 14:06 (2026) — trùng ngày golden capture (`tests/fixtures/cbm_golden/_meta.json` captured_at 2026-08-25T07:20+07:00); mtime là bằng chứng gián tiếp, không phải proof.

## Phân định wrapper/payload

- **Không phải shell/python wrapper script** — `file(1)` xác nhận Mach-O executable trực tiếp. `strings` không thấy marker PyInstaller (`pyi-`, `_MEIPASS`) trong lượt probe đầu.
- **Payload đơn khối:** chứa chuỗi toolchain Rust/Cargo (`.cargo`, `cargo`, `.cargo/bin/...`) và văn bản prompt MCP nhúng (mô tả `search_graph`, `trace_path`, `index_repository`, `list_projects`...) ⇒ hợp lý là binary native tự chứa (Rust) — [INFERENCE từ static markers].
- **Identity phiên bản (yếu):** đúng **1** occurrence chuỗi `0.10.8` trong toàn binary. Nhất quán với claim 0.10.8 nhưng KHÔNG phải proof — chuỗi có thể nằm trong prompt/dữ liệu khác; và hash chưa đối chiếu được với artifact upstream nào.

## Đối chiếu với claimed pin

| Nguồn | Claim | Loại |
| :--- | :--- | :--- |
| `tests/fixtures/cbm_golden/_meta.json:6-9` | `codebase-memory-mcp 0.10.8`, source `010569fa6ce1bc5d6430f858129243ea1a2e3fd5`, version_probe_exit 0 | historical capture receipt |
| `docs/adr/0001-federated-cli-provider.md:7-8` | source studied @`010569f`, binary exercised 0.10.8 | historical receipt |
| Payload thực tế | sha256 `996bad5f…`, 1× chuỗi `0.10.8` | measured static |
| Kết luận | Payload **không thể xác nhận** (cũng chưa bị bác bỏ) là `0.10.8@010569f` bằng mật mã học. Đóng GAP G0 cần trustworthy provenance binding: release manifest gắn sha256 per-artifact với source commit + build attestation. Version probe chỉ là inspection (đọc version string), không đóng identity. | GAP G0 |

## Tách khỏi candidate `3c7427e`

- Tài liệu gốc ghi CBM baseline commit `3c7427efb740934bf66653413b484118652ce649` — khác `010569f` (commit golden). Không tìm thấy source checkout nào của commit này trên máy ⇒ candidate **chưa có provenance**, mọi fetch/build bị chặn cho tới khi có nguồn an toàn.

## Rủi ro lifecycle quan sát được từ static strings

- Chuỗi nhúng: "watched projects auto-refresh in the background" ⇒ binary có cơ chế watcher nền tiềm năng. Chưa đo được: watcher có spawn khi CLI one-shot không, ghi ra đâu, kill CLI có hủy worker không. → Ghi nhận UNKNOWN, cấm giả định; gate G0 yêu cầu chứng minh hoặc báo unknown an toàn.
