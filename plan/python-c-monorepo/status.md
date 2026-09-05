# Trạng thái P0 — Monorepo Python + C (cập nhật 2026-09-05)

- Git baseline: `main` @ `319a4429e2ad2252e5b282719223db6f1e338ea2` (dirty: 1 file untracked `plan/remaining-work-phased-plan-2026-09-05.md`; trạng thái dirty được capture TRƯỚC khi tạo thư mục `plan/python-c-monorepo/` — file untracked đó là việc riêng có trước, được giữ nguyên, không thuộc output P0).
- Tài liệu gốc: [`../python-c-monorepo-architecture-plan-2026-09-05.md`](../python-c-monorepo-architecture-plan-2026-09-05.md).
- **G0 tổng thể: PASS — baseline subset, scope hẹp (2026-09-05).** Supported binary = installed `996bad5f…` (release v0.10.8 content). **Supported native tools CHỈ 4/15 đã live-verify: index_repository, search_graph, index_status, list_projects — đo qua 6 scenarios** (version probe = CLI command không phải tool; index default + index `--persistence true` = cùng một tool index_repository; thêm search_graph, index_status, list_projects). **11/15 tool còn lại = UNKNOWN, KHÔNG được tuyên bố supported**. Cancel = client-death supervision đo được trong đúng 2 scenario SIGKILL (n=1 mỗi scenario) — không còn giả định kill CLI = cancel worker, nhưng KHÔNG phải cam kết tổng quát; daemon latency chưa đo (log không timestamp). Isolation protocol validate bằng pre/post asserts (user daemon 47134 không đụng). Git binding vẫn UNVERIFIABLE trên 0.10.8 (G0-B3 mở). Managed-mode limits thuộc **G2 — chưa implement**. Platform: **chỉ host Darwin arm64, experimental spike ONLY — KHÔNG phải supported release platform; không có native CI support claim nào** (xem mục "Platform & budget" dưới). Chi tiết: `evidence/wp03-live-spike.md` mục 8; raw receipts mirror: `evidence/wp03-spike-receipts.txt`.

## Work packages

| WP | Nội dung | Trạng thái | Bằng chứng |
| :-- | :--- | :--- | :--- |
| WP0.1 | Baseline git/env, hash binary, hash golden suite | DONE | `evidence/baseline-environment.json`, `evidence/golden-fixture-manifest.json` |
| WP0.2 | Identity wrapper/payload vs claimed pin | **IDENTITY CLOSED (2026-09-05 continuation)** | `evidence/provenance-upstream.md` — release-manifest binding + byte-region comparison: installed `996bad5f…` có toàn bộ code/data segments byte-identical với release darwin-arm64 v0.10.8 (`2412e017…`), khác nhau chỉ 7 byte header + ad-hoc signature block; golden pin `0.10.8@010569f` là mis-attribution (build commit thật = tag `v0.10.8` → `46ae198f`) |
| WP0.3 | Spike sống trên scratch repo (lifecycle/cancel/artifacts) | **DONE (2026-09-05 live, scope hẹp)** | `evidence/wp03-live-spike.md` — version probe 0.10.8 exit 0; cold index 54/119 exit 0 (real 11.67s incl. daemon startup); kill-mid-job → supervisor reaps worker (signal 15), no orphan/commit dở (n=1); SIGKILL-at-startup → daemon tự kết thúc (n=1); clean exit → daemon stop; artifact chỉ với `--persistence true`; UI port 9749 bị daemon tự thử bind mỗi run (tắt ở G2, flag chưa verify); **daemon latency chưa đo (log không timestamp)**; pre/post asserts: user daemon 47134 không đụng. Raw mirror: `evidence/wp03-spike-receipts.txt` |
| WP0.4 | License/packaging/source của candidate `3c7427e` | **DONE (2026-09-05 continuation)** | MIT + THIRD_PARTY_NOTICES.md (563KB) ship kèm release; source full clone verified; upstream pin chuẩn = tag `v0.10.8` = `46ae198f`; PyPI wheel/sdist digests khớp. `evidence/provenance-upstream.md` mục 1, 2, 4 |
| WP0.5 | Bằng chứng CI + test mocked/golden local | DONE | `ci.yml:191-215` (config, chưa phải proof CI pass); **154 passed / 0 failed** (5 file, 26.25s rerun, `exit_code=0` ghi trong log sau rerun thật), log `evidence/test-run-mocked-golden.log` |
| WP0.6 | ADR hướng đã chấp nhận vs còn mở | **ACCEPTED — constrained P1 subset only** (user autonomous authorization + independent review 2026-09-05; KHÔNG phải chấp nhận toàn bộ deliverables P0) | `adr-p0-baseline.md` — checklist P0 chưa hoàn thành (mục D) carried thành hard P4 prerequisites |
| WP0.7 | Tool-schema inventory + operation compatibility matrix + runtime capability report | DONE (live: baseline subset đo được, còn lại UNKNOWN) | `evidence/p0-matrices.md` + phụ lục live `evidence/wp03-live-spike.md` mục 8 — blocker ledger: G0-B1 CLOSED (provenance), G0-B2 CLOSED (spike đo được, scope hẹp), G0-B3 MỞ (git binding UNVERIFIABLE trên 0.10.8, live-confirmed tại `q2.out`) |

