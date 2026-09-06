# P4 Handoff — Bounded artifact foundation (2026-09-06)

**Trạng thái hiện hành: P4 CHƯA HOÀN TẤT — mới có foundation có biên (ArtifactStore), G4 tổng thể vẫn BLOCKED.**
Không tuyên bố P4 done, không tuyên bố release surface, KHÔNG tuyên bố storage/source budget đã được user duyệt.
Session viết handoff này: **docs-only — không chạy test, không chạy native, không commit.**

## 1. Baseline

- Branch `feat/python-c-monorepo-phased` @ `8ccfd1f` "feat(artifacts): stage verified owned binaries with atomic promotion" — commit cluster đã track trên branch chính của chuỗi phased (sau `9e28993` docs G3).
- Commit `8ccfd1f` chạm ĐÚNG 2 file MỚI: `src/sot_graph/providers/artifacts.py` (462 dòng) + `tests/test_managed_artifacts.py` (559 dòng, 36 tests). Không file production nào khác bị đổi; các handoff trước (`p0/p1/p2/p3-handoff.md`) giữ nguyên bất biến.
- Chuỗi gate đã có từ trước (scoped): G2 PASS `df42f81`, G3 PASS `41e855d` + docs `9e28993`. Chi tiết: `p3-handoff.md` mục 4b.

## 2. Receipt đo thật (main, exit code thật — từ session code, KHÔNG chạy lại trong session docs này)

- `.venv/bin/pytest tests/test_managed_artifacts.py -q -p no:cacheprovider` → **35 passed, 1 skipped, 0.36s, exit 0**.
- Suite adjacent có file artifacts, TRƯỚC khi thêm regression cuối về collision: **132 passed, 1 skipped, 8.04s** (receipt giữ nguyên, không rerun).
- Ruff scoped trên `artifacts.py` + test file = **pass**. Review độc lập HOÀN TẤT: **4 repairs + collision guard** (guard = dest rỗng bị trồng trong lúc staging bị refuse và preserve).
- **1 skip duy nhất:** test chown cần quyền root (`skipif geteuid != 0`) — skip đúng trên host dev không root.
- **Zero spawn:** toàn bộ test mocked — không test nào gọi binary native thật, không network, không process con.

## 3. ArtifactStore — semantics đúng như đo (nền tảng admin-local TRUSTED)

- API: `import_artifact` / `promote` / `resolve` (`src/sot_graph/providers/artifacts.py:289,391,433`). Nguồn vào = 1 file local explicit. **KHÔNG có**: CLI, download, PATH lookup, upstream installer, source-checkout import, uninstall/upgrade public.
- **Root private, disjoint:** root do admin cung cấp, absolute, không symlink, BẮT BUỘC nằm ngoài repo; root-inside-repo và repo-inside-root đều refuse; root tồn tại được validate (0700, euid-owned, no symlink) và KHÔNG BAO GIỜ chmod/prune/rewrite — version cũ, pointer, dữ liệu lạ đều preserve.
- **Digest + manifest immutable, stage atomic:** manifest schema CHÍNH XÁC `{schema_version, name, digest, platform, protocol, engine_commit}` — field lạ/thiếu, pin malformed, mismatch platform/protocol → refuse. Import stage vào temp unique trong root, stream-copy vừa hash, verify sha256 + size, rồi rename atomic thành executable immutable đánh địa chỉ theo digest; stage fail chỉ dọn temp do chính call đó tạo.
- **Unknown/existing refusal:** digest dir đã tồn tại trên disk được re-verify, KHÔNG overwrite, KHÔNG adopt khi unknown/incomplete; artifact đã cài bị tamper → refuse, không tự sửa.
- **TOCTOU same-uid residual (khai báo trung thực):** guarantee no-overwrite chỉ scoped cho user WriteLock hợp tác + state pre-existing detect được — KHÔNG phải sandbox chống racer same-uid ác ý (không renameat2/FFI).
- **Lock scope:** mutation serialize sau `WriteLock` trên `<root>/write.lock` (cùng discipline `providers.runtime._mutation`); promote pointer flip atomic, promote fail giữ pointer cũ.

## 4. Gaps (thành thật) — vì sao G4 vẫn BLOCKED

