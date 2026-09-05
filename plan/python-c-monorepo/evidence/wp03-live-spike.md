# WP0.3 — Live spike receipt (2026-09-05, scratch-isolated, binary v0.10.8 identity-closed)

Binary: `~/.local/bin/codebase-memory-mcp` (sha256 `996bad5f…`, identity-closed = release v0.10.8 content — `provenance-upstream.md` mục 3). Scratch: `/tmp/sot-p0-scratch/spike/{home,runtime,tmp,repo}`. Isolation env cho MỌI invocation: `env -i HOME=$S/home CBM_CACHE_DIR=$S/home/.cache/codebase-memory-mcp CBM_RUNTIME_DIR=$S/runtime XDG_CONFIG_HOME=$S/home/.config TMPDIR=$S/tmp PATH=/usr/bin:/bin TERM=dumb`. Pre/post assert files: `/tmp/sot-p0-scratch/prestate.txt`, `poststate.txt` (mirror ở mục 6).

## 1. Version probe (stateless role)

- `codebase-memory-mcp --version` → stdout `codebase-memory-mcp 0.10.8`, **exit 0**. Log `$S/version.out`. Khớp golden `_meta.json` `version_probe_exit: 0`.

## 2. CLI surface

- `--help` → 15 tools: index_repository, search_graph, query_graph, trace_path, get_code_snippet, get_graph_schema, get_architecture, search_code, list_projects, delete_project, index_status, check_index_coverage, detect_changes, manage_adr, ingest_traces. Log `$S/help.out`. **Đây CHỈ là help surface — KHÔNG phải "15 tools supported".** Live-verified = **4/15 native tools** (index_repository, search_graph, index_status, list_projects); **11/15 tool còn lại = UNKNOWN** (limit ledger cho G2). (`--version` probe và `install` là CLI command, không thuộc 15 tools.)
- Help cũng ghi UI options: `--ui=true|false` "(persisted)", `--port=N` default 9749 — tên flag có thật trên help, nhưng **chưa hề chạy thử** (disabling UI chưa được verify bằng thực thi).
- **`install` sẽ đăng ký tới 43 client surfaces** (Claude Code, Codex, …) — cấm tuyệt đối trong managed mode (GS-SURFACE).
- Daemon tự log `build=996bad5f…` (`version_cohort.claimed_unheld`) = daemon tự-hash executable. Đây là **self-attestation**: chứng minh được identity CHỈ khi đối chiếu externally với release manifest (đã làm — `provenance-upstream.md`); **không tự chứng minh tính đúng đắn (correctness) của binary** — hành vi phải đo riêng như các mục dưới.

## 3. Index (scratch repo 10 file C/Python)

- `cli --json index_repository --repo-path $S/repo` → **exit 0**, `status=indexed`, nodes=54, edges=119, `artifact_present=false`, slug `private-tmp-sot-p0-scratch-spike-repo`. Log `$S/index2.out`. Timing đo được (time -p trong `$S/index2.err`): **successful cold index = real 11.67s wall, gồm cả temp-daemon startup** — KHÔNG có breakdown theo phase. (Lưu ý: `real 2.89s` trước đây bị trích sai — đó là lần chạy SAI flag `$S/index1.err`, không phải timing của index.)
- **Repo KHÔNG bị đụng mặc định**: `diff repo-files-before after` = rỗng; không `.codebase-memory/`, không `.gitattributes`.
- Flag đúng là `--repo-path` (không phải `--path`); sai flag → exit 1 + error message rõ (`unknown flag --path for this tool`).

## 4. Artifact side effect (chỉ khi opt-in)

- `--persistence true` → **`artifact_present=true`**; tạo `$S/repo/.codebase-memory/{artifact.json,graph.db.zst}` + **`.gitattributes`** trong repo. ⇒ plan đã đúng: managed SOT invocation KHÔNG BAO GIỜ pass `--persistence true` trừ khi user opt-in explicit.

## 5. Lifecycle / cancellation (đo thật — G0 assumption removal)

