# P0 Handoff — Monorepo Python + C (2026-09-05)

Checkpoint bàn giao cuối phiên P0-initial. Người nhận: reviewer độc lập + phase kế tiếp. File sở hữu: `plan/python-c-monorepo/` (không đụng production code).

## 1. Kết luận gate

- **G0: BLOCKED** — chưa "biết chính xác supported binary/operation". Hai lỗ hổng: (a) identity payload↔pin chưa đóng bằng mật mã học; (b) spike sống NOT RUN do scratch isolation chưa chứng minh được.

## 2. Bằng chứng đã ghi (đường dẫn tương đối `plan/python-c-monorepo/`)

| Bằng chứng | File |
| :--- | :--- |
| Git/env/binary/test baseline JSON | `evidence/baseline-environment.json` |
| Per-file golden manifest (8 files) | `evidence/golden-fixture-manifest.json` — digest `bd65c856ce16af5004109cd941c334a95446eff02d9dce6a98f5fd7eb0c40a64` (sha256 over sorted `relpath\0sha256\n` lines) |
| Binary identity phân tích static | `evidence/binary-identity.md` |
| Ma trận schema/compatibility/capability | `evidence/p0-matrices.md` (historical/mock vs live UNKNOWN + blocker ledger) |
| Full test log | `evidence/test-run-mocked-golden.log` (154 passed / 0 failed / 1 warning / 26.25s / `exit_code=0` ghi trong log từ rerun thật) |
| ADR draft | `adr-p0-baseline.md` |

## 3. Sự thật cần người nhận hiểu đúng

1. **Claimed pin ≠ measured payload:** golden `_meta.json` + ADR 0001 claim `0.10.8@010569f`; payload thực tế trên disk là Mach-O arm64 sha256 `996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435` (295,457,616 bytes, mtime 2026-08-25 14:06 — cùng ngày capture golden, nhưng đó là circumstantial). Binary chứa đúng 1 chuỗi `0.10.8` (static marker yếu). Chưa chạy version probe.
2. **Candidate `3c7427e`:** không có source local (đã tìm `~/code`, `~/code/GitHub`, `~/.local/src`, `~/src`); không có wheel cache; license chưa kiểm chứng được ⇒ fetch/build BLOCKED theo luật "missing provenance = blocker".
3. **Lifecycle:** SOT side gọi one-shot qua `src/sot_graph/proc.py run_command` (~dòng 262; shell-less, kill process-group khi timeout, không daemon). Adapter (`src/sot_graph/providers/codebase_memory.py`) **không scrub env/HOME**. Binary strings: "watched projects auto-refresh in the background" ⇒ không được giả định kill CLI = cancel worker; đây chính là giả định G0 buộc phải xóa. Kill-CLI behavior chưa hề được đo.
4. **CI:** `.github/workflows/ci.yml` dòng 191–215: job `real-cbm-e2e` (ubuntu-latest, `uv pip install codebase-memory-mcp==0.10.8`, chạy `scripts/e2e_real_cbm.py`); `package-smoke` matrix 3 OS. Đây là cấu hình — **không phải bằng chứng CI đã pass**.
5. **Test local:** 5 file mocked/golden (golden replay fixture JSON, adapter dùng fake executable trên PATH riêng, không network): 154/154 pass trên Python 3.14.6, .venv sẵn có. Không test native live nào được chạy.
6. `tests/conftest.py` **không tồn tại**; pytest config trong `pyproject.toml` (`testpaths=["tests"]`, `addopts="-v --strict-markers"`).

## 4. Việc tiếp theo (theo thứ tự ưu tiên)

1. Giữa block: locate/xin trustworthy provenance binding — release manifest gắn sha256 payload `996bad5f…` với source commit + build attestation (source 0.10.8/`3c7427e` có thêm thì phục vụ license/state-dir/lifecycle inspection, nhưng source một mình KHÔNG đóng identity). Version probe chỉ là inspection, không phải đường gỡ. Khi có provenance + attestation: đóng WP0.2; WP0.4 license vẫn cần source/notices.
2. Thiết kế scratch-isolation protocol: xác định state dir toàn cục của CBM từ source (khi có) + env/HOME scrubbing cho subprocess; chỉ sau đó cho phép WP0.3 spike sống trên scratch repo, không đụng store/daemon toàn cục.
3. Sau G0 mở: P1 authoring fixture song song được nhưng không promote; STOP checkpoint bắt buộc giữa các phase (mỗi phase tạo `pN-handoff.md` mới, handoff cũ giữ nguyên).

## 5. Reviewer findings — resolution receipt (2026-09-05)

