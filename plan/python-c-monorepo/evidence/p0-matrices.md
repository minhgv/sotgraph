# P0 compact matrices — tool-schema inventory, operation compatibility, runtime capability

Ngày: 2026-09-05. Thêm theo review P0. Nguyên tắc conservativeness: **mọi cột "live (payload 996bad5f…)" là UNKNOWN** vì payload chưa từng được thực thi trong đợt này và chưa được gắn với pin lịch sử. Cột "historical" chỉ là receipt từ tài liệu/golden cũ, KHÔNG phải measured fact hiện tại.

Nguồn historical: `docs/adr/0001-federated-cli-provider.md` (source-verified @`010569f`, binary-captured @0.10.8), `tests/fixtures/cbm_golden/_meta.json` (7 captures exit 0, 2026-08-25). Mocked: test suite dùng fake executable (154 passed, `test-run-mocked-golden.log`, exit_code=0).

## 1. Tool-schema inventory (7 tools)

Envelope chung (historical: source-verified + binary-captured): `content[0].type=="text"`, `isError:bool`, `structuredContent?` (chỉ với payload JSON: index_status, list_projects, check_index_coverage), stderr tách riêng, exit 0/1/2, invocation `cli --json <tool> [--flag value | --args-file path]`.

| Tool | Input chính | Output chính | Historical | Live (payload hiện tại) | Blocker |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `list_projects` | — | `projects[].name/root_path`, `total`, paging | binary-captured | UNKNOWN | identity payload chưa đóng (G0-B1) |
| `index_status` | `project` | `nodes`, `edges`, `status`, `parse_partial{}`, `skipped{}`, `not_indexed{}` | binary-captured; **KHÔNG có `head_sha`/`base_sha`/`branch`** trên binary 0.10.8 | UNKNOWN | git snapshot binding không chứng minh được trên 0.10.8 (G0-B3) |
| `search_graph` | `project`; `query?` | text report `total`, `search_mode`, rows, `has_more` | binary-captured | UNKNOWN | (B1) |
| `trace_path` | `function_name`, `direction?` | `callees[]`, `callers[]` totals | binary-captured | UNKNOWN | (B1) |
| `get_architecture` | `project`; `aspects?` | `total_nodes`, `total_edges`, `node_labels[]`, `languages[]`, `packages[]` | binary-captured | UNKNOWN | (B1) |
| `check_index_coverage` | `paths`/`scopes` (max 128/32) | `signal`, `indexed_at`, `paths[].status`, `caveat` | binary-captured; array-via-flag quirk → array passing UNKNOWN ngay cả historical | UNKNOWN | (B1) + array passing cần re-test `--args-file` |
| `detect_changes` | `project` + git context repo cha | `base`, `merge_base`, `changed_files`, `impacted[]` | binary-captured; **environment-dependent** | UNKNOWN | (B1) + phụ thuộc trạng thái repo cha |

## 2. Operation compatibility matrix

| Operation | Historical (0.10.8 golden) | Mocked suite (fake exe) | Live payload 996bad5f… | Ghi chú blocker |
| :--- | :--- | :--- | :--- | :--- |
| Version probe `--version` → `codebase-memory-mcp <ver>` | receipt: exit 0 tại capture (2026-08-25) | PASS (fake exe test) | **UNKNOWN — chưa chạy**; lưu ý: probe chỉ đọc version string, KHÔNG gắn mật mã học commit — cần provenance manifest hoặc gắn nhãn UNKNOWN | G0-B1 |
| Envelope parse (ok/error/bad-args) | binary-captured | PASS (154 tests) | UNKNOWN | — |
| Malformed/truncated/oversized handling | khẳng định trong ADR, golden không cover hết | PASS (fixture/adversarial) | UNKNOWN | P1 phải bổ sung golden cho các lớp này |
| Git snapshot binding | **UNVERIFIABLE trên binary 0.10.8** (không emit git identity) | PASS với fake serve `head_sha` | UNKNOWN | G0-B3: fail-close `UNVERIFIABLE` là hành vi đúng hiện tại |
| Path-level freshness (`check_index_coverage` `hash_status`) | binary-captured, authority cho staleness | PASS | UNKNOWN | không nâng verdict quá `UNVERIFIABLE` |
| Background watcher / daemon lifecycle | không đo | không áp dụng (fake) | **UNKNOWN** — binary strings nói watched projects auto-refresh nền | G0-B2: cấm giả định kill CLI = cancel |
| Env/HOME isolation của subprocess | không có (adapter truyền env đầy đủ — kiểm chứng bằng grep code hiện tại) | không áp dụng | UNKNOWN | G0-B2 prerequisite cho spike |

Blocker ledger: **G0-B1** payload↔pin identity (cần upstream release manifest/provenance; version probe một mình KHÔNG đủ — nếu không có provenance thì gắn nhãn UNKNOWN vĩnh viễn cho đến khi có); **G0-B2** scratch isolation + lifecycle đo được; **G0-B3** git binding thiếu trên 0.10.8 (chờ upstream hoặc design digest riêng).

## 3. Runtime capability report (SOT-side, measured/static hiện tại)

| Capability | Trạng thái | Bằng chứng |
| :--- | :--- | :--- |
| Shell-less one-shot runner, timeout, kill process-group | Có sẵn (SOT) | `src/sot_graph/proc.py` `run_command` ~262 |
| Version compatibility classifier (COMPATIBLE/UNTESTED/INCOMPATIBLE/UNKNOWN) | Có sẵn (SOT) | `src/sot_graph/providers/codebase_memory.py` ~326-343 vs `TESTED_CBM_VERSION` |
| Provider default: command `codebase-memory-mcp` qua PATH, cli integration, timeout 30s, index_policy reuse | Có sẵn | `src/sot_graph/config.py` ~110-124 |
| Subprocess env scrubbing / HOME isolation | **THIẾU** (grep không thấy env_extra/PATH scrub trong adapter) | code hiện tại |
| Golden replay (7 tools) | PASS mocked | `evidence/test-run-mocked-golden.log` exit_code=0 |
| Live capability trên payload đã cài | **NOT MEASURED** | toàn hàng UNKNOWN ở mục 1-2 |
| CI runtime (Linux, CBM 0.10.8 từ PyPI) | config tồn tại, pass chưa chứng minh | `ci.yml:191-215` |