1. **One-shot CLI DÙNG daemon**: log daemon có `watcher.watch project=…` ngay lần index đầu — và `auto_watch` default **true** được xác nhận live.
2. **Clean exit:** CLI kết thúc bình thường → daemon log: `daemon.runtime_stopping reason=last_committed_client_disconnected` → `watcher.unwatch` → `daemon.lifetime_end reason=runtime_exited` → `daemon.stop`. Không còn daemon nào ở scratch namespace (pgrep xác nhận).
3. **SIGKILL CLI lúc startup (t+4s):** daemon (PID 53139) SỐNG SÓT sau kill (kill CLI ≠ cancel ngay), nhưng tự kết thúc khi `initial window` không có client nào commit: `daemon.lifetime_end reason=initial_window_expired` → `daemon.stop`. Không orphan writer, không db committed.
4. **SIGKILL CLI GIỮA JOB (t+12s, job in-flight):** daemon (PID 53805) phát hiện client chết qua `daemon.connection_end received=-1 frame_type=none` → `daemon.runtime_stopping reason=last_committed_client_disconnected` → **`index.supervisor.reap outcome=killed exit_code=-1 signal=15`** → `index.supervisor.worker_cancelled outcome=killed` → `watcher.stop` → `daemon.stop`. **Không tạo db** cho repo đang index (0 byte partial commit).
   **Verdict G0 (scope hẹp):** "kill CLI = cancel worker" là SAI nếu hiểu theo nghĩa cơ chế (kill không trực tiếp cancel), nhưng ĐÚNG theo nghĩa kết quả trong **2 scenario đã đo (mỗi scenario n=1, host macOS arm64)**: SIGKILL lúc startup → daemon tự kết thúc (`initial_window_expired`); SIGKILL giữa job → supervisor phát hiện client chết và tự cancel worker (SIGTERM, `supervisor.reap outcome=killed signal=15`), không orphan writer, không commit dở. **KHÔNG phải cam kết cancellation tổng quát**: SIGTERM/timeout từ phía SOT, đường không-daemon, và repeat-run variance CHƯA đo. Latency tự-kết-thúc của daemon **chưa được đo** — `cbm-daemon.log` không có timestamp (claim cũ "≤5s đã đo" đã bị RÚT BỎ; đo lại có instrument ở G2).
5. **UI port global side effect:** daemon tự thử bind HTTP UI **port 9749** mỗi invocation — log `ui.unavailable port=9749 reason=in_use` (18 lần, passive fail do daemon thật của user đang giữ port; KHÔNG có tương tác nào với daemon user). Port là tài nguyên máy toàn cục ⇒ managed mode bắt buộc tắt UI; tên flag `--ui=false` chỉ mới xác nhận trên help (persisted), **chưa chạy thử** — verify thực tế ở G2.

## 6. Namespace asserts (pre → post)

- User daemon thật **PID 47134 còn sống, uptime 3d5h** — không bị đụng.
- `/private/tmp/cbm-daemon-501/` (rendezvous thật): 150 file, newest mtime Sep 3 15:09 — **không thay đổi** (spike chạy với `CBM_RUNTIME_DIR` scratch nên không chạm).
- `~/.cache/codebase-memory-mcp/`: newest entries Sep 3 — không thay đổi. `~/Library/Caches/codebase-memory-mcp/`: không tồn tại trước lẫn sau.
- Sau spike: duy nhất 1 process `cbm-daemon-internal` trên máy = 47134 (của user). Scratch sạch.

## 7. Query ops (read-only)

- `search_graph --project <slug> --query f1` → exit 0, bm25 result (`qn,label,file,lines,rank`).
- `index_status --project <slug>` → exit 0, `status=ready`, nodes/edges khớp schema golden.
- `list_projects` → exit 0, project scratch liệt kê đúng root_path.
- Output shape khớp golden fixtures (schema không đổi giữa binary installed và golden capture).

## 8. Kết luận gate

- Supported binary: installed `996bad5f…` (= v0.10.8 release content, darwin-arm64). **Supported native tools = baseline subset đã live-verify: 4/15 tools (index_repository, search_graph, index_status, list_projects), đo qua 6 scenarios: version probe (CLI command, không phải tool), index default (không đụng repo), index `--persistence true` (opt-in artifact — cùng tool index_repository), search_graph, index_status, list_projects; envelope shape khớp golden.** 11/15 tool còn lại trong help = **UNKNOWN** (chưa chạy — không được tuyên bố supported). Cancel = client-death supervision, đo được CHỈ trong 2 scenario SIGKILL (n=1 mỗi scenario); latency chưa đo. Persistence artifact opt-in; UI tự thử bind port 9749 toàn cục (tắt UI trong profile riêng — flag chưa verify bằng thực thi).
- **G0: PASS cho baseline subset với limits ghi rõ** — managed mode (G2, CHƯA implement) sẽ phải: profile namespace riêng (HOME/CBM_CACHE_DIR/CBM_RUNTIME_DIR/XDG_CONFIG_HOME/TMPDIR — protocol đã validate live ở mục 6), `auto_watch=false` (tắt watcher — chưa verify flag), UI off (chưa verify flag), không bao giờ `install`, không `--persistence true` trừ opt-in, timeout kill process-group (proc.py) + expected daemon self-termination sau disconnect (observed; latency chưa đo). Các limits này là yêu cầu ghi nhận cho G2, không phải thứ P0 đã chứng minh giải quyết.
- Git snapshot binding: `index_status` live output KHÔNG có `head_sha`/`base_sha`/`branch` (`q2.out`) — khẳng định live điều đã thấy ở matrix: git binding UNVERIFIABLE trên binary 0.10.8 (blocker G0-B3 còn mở, fail-close là đúng).
- Raw receipts đã mirror vào repo: `evidence/wp03-spike-receipts.txt` (sha256 + excerpt đã sanitize) — không phụ thuộc /tmp.
- Giới hạn: mọi kết quả là host macOS arm64; platform khác KHÔNG được tuyên bố supported.