## Phát hiện chính

1. Binary đã cài là Mach-O arm64 một khối (295,457,616 bytes, sha256 `996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435`, mtime 2026-08-25 14:06 — trùng ngày capture golden). Không phải script wrapper. Chưa hề được thực thi trong đợt này.
2. Golden `_meta.json` + ADR 0001 claim pin `0.10.8@010569f`; binary chứa đúng 1 chuỗi `0.10.8` (static marker yếu) — **chưa thể gắn hash payload với pin bằng mật mã học**.
3. SOT gọi CBM one-shot qua `proc.py run_command` (shell-less, kill process-group khi timeout) — SOT không quản daemon qua đường này; nhưng adapter **không scrub env/HOME** cho subprocess.
4. Chuỗi nhúng trong binary nói "watched projects auto-refresh in the background" — **đã đo thật (WP0.3)**: `watcher.watch` xuất hiện ngay lần index đầu (auto_watch default true, live); kill CLI không trực tiếp cancel — daemon supervisor mới là tầng cancel.
5. CI: `real-cbm-e2e` (Linux, cài `codebase-memory-mcp==0.10.8` từ PyPI) + `package-smoke` matrix 3 OS tồn tại trong YAML; **không có artifact chứng minh run nào pass**.

## Điều kiện gỡ BLOCKED G0 (cập nhật 2026-09-05 continuation — CẢ HAI ĐÃ ĐÓNG)

1. **Provenance đóng identity (WP0.2): ĐÃ ĐÓNG.** User authorization 2026-09-05: external attestation không còn bắt buộc; trusted evidence = release-manifest binding (checksums.txt digest-verified + sigstore bundles) hoặc controlled reproducible build receipt từ source pin. Channel thật tìm thấy: distribution repo `DeusData/codebase-memory-mcp` (repo `minhgv/` không có release). Binding hoàn chỉnh trong `evidence/provenance-upstream.md`.
2. **State-dir toàn cục: ĐÃ XÁC ĐỊNH.** Toàn bộ state namespace điều khiển được bằng env: `HOME` → cache + config; `CBM_CACHE_DIR` trực tiếp; `CBM_RUNTIME_DIR` → daemon rendezvous (bắt buộc vì namespace account-wide, key là hằng số — `service.c:144-162`); `auto_watch` default true tắt được qua `config set` trong scratch cache. Protocol mục 5 của `evidence/provenance-upstream.md`.
3. Còn lại để G0 PASS: ~~WP0.3 live spike~~ **ĐÃ ĐO (2026-09-05)** — kết quả scope hẹp ghi ở `evidence/wp03-live-spike.md`: giả định kill CLI = cancel đã bị xóa bằng đo thật (kill không trực tiếp cancel; daemon supervisor tự cancel worker qua SIGTERM trong 2 scenario SIGKILL, n=1). G0 PASS cho baseline subset; các limits (watcher off, UI off, cancel latency, 11/15 tool UNKNOWN) chuyển thành yêu cầu G2 chưa implement.

## Platform & CI/storage budget (quyết định B0, 2026-09-05 — theo yêu cầu gốc của P0)