- G4 BLOCKED tổng thể, pending đủ các mảnh: **source import → build → license → platform → surface**. Foundation này chỉ che mảnh nhỏ nhất (staging binary admin-local); không mảnh nào trong 5 mảnh trên được đóng bởi `8ccfd1f`.
- **Source import: budget CHƯA được duyệt** — quyết định explicit per ADR mục B4 (platform/CI budget) + D2 (source/git/build budget breakdown, hard P4 prerequisite). Số đo candidate: clone source tại `3c7427e` = **1.37 GB, ~94% nội dung generated**. Quy tắc trung thực: KHÔNG trộn footprint candidate `3c7427e` với footprint release đã đo (`46ae198f`) — hai dataset đo riêng, không quy đổi hộ nhau.
- **Default base GIỮ release pin `46ae198f` (v0.10.8)** — KHÔNG dùng candidate `3c7427e` làm base. Candidate chỉ là dữ liệu measurement cho quyết định subtree.
- **KHÔNG có approval** cho: pruning ~80MB, submodule, hay biến thể source-topology khác. Đây là quyết định user explicit thật sự (đổi topology + budget), agent KHÔNG tự chốt, docs KHÔNG được ghi "user đã duyệt budget".

## 5. Rollback

- **Không có auto-deletion:** store không bao giờ prune/xóa artifact cũ, pointer cũ, hay dữ liệu lạ trong root; promote fail giữ pointer cũ → rollback logic-side an toàn theo thiết kế.
- Code rollback: `git revert 8ccfd1f` là self-contained (chỉ 2 file MỚI, không đụng code khác); không có migration hay state ngoài root admin (root do admin tạo, admin tự quản).

## 6. Cập nhật integration — `248a399`

- Thêm `providers/installation.py` và `tests/test_managed_installation.py`: factory `create_managed_installation` nối artifact đã promote/verify với exact compatibility context, profile, runtime và provider. API admin-local opt-in; không prepare, spawn, đọc cấu hình repo hay ghi ledger khi khởi tạo.
- Protocol artifact `artifacts-v1` tách biệt native protocol được kiểm chứng qua registry. Thiếu identity/operation evidence hoặc artifact bị sửa thì fail-closed, không fallback legacy.
- Kiểm tra repo thực tế, artifact store và runtime root không chứa nhau, trước khi resolve. Kiểm tra inode/ancestor bổ sung cho alias trên filesystem không phân biệt hoa thường; store dùng chung giữa các repo độc lập vẫn được phép.
- Main chạy `.venv/bin/pytest tests/test_managed_installation.py tests/test_managed_artifacts.py tests/test_managed_runtime.py tests/test_managed_execution.py tests/test_cbm_managed_provider.py -q -p no:cacheprovider`: **165 passed, 2 skipped, exit 0, 8.21s**. Skip: root-only chown và trường hợp yêu cầu filesystem phân biệt hoa thường. Ruff hai file pass; reviewer độc lập không còn findings sau sửa path overlap/alias.
- Full default suite trước integration tại `cf8d031`: **1,848 passed, 176 subtests passed, 3 skipped**, offline wheel/sdist build pass. Đây không phải full-suite receipt cho `248a399`; xem `evidence/branch-quality-gate.md`.
- Không merge: `main` vẫn ở `319a442`; user yêu cầu tiếp tục trên feature branch. G4 vẫn BLOCKED theo mục 4; chưa có public lifecycle hay native packaging.

## 7. Điều kiện resume

1. Đọc `adr-p0-baseline.md` mục B4 + D làm khung: 5 mảnh G4 (source import/build/license/platform/surface) phải đóng tuần tự có bằng chứng; foundation `8ccfd1f` là điểm start.
2. Source import: cần user quyết budget/topology TRƯỚC (không tự chốt); measurement mới phải tách source vs .git vs build vs cache, và ghi rõ dataset nào thuộc `46ae198f` nào thuộc `3c7427e`.
3. Không đụng: handoff cũ, golden `tests/fixtures/cbm_golden`, ADR; mọi claim mới phải kèm receipt exit-code thật; không claim native/platform support mới; Windows unsupported (mirror `providers.runtime`).
