# P3 Handoff (fault subset) — Ledger rollback + publication + concurrency (2026-09-06)

**Trạng thái hiện hành: G3 = PASS scope hẹp (2026-09-06, audit độc lập read-only `c4bbb61b`) — readiness P4 research/implementation, KHÔNG phải G4.** Chuỗi promotion đã thỏa: G2 PASS scope hẹp (`df42f81`) rồi managed-SOT fault matrix đóng đủ (mục 4b). **[HISTORY — superseded: "SUBSET fault-injection HOÀN TẤT — G3 KHÔNG được promote" (đầu 2026-09-06); phần G2 superseded sớm hơn — `p2-handoff.md` mục 6b.]** `p0/p1/p2-handoff.md` giữ nguyên như lịch sử bất biến; `status.md` là bảng trạng thái sống.

## 1. Baseline & phạm vi

- Branch `feat/python-c-monorepo-phased`: `a61a62d` "feat(provider): bind managed execution without circular freshness" + `8131295` (managed publication failure) + `8d83f64` (ledger concurrency).
- Additions ĐÃ COMMIT trên `a61a62d`: `8131295` (managed publication failure) + `8d83f64` (ledger concurrency) — `tests/test_cbm_managed_provider.py` (+3 tests: 33 → 36), `tests/test_monorepo_ledger_concurrency.py` (MỚI, 3 tests). **Review HOÀN TẤT — no blockers** (36 managed + 3 concurrency independently tested). Receipt 203 passed REMAINS VALID sau commits.
- Phiên viết handoff: docs-only — KHÔNG chạy native, KHÔNG sửa production, KHÔNG commit; chỉ sở hữu `p3-handoff.md` (MỚI) + cập nhật receipt trong `p2-handoff.md`/`status.md`.

## 2. Receipt đo thật (main, exit code thật)

- `.venv/bin/pytest tests/test_cbm_managed_provider.py tests/test_managed_execution.py tests/test_managed_runtime.py tests/test_cbm_exact_compatibility.py tests/test_cbm_adapter.py tests/test_cbm_snapshot_p2.py tests/test_monorepo_snapshot_adversarial.py tests/test_monorepo_ledger_concurrency.py -q -p no:cacheprovider` → **203 passed, exit 0, 33.25s**.
- Ruff scoped: `src/sot_graph/providers/codebase_memory.py` + `tests/test_cbm_managed_provider.py` + `tests/test_monorepo_ledger_concurrency.py` = **pass**; gitdiff-check clean.
- SOT health sau commits (exit code thật): `sot reconcile` exit 0 — 5 updated / 420 unchanged / 0 failed; `sot doctor` exit 0; `sot diff-impact HEAD~2` exit 0 — receipt `583ed0cb4ea4c46003a98af9dd8b0177326c2399295996e793363635668026a6`.
- Toàn bộ mocked / fake-runner / SQLite-thật-với-failure-injection — **không test nào gọi binary native thật**.

## 3. Fault subset HOÀN TẤT (4 mệnh đề, đúng phạm vi đo được)

1. **Samehead / không native head → UNBOUND:** khi native head KHÔNG có (kể cả trường hợp prior head đã trùng khớp từ lần trước), provider KHÔNG publish binding nào và kết quả KHÔNG bao giờ được đánh dấu fresh — fail-closed, không suy diễn freshness từ prior head. Test anchor: `TestPriorBindingHeadRegression.test_matching_prior_head_without_native_head_not_fresh`.
2. **DB thật fail tại bước binding → rollback staged run:** với connection SQLite thật được inject failure tại điểm publish binding, staged run bị ROLL BACK; prior binding + prior evidence + notes GIỮ NGUYÊN như trước run. **Lưu ý semantics (bắt buộc):** sau DB failure KHÔNG có receipt mới nào được persist — không được mô tả/báo cáo "receipt đã lưu" trong trường hợp này; chỉ prior state tồn tại trên disk. Test anchor: `TestLedgerFailurePublication.test_transaction_failure_preserves_prior_ledger` (helper `_FailingConn`).
3. **Managed trả `publication_failed`, legacy status unchanged:** failure tại publication surface ra trạng thái riêng cho đường managed; legacy outcome status KHÔNG bị đổi meanings — hai vocabulary tách bạch, không fallback im lặng.
4. **3 test thread-concurrency:** `tests/test_monorepo_ledger_concurrency.py` — phản sinh đường đua thread tại boundary publish binding/ledger bằng **SQLite THẬT + thread thật** (KHÔNG mock ledger; deterministic trong suite).

## 4. Hạn chế ghi tại thời điểm CHƯA đóng G3 (history — một phần superseded bởi mục 4b)

