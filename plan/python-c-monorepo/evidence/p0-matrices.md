# P0 compact matrices — tool-schema inventory, operation compatibility, runtime capability

Ngày: 2026-09-05. Thêm theo review P0. Nguyên tắc conservativeness: **mọi cột "live (payload 996bad5f…)" là UNKNOWN** vì payload chưa từng được thực thi trong đợt này và chưa được gắn với pin lịch sử. Cột "historical" chỉ là receipt từ tài liệu/golden cũ, KHÔNG phải measured fact hiện tại. **[Cập nhật 2026-09-05 sau WP0.3 spike: payload ĐÃ được thực thi trong scratch isolation — live status của từng op ghi ở mục 4; chỉ các op đo được mới chuyển khỏi UNKNOWN.]**

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

Blocker ledger: **G0-B1** payload↔pin identity — **CLOSED** (release-manifest binding, `provenance-upstream.md`); **G0-B2** scratch isolation + lifecycle đo được — **CLOSED** (WP0.3 live spike, scope hẹp: 2 scenario SIGKILL n=1, daemon latency chưa đo — `wp03-live-spike.md`); **G0-B3** git binding thiếu trên 0.10.8 — **MỞ** (live-confirmed: `index_status` output không có `head_sha`/`base_sha`/`branch` — `q2.out`); fail-close `UNVERIFIABLE` là hành vi đúng hiện tại.

## 4. Live results update — WP0.3 spike (2026-09-05, scratch-isolated, `evidence/wp03-live-spike.md`)

| Op | Live result | Bằng chứng |
| :--- | :--- | :--- |
| `--version` probe | **PASS** exit 0, `0.10.8` | `version.out` |
| `index_repository` — scenario A (default) | **PASS** exit 0, nodes=54, edges=119, repo files untouched (diff rỗng), artifact_present=false; cold wall-time real 11.67s incl. temp-daemon startup (không per-phase) | `index2.out`, `index2.err`, repo-files diff |
| `index_repository` — scenario B (`--persistence true`, cùng tool) | **PASS** opt-in artifact: `.codebase-memory/{artifact.json,graph.db.zst}` + `.gitattributes` ghi vào repo | `index3.out` |
| `search_graph` | **PASS** exit 0, bm25 result shape khớp golden | `q1.out` |
| `index_status` | **PASS** exit 0, `status=ready`, nodes/edges khớp; **không có git identity fields** (G0-B3) | `q2.out` |
| `list_projects` | **PASS** exit 0, root_path đúng | `q.out` |
| Flag sai (`--path`) | exit 1 + error message rõ | `index1.err` |
| Daemon lifecycle / cancel | **MEASURED, scope hẹp**: auto_watch default true live (`watcher.watch`); clean exit → stop; SIGKILL startup → `initial_window_expired` (n=1); SIGKILL mid-job → supervisor reap worker signal=15 (n=1), no orphan/partial commit. Latency chưa đo (log không timestamp) | `cbm-daemon.log` (sha256 trong `wp03-spike-receipts.txt`) |
| UI port side effect | Daemon tự thử bind port 9749 mỗi run (18x `ui.unavailable reason=in_use`, passive fail); `--ui=false` chỉ help-confirmed, chưa thực thi | `cbm-daemon.log`, `help.out` |
| 11/15 tool còn lại (query_graph, trace_path, get_code_snippet, get_graph_schema, get_architecture, search_code, delete_project, check_index_coverage, detect_changes, manage_adr, ingest_traces) | **UNKNOWN** — help-listed only, KHÔNG supported claim (`install` và `--version` là CLI command, không thuộc 15 tools) | `help.out` |

Verdict: G0 PASS cho baseline subset = **4/15 native tools** (6 scenarios: version probe [CLI command] + 2 biến thể index_repository + search_graph + index_status + list_projects); các giới hạn trên là yêu cầu bắt buộc cho G2 (managed lifecycle) — G2 CHƯA implement. Platform: Darwin arm64 experimental spike ONLY — không phải supported release, không native CI support claim; CI/storage budget CHƯA duyệt (footprint 1.5 GB clone gồm .git chưa tách source/build).

## 3. Runtime capability report (SOT-side, measured/static hiện tại)

| Capability | Trạng thái | Bằng chứng |
| :--- | :--- | :--- |
| Shell-less one-shot runner, timeout, kill process-group | Có sẵn (SOT) | `src/sot_graph/proc.py` `run_command` ~262 |
| Version compatibility classifier (COMPATIBLE/UNTESTED/INCOMPATIBLE/UNKNOWN) | Có sẵn (SOT) | `src/sot_graph/providers/codebase_memory.py` ~326-343 vs `TESTED_CBM_VERSION` |
| Provider default: command `codebase-memory-mcp` qua PATH, cli integration, timeout 30s, index_policy reuse | Có sẵn | `src/sot_graph/config.py` ~110-124 |
| Subprocess env scrubbing / HOME isolation | **THIẾU** (grep không thấy env_extra/PATH scrub trong adapter) | code hiện tại |
| Golden replay (7 tools) | PASS mocked | `evidence/test-run-mocked-golden.log` exit_code=0 |
| Live capability trên payload đã cài | **MEASURED — 4/15 native tools PASS (6 scenarios); 11 UNKNOWN** | mục 4 + `wp03-live-spike.md` |
| CI runtime (Linux, CBM 0.10.8 từ PyPI) | config tồn tại, pass chưa chứng minh | `ci.yml:191-215` |