- **Platform decision (conservative):** host đo được duy nhất = **Darwin arm64 (máy dev này)**. Trạng thái = **experimental spike ONLY** — KHÔNG phải supported release platform; KHÔNG platform nào khác được tuyên bố. P0 chưa chốt supported platform list — việc này thuộc quyết định release (P4/P5), không thể chốt từ 1 host.
- **Native CI support claim: KHÔNG có.** `ci.yml:191-215` vẫn chỉ là config; mọi job CI liên quan native KHÔNG được quảng bá là supported/verified.
- **Storage/CI budget: CHƯA duyệt — không duyệt tùy tiện khi chưa có measurement.** Số đo duy nhất: source clone v0.10.8 tại candidate `3c7427ef…` = **1.5 GB on-disk bao gồm .git** (2119 files excl. .git). **Chưa tách được**: working-tree source vs `.git` vs build artifacts vs release binary (297 MB inner binary; tarball 40.4 MB) vs cache runtime — ngân sách CI/storage cần các con số này tách riêng trước khi quyết. Đây là measurement còn thiếu, KHÔNG phải budget đã duyệt.
- **ADR: ACCEPTED cho P1 limited subset** (docs-only, autonomous authorization + independent review) — checklist P0 chưa hoàn thành (grammar/generated inventory, source/git/build budget breakdown) là **HARD P4 PREREQUISITES**: `adr-p0-baseline.md` mục D. Signature verify (independent publisher) là hard prerequisite trước managed artifact release.

## P0-only unknowns còn lại (explicit, không chuyển sang phase khác)

1. 11/15 native tools chưa từng chạy (chỉ help-listed).
2. Daemon tự-kết-thúc latency chưa đo (log không timestamp).
3. `--ui=false` / tắt watcher (`auto_watch=false` qua config) chưa verify bằng thực thi.
4. Cancel qua đường SIGTERM/timeout từ `proc.py` và đường không-daemon chưa đo.
5. Git snapshot binding UNVERIFIABLE trên binary 0.10.8 (G0-B3, fail-close là đúng) — thiết kế digest riêng là việc P3, không phải P0.
6. Footprint chi tiết (source/.git/build/cache tách riêng) chưa đo → budget chưa duyệt.
7. Envelope classes malformed/truncated/oversized trên binary thật chưa golden (P1 fixtures).

## Điều đã chạy (đo được)

- `.venv/bin/pytest tests/test_cbm_golden.py tests/test_cbm_adapter.py tests/test_cbm_verification.py tests/test_cbm_normalization.py tests/test_cbm_snapshot_p2.py -p no:cacheprovider` → **154 passed, 0 failed, 1 warning, 26.25s, `exit_code=0` (ghi trong log từ rerun thật)**. Toàn bộ mocked/golden, không gọi binary thật, không network.

## Phụ lục: SOT health sau khi tạo + sửa file (2026-09-05, lần 2)

- `sot diff-impact HEAD`: exit 0 — Risk LOW 13/100, 1 changed file, 0 blast-radius callers, no API/test bindings; untracked plan docs chưa vào index nên chủ yếu thấy trạng thái sạch. Log: `evidence/diff-impact-docs.log`.
- `sot reconcile`: exit 0 — "4 indexed/updated, 392 unchanged, 0 purged, 0 failed" (0.56s). Log: `evidence/sot-reconcile.log`.
- `sot doctor`: exit 0 — schema v8, WAL; 396 tracked files, 5187 nodes. Log: `evidence/sot-doctor.log`.
- Ghi chú kiến thức đã lưu: SOT note `6fc6034b5477` (P0 baseline summary).

## Không làm trong đợt này

- Đợt continuation 2026-09-05 (sau spike): **DOCS-ONLY PASS** — không chạy binary native, không đụng global daemon/config, không fetch/build, không commit/push, không sửa production code; spike WP0.3 do agent phiên trước thực thi, phiên này chỉ review/mirror/hash lại raw evidence (`evidence/wp03-spike-receipts.txt`, gồm cả các run FAILED/CANCELLED — không ẩn run hỏng).
- Signature: sigstore bundles chỉ observed presence — trust = GitHub TLS same-channel checksum, chưa verify independent publisher (`provenance-upstream.md` mục 8; hard prerequisite trước managed artifact release).
- P0 incomplete checklist (grammar/generated inventory; source/git/build budget breakdown) = hard P4 prerequisites — xem `adr-p0-baseline.md` mục D.