- **G3 NOT promoted.** Điều kiện chưa đủ: (a) G2 chưa PASS — còn đúng 1 gap: isolation/orphan unsafe-success proof (gap live provider acceptance ĐÃ ĐÓNG: native PASS exit 0 tại `8d83f64` qua binding — `evidence/p2-provider-acceptance.md`; gate cho phép `cancellation_unknown` + quarantine nên terminal-daemon KHÔNG bắt buộc; host scope honest là đủ, CLI/installer thuộc P4/P5) **[SUPERSEDED 2026-09-06: G2 = PASS scope hẹp — inventory process đo được, `p2-handoff.md` mục 6b; điều kiện (a) ĐÃ thỏa scoped, chỉ còn (b)];** (b) full fault matrix G3 chưa hoàn tất — **specifics G3** (`execution-plan.md` §4): false-fresh adversarial; crash-at-commit (crash không tạo successful run thiếu evidence); stale-supersede (old evidence không bị supersede bởi failed sync); fault injection tại native completion + ledger commit boundary. Một phần đã có từ `86c97fc` (unborn head, linked worktree, mutation giữa captures, failed-sync supersede) + subset mới mục 3. **SIGINT/non-daemon/reindex-during-cancel là việc KHÁC — không tính vào matrix G3.** **[SUPERSEDED 2026-09-06: (b) ĐÃ đóng đủ — mục 4b; G3 = PASS scope hẹp.]**
- **Hạn chế giai đoạn sau (không phải blocker gate hiện tại):** native fault injection (native completion boundary) thuộc phần còn lại của matrix; toàn bộ suite hiện tại mocked/real-SQLite trên 1 host macOS arm64; full-platform native proof = giai đoạn P4/P5 theo khai báo scope trung thực.
- Không suy diễn hành vi native thật từ mocked tests; các mệnh đề mục 3 là hành vi SOT-side (provider/ledger), không phải chứng minh native 0.10.8.

## 4b. Cập nhật 2026-09-06 — G3 = PASS scope hẹp (managed-SOT fault matrix ĐÓNG ĐỦ)

- **Audit độc lập read-only `c4bbb61b`: G3 PASS** — mapping đủ 5 mệnh đề matrix, mỗi mệnh đề có test/commit riêng:
  1. Source-inside successful completion (không false-fresh qua completion drift): `tests/test_managed_snapshot_boundaries.py` MỚI @ `41e855d` (2 tests, 190 dòng).
  2. Real DB publication failure → rollback giữ prior state: `8131295` (mục 3.2).
  3. Snapshot adversarial (unborn head, linked worktree, mutation giữa captures, failed-sync supersede): `86c97fc`.
  4. Ledger concurrency (thread race tại boundary publish binding/ledger): `8d83f64` (mục 3.4).
  5. Orphan writer unsafe-success refuse: `b08f0de`.
- **Receipt main (exit code thật): 10 file → 207 passed, exit 0, 40.39s** = 8 file trước + `tests/test_managed_orphan_writer.py` + `tests/test_managed_snapshot_boundaries.py`. Ruff file mới pass; **review 0 blocking**.
- **Scope trung thực:** G2 = PASS scope hẹp, commit `df42f81` (docs + inventory evidence + harness fix). Native 0.10.8 không expose native head → binding vẫn **UNBOUND** (`snapshot_bound=false`); **KHÔNG claim release hay native CI**. G3 PASS cũng scoped: matrix managed-SOT (mocked/real-SQLite failure injection), 1 host macOS arm64 — KHÔNG phải proof native 0.10.8.
- **Readiness: P4 research/implementation** — KHÔNG phải G4.

## 5. Điều kiện resume

1. **Commit + review ĐÃ XONG:** `8131295` + `8d83f64` đã vào lịch sử; review độc lập hoàn tất no blockers. Bằng chứng mục 2–3 là trạng thái committed, không còn worktree-pending.
2. **Đóng G2 trước** theo điều kiện liệt kê trong `p2-handoff.md` mục 6–7 (native rerun tại HEAD, đa host hoặc tuyên bố 1-host experimental tường minh, terminal-daemon/orphan evidence, quyết định surface + trust policy). **[SUPERSEDED 2026-09-06: G2 = PASS scope hẹp (`p2-handoff.md` mục 6b) — điều kiện này ĐÃ thỏa; bước kế = mục 3 dưới.]**
3. **Sau G2:** hoàn tất full fault matrix P3 còn thiếu rồi mới xét gate G3 (nguyên văn gate: không false-fresh trong adversarial suite; crash không tạo successful run thiếu evidence; old evidence không bị supersede bởi failed sync). **[SUPERSEDED 2026-09-06: G2 PASS scoped `df42f81` + G3 PASS scoped (mục 4b, audit `c4bbb61b`) — bước kế = P4 research/implementation.]**
4. Ràng buộc bất biến giữ nguyên: không đổi các handoff trước; golden `tests/fixtures/cbm_golden` không đổi; không lặp negative control no-pre-seed khi có native. (Commit có authorization rõ của user.)
