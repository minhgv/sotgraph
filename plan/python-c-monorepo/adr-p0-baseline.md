# ADR draft (P0): Baseline native CBM — hướng đã chấp nhận vs quyết định còn mở

- Ngày: 2026-09-05. Trạng thái: **PROPOSED/DRAFT** (chưa có reviewer độc lập phê duyệt; G0 BLOCKED).
- Bối cảnh: tài liệu gốc `plan/python-c-monorepo-architecture-plan-2026-09-05.md` đã được user phê duyệt hướng P0–P7.

## A. Hướng ĐÃ được chấp nhận (broad direction, từ tài liệu gốc)

1. Monorepo Python + C, một repo/một trải nghiệm SOT; Python giữ điều phối/xác minh, CBM giữ engine C, giao tiếp qua process boundary.
2. Filesystem là SSOT; graph là projection có scope; CBM là provider native có pin phiên bản, không phải nguồn chân lý thay thế.
3. Chuỗi promotion cứng P0→P7; external binary chỉ opt-in admin/developer; không download-on-query, không public CBM shim; GS-SURFACE là release blocker.
4. Ước lượng 26–47 engineer-days giữ nguyên cho tới khi P0 đóng được platform/harness.

## B. Quyết định CÒN MỞ (chưa quyết — không coi là accepted)

1. **Identity pin: ĐÃ ĐÓNG (2026-09-05 continuation).** Release-manifest binding: distribution repo `DeusData/codebase-memory-mcp`, tag `v0.10.8` = commit `46ae198f`, checksums.txt digest-verified (9d2e33bd…), darwin-arm64 release binary `2412e017…`; installed `996bad5f…` byte-identical ở toàn bộ code/data segments (khác 7 byte header + ad-hoc signature). Golden claim `@010569f` mis-attribution. Provenance policy mới (user authorization): external attestation không bắt buộc; release-manifest binding hoặc controlled reproducible build receipt đều là trusted evidence. Chi tiết: `evidence/provenance-upstream.md`. (G0 — CLOSED)
2. **Upstream-base cho P4 subtree: pin `v0.10.8` = `46ae198f`** (trùng binary đã verify). Nhánh main source repo (`3c7427e` minhgv / `fe85a6b2` DeusData) chỉ cân nhắc nếu P2/P3 cần fix mới — quyết định cuối ở P4. (G0/G4 — pin chốt, quyết subtree ở P4)
3. **Lifecycle model:** watcher nền của CBM chưa được đo; cơ chế cancel/quarantine (P2) chưa thiết kế được trên dữ liệu thật — hiện là [INFERENCE].WP0.3 spike đã unblocked (isolation protocol xong — `provenance-upstream.md` mục 5), chờ chạy đo thật.
4. **Platform support & CI budget:** chỉ có bằng chứng cấu hình CI (Linux real-cbm-e2e + package-smoke matrix 3 OS); chưa đo build footprint/byte-size ngân sách; chưa chốt platform list. Native supported matrix sẽ giới hạn ở host thật đã đo (macOS arm64) với experimental limitations ghi rõ; GS-SURFACE không waive supported claims.
5. **Scratch-isolation protocol: ĐÃ THIẾT KẾ** từ source (`provenance-upstream.md` mục 5): `HOME`/`CBM_CACHE_DIR`/`CBM_RUNTIME_DIR`/`XDG_CONFIG_HOME`/`TMPDIR`; pre/post asserts không đụng user daemon. Còn: chạy spike sống để chứng minh protocol hoạt động.
6. Snapshot content-bound dirty (P3) và rollout opt-in (P6): để theo tài liệu gốc, chưa có dữ liệu benchmark.

## C. Hệ quả

- Không promote P1 vượt mức authoring chuẩn bị; mọi claim trong `status.md` phải giữ trạng thái BLOCKED cho tới khi B.1–B.5 có bằng chứng. **[Cập nhật 2026-09-05: checkpoint STOP bỏ theo user authorization — auto-advance khi gate verified; B.1, B.2, B.5 phần thiết kế đã đóng/có bằng chứng, còn B.3 đo ở WP0.3.]**
- ADR này phải được reviewer độc lập duyệt trước khi chuyển ACCEPTED cho phần A; phần B mở dần theo gate.