| Finding | Resolution |
| :--- | :--- |
| Thiếu tool-schema inventory, operation compatibility matrix, runtime capability report | Added `evidence/p0-matrices.md`: 7-tool schema inventory, operation matrix (historical binary-captured / mocked PASS vs live UNKNOWN), runtime capability report, blocker ledger G0-B1/B2/B3 |
| Historical/mock vs live unknown + blocker statuses | Mọi ma trận có cột riêng: historical receipt, mocked result, live payload = UNKNOWN (chưa thực thi, identity chưa đóng), blocker id |
| Self-contained resume requirements | Mục 6 mới dưới đây; execution-plan.md mục 0.4 sửa: mỗi phase TẠO MỚI `pN-handoff.md`, handoff trước giữ nguyên bất biến (không rename p0) |
| WP identity phải PARTIAL nếu evidence không có | WP0.2 đổi DONE→**PARTIAL** trong status.md, execution-plan.md và baseline-environment.json (`wp0_2_status`) |
| Dirty baseline cần định danh thời điểm | baseline-environment.json + status.md: dirty capture TRƯỚC khi tạo evidence folder; file untracked không liên quan được giữ nguyên, không thuộc output |
| Test log thiếu exit code | Suite đã chạy lại y nguyên (same 5 files, same flags): 154 passed, 1 warning, 26.25s; **exit_code=0 thật** được ghi vào cuối log mới (log thay thế, không ghép receipt hồi tố) |
| diff-impact cho docs change | Chạy CLI `sot diff-impact`, receipt bounded tại `evidence/diff-impact-docs.log` |
| Conservative claims | Toàn bộ cột live là UNKNOWN; không claim pass nếu chưa measured |
| **Delta-2:** probe-as-closure còn sót (status.md unblock #2, baseline JSON, execution-plan G0, adr-p0, binary-identity) | Deleted ở mọi nơi; unblock G0 duy nhất cho identity = trustworthy provenance binding (sha256 payload → source commit + build attestation); source một mình không đủ; probe chỉ là inspection |
| **Delta-2:** stale 26.72s (status.md, p0-handoff.md) | Cập nhật 26.25s khớp log thật; 26.72s chỉ còn trong baseline JSON như ghi chú lịch sử của lần chạy đầu |
| **Delta-2:** execution-plan thiếu WP0.7 | Đã thêm WP0.7 (matrices, ĐÃ LÀM — live UNKNOWN) |
| **Delta-2:** p0-handoff diff-impact thiếu caveat | Đã thêm caveat bounded/untracked docs khớp status.md phụ lục |

## 6. Yêu cầu resume tự đủ (self-contained resume)

Agent mới resume cần đúng những thứ sau, không cần ngữ cảnh hội thoại:
1. Baseline: `main` @ `319a4429e2ad2252e5b282719223db6f1e338ea2`; dirty tiền tồn tại `plan/remaining-work-phased-plan-2026-09-05.md` (giữ nguyên).
2. Đọc theo thứ tự: `status.md` → `p0-handoff.md` → `execution-plan.md` → `evidence/p0-matrices.md` → `evidence/baseline-environment.json` → `evidence/binary-identity.md` → `adr-p0-baseline.md`.
3. Constraints còn hiệu lực: không chạy binary native; không fetch/build CBM khi thiếu provenance; không đụng store/daemon toàn cục; không commit/push; một file một owner; STOP ở mỗi checkpoint.
4. Lệnh kiểm chứng nhanh (mocked only): `.venv/bin/pytest tests/test_cbm_golden.py tests/test_cbm_adapter.py tests/test_cbm_verification.py tests/test_cbm_normalization.py tests/test_cbm_snapshot_p2.py -p no:cacheprovider` — kỳ vọng 154 passed; exit code thật phải ghi vào log mới.
5. Điều kiện gỡ G0: (i) trustworthy provenance binding payload `996bad5f…` → source commit + build attestation đóng WP0.2; (ii) source (kèm attestation hoặc không) cho license/state-dir inspection + scratch-isolation protocol; khi đó mới WP0.3 spike. Version probe chỉ inspection: nếu chỉ probe được version mà không có provenance binding → giữ nhãn UNKNOWN, G0 vẫn BLOCKED.

## 7. Ghi chú vận hành

- Không commit/push; các file mới chưa nằm trong git index (để reviewer tự diff).
- Sau đợt sửa theo review: `sot diff-impact HEAD` → LOW (13/100), 0 blast-radius callers, no API/test bindings (`evidence/diff-impact-docs.log`). **Caveat: receipt bounded** — toàn bộ plan docs là untracked (chưa vào git index), nên diff-impact chủ yếu đo trạng thái committed (thấy 1 changed file); kết quả không phản ánh đầy đủ thay đổi docs mới. `sot reconcile` exit 0 (4 updated/392 unchanged); `sot doctor` exit 0 (396 tracked files, 5187 nodes) — logs trong `evidence/`.
- Ước lượng giữ nguyên tài liệu gốc: 26–47 engineer-days; chưa hiệu chỉnh vì P0 BLOCKED.

## 8. P0 continuation (2026-09-05, session 2) — provenance ĐÃ ĐÓNG, WP0.3 unblocked

Ngữ cảnh authorization mới từ user: (i) external third-party attestation của binary đã cài KHÔNG còn là điều kiện bắt buộc — trusted evidence = release-manifest binding hoặc controlled reproducible build receipt từ pinned source + digest (đúng mục 7 tài liệu gốc); (ii) checkpoint bỏ STOP cứng, auto-advance khi gate verified bằng chứng trên disk; (iii) cho phép fetch public source về scratch (read-only external); (iv) commit nhỏ theo task-group được phép.

### 8.1. Khám phá kênh provenance thật (sửa giả định cũ "không có release manifest")

- Distribution repo thật: **`DeusData/codebase-memory-mcp`** (wrapper PyPI `REPO` trỏ về đây — `_cli.py:19`). Repo `minhgv/…` (plan dẫn) chỉ là source mirror, **không có release nào** (API `[]`).
- PyPI 0.10.8 wheel/sdist tải về, sha256 khớp PyPI JSON (`a5e39e68…` / `d8186745…`); wheel là downloader-wrapper 14.9KB, KHÔNG chứa native binary.
- Release **v0.10.8** (published 2026-08-19T02:42:10Z, 49 assets): tag → commit **`46ae198fc11cda80e817acbc5f5908d7c2de7032`**; checksums.txt `9d2e33bd…` digest-verified qua API; sigstore `.bundle` cho từng asset; SBOM SPDX; release-selection.tsv. Bản copy digest-verified: `evidence/upstream-release/`.
- darwin-arm64 tar.gz `9bd840df…` (khớp checksums.txt) → inner binary **`2412e017…`** (297,185,328 B).

### 8.2. Identity closure (WP0.2)

- Byte-region comparison installed `996bad5f…` vs release `2412e017…`: 2,208 diff regions, toàn bộ nằm ở header (7 byte, __LINKEDIT size field) + signature block (594KB diff + 1.7MB tail). **≈294.8MB code/data segments BYTE-IDENTICAL.** Cùng string set (123,812, diff 0), cùng `__text` 20,745,352 B, cùng LC_BUILD_VERSION, cùng code-sign Identifier; ad-hoc CodeDirectory khác coverage (17,998 vs 71,989 page hashes).
- Verdict: installed binary = release v0.10.8 darwin-arm64 content, re-signed. Version CONFIRMED. Golden `0.10.8@010569f` là mis-attribution: `010569f` là main merge sau release (41 commit sau tag; pyproject còn ghi 0.8.1 lúc đó); build commit thật = `46ae198f`.
- Full chain + lệnh tái lập: `evidence/provenance-upstream.md` (mục 2, 3, 7).

### 8.3. Source/license/state-dir (WP0.4 + WP0.3 protocol)

- WP0.4 DONE: MIT (DeusData 2025) + THIRD_PARTY_NOTICES.md 563KB ship cùng binary; source full clone verified (tag v0.10.8 fetch được); build recipe production `make -f Makefile.cbm cbm`, version inject `-DCBM_VERSION` (main.c:97), test seams opt-in compile-out.
- WP0.3 protocol xong (`provenance-upstream.md` mục 5): `HOME`+`CBM_CACHE_DIR`+`CBM_RUNTIME_DIR`+`XDG_CONFIG_HOME`+`TMPDIR` che phủ cache/config/rendezvous/tmp; rendezvous key là HẰNG SỐ account-wide (`service.c:144-162`) ⇒ `CBM_RUNTIME_DIR` BẮT BUỘC cho scratch (nếu không, scratch test sẽ share daemon với user); `auto_watch` default true (tắt được qua scratch config db); `auto_index` default false; `--version` là process STATELESS (`bootstrap.c:206-209`).

### 8.4. Trạng thái gate sau continuation

- G0: UNBLOCKED — còn thiếu đúng một thứ: **WP0.3 live spike** (lifecycle/cancel/artifact đo thật trên scratch). WP0.2 CLOSED, WP0.4 DONE, WP0.1/0.5/0.6/0.7 giữ nguyên từ mục 2.
- File mới/đổi session này: `evidence/provenance-upstream.md` (mới), `evidence/upstream-release/{checksums-v0.10.8.txt, sbom.json, release-selection.tsv}` (mới, digest-verified copies), status.md/execution-plan.md/adr-p0-baseline.md (cập nhật WP statuses + authorization), mục 8 này (append-only). `binary-identity.md` giữ nguyên như lịch sử — superseded bởi `provenance-upstream.md`.
- Native supported matrix: giới hạn host thật đã đo (macOS arm64); mọi platform khác = experimental/không tuyên bố cho tới khi đo thật; GS-SURFACE không waive.
