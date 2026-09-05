# Trạng thái P0 — Monorepo Python + C (cập nhật 2026-09-05)

- Git baseline: `main` @ `319a4429e2ad2252e5b282719223db6f1e338ea2` (dirty: 1 file untracked `plan/remaining-work-phased-plan-2026-09-05.md`; trạng thái dirty được capture TRƯỚC khi tạo thư mục `plan/python-c-monorepo/` — file untracked đó là việc riêng có trước, được giữ nguyên, không thuộc output P0).
- Tài liệu gốc: [`../python-c-monorepo-architecture-plan-2026-09-05.md`](../python-c-monorepo-architecture-plan-2026-09-05.md).
- **G0 tổng thể: UNBLOCKED (2026-09-05 continuation) — WP0.2/WP0.4 đóng, WP0.3 spike còn NOT RUN.** Không có mục nào được đánh "pass" nếu thiếu proof. Bổ sung continuation: `evidence/provenance-upstream.md`.

## Work packages

| WP | Nội dung | Trạng thái | Bằng chứng |
| :-- | :--- | :--- | :--- |
| WP0.1 | Baseline git/env, hash binary, hash golden suite | DONE | `evidence/baseline-environment.json`, `evidence/golden-fixture-manifest.json` |
| WP0.2 | Identity wrapper/payload vs claimed pin | **IDENTITY CLOSED (2026-09-05 continuation)** | `evidence/provenance-upstream.md` — release-manifest binding + byte-region comparison: installed `996bad5f…` có toàn bộ code/data segments byte-identical với release darwin-arm64 v0.10.8 (`2412e017…`), khác nhau chỉ 7 byte header + ad-hoc signature block; golden pin `0.10.8@010569f` là mis-attribution (build commit thật = tag `v0.10.8` → `46ae198f`) |
| WP0.3 | Spike sống trên scratch repo (lifecycle/cancel/artifacts) | **UNBLOCKED — protocol sẵn sàng** | Isolation protocol xác định từ source tag `46ae198f`: `HOME`+`CBM_CACHE_DIR`+`CBM_RUNTIME_DIR`+`XDG_CONFIG_HOME`+`TMPDIR` che phủ toàn bộ state namespace (`evidence/provenance-upstream.md` mục 5); spike sống còn phải chạy |
| WP0.4 | License/packaging/source của candidate `3c7427e` | **DONE (2026-09-05 continuation)** | MIT + THIRD_PARTY_NOTICES.md (563KB) ship kèm release; source full clone verified; upstream pin chuẩn = tag `v0.10.8` = `46ae198f`; PyPI wheel/sdist digests khớp. `evidence/provenance-upstream.md` mục 1, 2, 4 |
| WP0.5 | Bằng chứng CI + test mocked/golden local | DONE | `ci.yml:191-215` (config, chưa phải proof CI pass); **154 passed / 0 failed** (5 file, 26.25s rerun, `exit_code=0` ghi trong log sau rerun thật), log `evidence/test-run-mocked-golden.log` |
| WP0.6 | ADR hướng đã chấp nhận vs còn mở | DRAFT | `adr-p0-baseline.md` |
| WP0.7 | Tool-schema inventory + operation compatibility matrix + runtime capability report | DONE (live cột UNKNOWN) | `evidence/p0-matrices.md` — historical/mock vs live-unknown + blocker ledger G0-B1/B2/B3 |

## Phát hiện chính

1. Binary đã cài là Mach-O arm64 một khối (295,457,616 bytes, sha256 `996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435`, mtime 2026-08-25 14:06 — trùng ngày capture golden). Không phải script wrapper. Chưa hề được thực thi trong đợt này.
2. Golden `_meta.json` + ADR 0001 claim pin `0.10.8@010569f`; binary chứa đúng 1 chuỗi `0.10.8` (static marker yếu) — **chưa thể gắn hash payload với pin bằng mật mã học**.
3. SOT gọi CBM one-shot qua `proc.py run_command` (shell-less, kill process-group khi timeout) — SOT không quản daemon qua đường này; nhưng adapter **không scrub env/HOME** cho subprocess.
4. Chuỗi nhúng trong binary nói "watched projects auto-refresh in the background" ⇒ giả định "kill CLI = cancel worker" vẫn chưa được chứng minh (đúng như gate G0 yêu cầu xóa bỏ).
5. CI: `real-cbm-e2e` (Linux, cài `codebase-memory-mcp==0.10.8` từ PyPI) + `package-smoke` matrix 3 OS tồn tại trong YAML; **không có artifact chứng minh run nào pass**.

## Điều kiện gỡ BLOCKED G0 (cập nhật 2026-09-05 continuation — CẢ HAI ĐÃ ĐÓNG)

1. **Provenance đóng identity (WP0.2): ĐÃ ĐÓNG.** User authorization 2026-09-05: external attestation không còn bắt buộc; trusted evidence = release-manifest binding (checksums.txt digest-verified + sigstore bundles) hoặc controlled reproducible build receipt từ source pin. Channel thật tìm thấy: distribution repo `DeusData/codebase-memory-mcp` (repo `minhgv/` không có release). Binding hoàn chỉnh trong `evidence/provenance-upstream.md`.
2. **State-dir toàn cục: ĐÃ XÁC ĐỊNH.** Toàn bộ state namespace điều khiển được bằng env: `HOME` → cache + config; `CBM_CACHE_DIR` trực tiếp; `CBM_RUNTIME_DIR` → daemon rendezvous (bắt buộc vì namespace account-wide, key là hằng số — `service.c:144-162`); `auto_watch` default true tắt được qua `config set` trong scratch cache. Protocol mục 5 của `evidence/provenance-upstream.md`.
3. Còn lại để G0 PASS: WP0.3 live spike (lifecycle/cancel/artifacts đo được trên scratch, không còn giả định kill CLI = cancel worker).

## Điều đã chạy (đo được)

- `.venv/bin/pytest tests/test_cbm_golden.py tests/test_cbm_adapter.py tests/test_cbm_verification.py tests/test_cbm_normalization.py tests/test_cbm_snapshot_p2.py -p no:cacheprovider` → **154 passed, 0 failed, 1 warning, 26.25s, `exit_code=0` (ghi trong log từ rerun thật)**. Toàn bộ mocked/golden, không gọi binary thật, không network.

## Phụ lục: SOT health sau khi tạo + sửa file (2026-09-05, lần 2)

- `sot diff-impact HEAD`: exit 0 — Risk LOW 13/100, 1 changed file, 0 blast-radius callers, no API/test bindings; untracked plan docs chưa vào index nên chủ yếu thấy trạng thái sạch. Log: `evidence/diff-impact-docs.log`.
- `sot reconcile`: exit 0 — "4 indexed/updated, 392 unchanged, 0 purged, 0 failed" (0.56s). Log: `evidence/sot-reconcile.log`.
- `sot doctor`: exit 0 — schema v8, WAL; 396 tracked files, 5187 nodes. Log: `evidence/sot-doctor.log`.
- Ghi chú kiến thức đã lưu: SOT note `6fc6034b5477` (P0 baseline summary).

## Không làm trong đợt này

- Không fetch/build CBM candidate; không chạy binary native; không commit/push; không sửa production code; không chạy `sot clean`; không giả lập kết quả đo native.
