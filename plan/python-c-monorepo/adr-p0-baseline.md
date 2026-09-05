# ADR draft (P0): Baseline native CBM — hướng đã chấp nhận vs quyết định còn mở

- Ngày: 2026-09-05. Trạng thái: **ACCEPTED — CHỈ cho P1 limited subset (safe scope), theo user autonomous authorization + independent review 2026-09-05.** KHÔNG đồng nghĩa chấp nhận toàn bộ deliverables P0: checklist P0 chưa hoàn thành ghi rõ ở mục D (carried thành hard P4 prerequisites). **G0: PASS cho baseline subset (2026-09-05) — supported = 4/15 native tools live-verified trên installed `996bad5f…` (6 scenarios gồm version probe + 2 biến thể index); 11/15 tool = UNKNOWN; platform = Darwin arm64 experimental spike ONLY (không phải supported release); limits = yêu cầu G2 chưa implement.** Chi tiết: `evidence/wp03-live-spike.md` mục 8; addendum hiện trạng: `p0-handoff-addendum.md`.
- Bối cảnh: tài liệu gốc `plan/python-c-monorepo-architecture-plan-2026-09-05.md` đã được user phê duyệt hướng P0–P7.

## A. Hướng ĐÃ được chấp nhận (broad direction, từ tài liệu gốc)

1. Monorepo Python + C, một repo/một trải nghiệm SOT; Python giữ điều phối/xác minh, CBM giữ engine C, giao tiếp qua process boundary.
2. Filesystem là SSOT; graph là projection có scope; CBM là provider native có pin phiên bản, không phải nguồn chân lý thay thế.
3. Chuỗi promotion cứng P0→P7; external binary chỉ opt-in admin/developer; không download-on-query, không public CBM shim; GS-SURFACE là release blocker.
4. Ước lượng 26–47 engineer-days giữ nguyên cho tới khi P0 đóng được platform/harness.

## B. Quyết định CÒN MỞ (chưa quyết — không coi là accepted)

1. **Identity pin: ĐÃ ĐÓNG (2026-09-05 continuation).** Release-manifest binding: distribution repo `DeusData/codebase-memory-mcp`, tag `v0.10.8` = commit `46ae198f`, checksums.txt digest-verified (9d2e33bd…), darwin-arm64 release binary `2412e017…`; installed `996bad5f…` byte-identical ở toàn bộ code/data segments (khác 7 byte header + ad-hoc signature). Golden claim `@010569f` mis-attribution. Provenance policy mới (user authorization): external attestation không bắt buộc; release-manifest binding hoặc controlled reproducible build receipt đều là trusted evidence. Chi tiết: `evidence/provenance-upstream.md`. (G0 — CLOSED)
2. **Upstream-base cho P4 subtree: pin `v0.10.8` = `46ae198f`** (trùng binary đã verify). Nhánh main source repo (`3c7427e` minhgv / `fe85a6b2` DeusData) chỉ cân nhắc nếu P2/P3 cần fix mới — quyết định cuối ở P4. (G0/G4 — pin chốt, quyết subtree ở P4)
3. **Lifecycle model: [MEASURED 2026-09-05, scope hẹp]** — WP0.3 spike đã chạy trên scratch (`evidence/wp03-live-spike.md`): auto_watch default true live (`watcher.watch`); clean exit → daemon tự stop; SIGKILL CLI lúc startup → daemon tự kết thúc (`initial_window_expired`, n=1); SIGKILL giữa job → supervisor phát hiện client chết, tự cancel worker SIGTERM (`supervisor.reap outcome=killed signal=15`, n=1), không orphan/commit dở. Kill CLI ≠ cancel trực tiếp — daemon supervision mới là tầng cancel. **Chưa đo:** SIGTERM/timeout từ phía SOT, đường không-daemon, variance, daemon latency (log không timestamp). Thiết kế cancel/quarantine (P2) giờ có dữ liệu thật để dựa.
4. **Platform support & CI budget:** chỉ có bằng chứng cấu hình CI (Linux real-cbm-e2e + package-smoke matrix 3 OS) — **không có native CI support claim nào**. Đo bổ sung 2026-09-05: source clone tại candidate `3c7427ef…` = **1.5 GB on-disk bao gồm .git** / 2119 files (excl. .git), có sẵn ở scratch; **chưa tách source vs .git vs build artifacts vs cache** — ngân sách CI/storage **KHÔNG được duyệt khi chưa có các measurement tách riêng này**. Quyết định platform (conservative): **Darwin arm64 = experimental spike ONLY, không phải supported release platform**; supported platform list chỉ chốt ở P4/P5 với measurement thật. GS-SURFACE không waive supported claims.
5. **Scratch-isolation protocol: ĐÃ THIẾT KẾ + ĐÃ VALIDATE LIVE (2026-09-05).** `HOME`/`CBM_CACHE_DIR`/`CBM_RUNTIME_DIR`/`XDG_CONFIG_HOME`/`TMPDIR` (`provenance-upstream.md` mục 5); spike sống chạy đúng protocol, pre/post asserts: user daemon 47134 + rendezvous dir + user caches không đổi (`evidence/wp03-spike-receipts.txt` mục C). Side effect toàn cục còn lại: daemon tự thử bind UI port 9749 mỗi run (passive fail khi bị chiếm; tắt UI ở G2 — flag `--ui=false` mới xác nhận trên help, chưa thực thi).
6. Snapshot content-bound dirty (P3) và rollout opt-in (P6): để theo tài liệu gốc, chưa có dữ liệu benchmark.

## C. Hệ quả

- **Chỉ P1 limited subset được phép tiến hành** (safe scope theo review 2026-09-05): golden fixtures cho 4 tools đã verify + error classes; capability metadata đánh 11 tool = explicit unsupported; không promote lifecycle/isolation (G2) hay native CI. Không promote P2+.
- **Signature prerequisite (hard gate):** sigstore bundles chỉ mới OBSERVED presence; trust hiện tại = GitHub TLS/account same-channel checksum, KHÔNG phải independent authenticated publisher. Trước managed artifact release (P4/GS-SURFACE) bắt buộc verify signature thật (cosign hoặc tương đương) — `evidence/provenance-upstream.md` mục 8.
- P1 docs-only scope: đợt sửa tài liệu này là **docs-only pass** — không native execution nào do agent authoring thực hiện; spike evidence kế thừa từ run của agent trước (raw receipts đã mirror + hash).

## D. Checklist P0 chưa hoàn thành (explicit — carried thành HARD P4 PREREQUISITES)

1. **Grammar/generated inventory:** phân loại generated grammar vs handwritten source chưa làm (yêu cầu gốc P0 "phân biệt generated grammar với handwritten source"). → HARD prerequisite trước khi subtree nhập ở P4 (ảnh hưởng build size + ownership manifest).
2. **Source/git/build budget breakdown:** chỉ đo được 1.5 GB clone gồm .git; chưa tách source vs `.git` vs build artifacts vs release binary vs runtime cache. CI/storage budget KHÔNG duyệt khi chưa có số tách riêng. → HARD prerequisite cho P4 packaging decisions.
3. 11/15 native tools chưa đo; cancel latency chưa instrument; `--ui=false`/watcher-off chưa thực thi; SIGTERM path chưa đo (G2 measurements).
4. Git snapshot binding UNVERIFIABLE trên 0.10.8 (G0-B3 — thiết kế digest riêng là việc P3).
5. Independent publisher signature verification chưa làm (mục C).
