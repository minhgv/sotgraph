# P0 Handoff — ADDENDUM (2026-09-05, sau WP0.3 live spike + review fixes)

Bàn giao bổ sung. **`p0-handoff.md` gốc giữ NGUYÊN VĨNH VIỄN như lịch sử bất biến** (luật execution-plan mục 0.4) — nó ghi trạng thái G0 BLOCKED tại thời điểm đóng, và đã đúng lúc đó. File này ghi hiện trạng sau khi WP0.3 đã chạy và các overclaim đã bị reviewer bắt + sửa. Đọc cả hai khi nhận phase.

## 1. Hiện trạng gate

- **ADR: ACCEPTED — CHỈ cho P1 limited subset (safe scope)** theo user autonomous authorization + independent review 2026-09-05. **KHÔNG đồng nghĩa chấp nhận toàn bộ deliverables P0** — checklist chưa hoàn thành là HARD P4 PREREQUISITES (`adr-p0-baseline.md` mục D).
- **G0: PASS — baseline subset, scope hẹp.** Supported binary = installed `996bad5f…` (release v0.10.8 content, identity closed qua release-manifest binding — `evidence/provenance-upstream.md`).
- **Supported native tools: 4/15** — index_repository, search_graph, index_status, list_projects. Đo qua **6 scenarios** (version probe = CLI command, KHÔNG phải native tool; index_repository xuất hiện ở 2 scenarios: default + `--persistence true` = cùng một tool; + search_graph, index_status, list_projects). Envelope shape khớp golden.
- **11/15 tool còn lại: UNKNOWN** — help-listed only, KHÔNG được tuyên bố supported.
- **Giả định "kill CLI = cancel worker": ĐÃ XÓA bằng đo thật** — 2 scenario SIGKILL (startup, mid-job; n=1 mỗi scenario): daemon supervisor phát hiện client chết, tự cancel worker (SIGTERM, `supervisor.reap outcome=killed signal=15`), không orphan, không partial commit. KHÔNG phải cam kết cancellation tổng quát; daemon latency chưa đo (log không timestamp).
- Blocker ledger: **G0-B1 CLOSED** (provenance), **G0-B2 CLOSED** (spike đo được, scope hẹp), **G0-B3 MỞ** (git binding UNVERIFIABLE trên 0.10.8 — live-confirmed `q2.out` không có `head_sha`/`base_sha`/`branch`; fail-close là đúng; thiết kế digest riêng là việc P3).
- **Signature trust (reviewer note):** sigstore bundles chỉ OBSERVED presence — CHƯA verify. Trust hiện tại = GitHub TLS + account same-channel checksum, KHÔNG phải independent authenticated publisher. **Hard prerequisite trước managed artifact release (P4/GS-SURFACE): verify signature thật** (`provenance-upstream.md` mục 8).
- G1–G7: chỉ **P1 limited subset được tiến hành**; không promote G2+.

## 2. Platform & CI/storage budget (P0 requirement gốc — quyết định conservative)

- **Platform: Darwin arm64 (host dev duy nhất) = experimental spike ONLY.** KHÔNG phải supported release platform; không platform nào khác được tuyên bố. Supported platform list chỉ chốt ở P4/P5 với measurement thật trên mỗi platform.
- **Native CI support claim: KHÔNG có.** `ci.yml:191-215` là config — không được quảng bá job native là supported/verified.
- **Budget: CHƯA DUYỆT — không duyệt khi chưa có measurement.** Số đo duy nhất: clone source tại candidate `3c7427ef…` = **1.5 GB on-disk bao gồm .git** (2119 files excl. .git). **Chưa tách**: working-tree source vs `.git` vs build artifacts vs release binary (inner binary 297 MB, tarball 40.4 MB) vs runtime cache. Ngân sách CI/storage cần footprint tách riêng (artifact/source footprint khác git/build footprint) trước khi quyết — đây là measurement còn thiếu, không phải decision đã duyệt.
- **Grammar/generated inventory: CHƯA LÀM** (yêu cầu gốc P0) — HARD prerequisite trước subtree nhập ở P4.
- Cả hai mục trên = **P0 incomplete checklist explicit, carried thành hard P4 prerequisites** (`adr-p0-baseline.md` mục D).

## 3. P0-only unknowns (explicit — không giấu, không chuyển nhầm phase)

1. 11/15 native tools chưa chạy (query_graph, trace_path, get_code_snippet, get_graph_schema, get_architecture, search_code, delete_project, check_index_coverage, detect_changes, manage_adr, ingest_traces).
2. Daemon self-termination latency chưa đo (log không timestamp; claim cũ "≤5s" đã bị RÚT BỎ).
3. `--ui=false` và tắt watcher (`auto_watch=false`) chưa verify bằng thực thi (chỉ help-confirmed; UI port 9749 bị daemon tự thử bind mỗi run — 18x `ui.unavailable`, passive fail).
4. Cancel qua SIGTERM/timeout từ `proc.py` và đường không-daemon chưa đo.
5. Git snapshot binding UNVERIFIABLE trên 0.10.8 (G0-B3).
6. Footprint chi tiết source/.git/build/cache chưa tách → budget chưa duyệt.
7. Envelope classes malformed/truncated/oversized trên binary thật chưa có golden (việc P1).

## 4. Ràng buộc cho phase sau (đọc kỹ trước khi làm)

1. Không tuyên bố supported ngoài 4/15 tools + 6 scenarios ghi trên; mọi thứ khác = UNKNOWN explicit.
2. Không chạy native ngoài scratch isolation protocol (HOME/CBM_CACHE_DIR/CBM_RUNTIME_DIR/XDG_CONFIG_HOME/TMPDIR — `evidence/provenance-upstream.md` mục 5, đã validate live); không đụng global daemon (PID user) — pre/post asserts bắt buộc mỗi đợt đo.
3. Không commit/stash hộ user; reviewer độc lập (read-only) xác minh bằng chứng trên disk trước khi chấp nhận.
4. Raw spike evidence mirror trong repo: `evidence/wp03-spike-receipts.txt` (sha256 + excerpts) — /tmp là disposable, đừng dựa vào nó.
5. Mọi claim mới: `[EVIDENCE]` phải có path:line/digest + exit code thật; `[INFERENCE]` phải ghi rõ.

## 5. Việc kế tiếp (đã duyệt: P1 limited subset — main sẽ commit rồi implement)

1. **P1 safe subset (duyệt):** golden fixtures cho 4 tools đã verify (index_repository, search_graph, index_status, list_projects) + error classes; capability metadata đánh 11 tool = explicit unsupported; SOT CLI/MCP cùng interpretation. Không promote G2+, không native CI claim.
2. Measurement bổ sung (scratch-only): cancel-latency có instrument, thực thi `--ui=false`/watcher-off trong scratch profile, footprint tách source/.git/build — vẫn KHÔNG tự duyệt budget.
3. Quyết budget/platform list chỉ sau measurement tách riêng + reviewer duyệt; signature verification (independent publisher) bắt buộc trước managed artifact release.
4. Đợt tài liệu này là **docs-only pass** — toàn bộ thay đổi nằm trong `plan/python-c-monorepo/`, không đụng production code; raw receipts gồm cả failed/cancelled runs (`wp03-spike-receipts.txt` mục E).
