# Kế hoạch thực thi P0–P7: Monorepo Python + C (SOT + CBM)

- Ngày: 2026-09-05. Tài liệu dẫn nguồn gốc: [`plan/python-c-monorepo-architecture-plan-2026-09-05.md`](../python-c-monorepo-architecture-plan-2026-09-05.md) (giữ nguyên ước lượng **26–47 engineer-days**, chuỗi promotion và gates).
- Phạm vi file này: mục tiêu giai đoạn, gói công việc, gate, luật sở hữu song song, checkpoint bàn giao. Chi tiết thiết kế thuộc tài liệu gốc; file này không thay thế.

## 0. Luật vận hành (áp dụng mọi phase)

1. **Sở hữu file:** một file chỉ được một agent sửa tại một thời điểm. Không sửa đồng thời cùng file; phân công qua work-package, mỗi PR một concern (contract XOR lifecycle XOR schema).
2. **Reviewer độc lập:** mọi phase cần reviewer không phải người viết; reviewer xác minh bằng chứng trên disk (filesystem = SSOT), không tin mô tả.
3. **Chuỗi promotion nghiêm ngặt:** `P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7`. Không promote trước khi gate của phase hiện tại đạt bằng bằng chứng ghi trong `status.md`. Chuẩn bị song song (corpus P6, packaging research P4) được phép sau P0 nhưng không promote sớm.
4. **Checkpoint bàn giao:** kết thúc mỗi phase, **TẠO MỚI file `pN-handoff.md` riêng cho phase đó** (p1-handoff.md, p2-handoff.md, …). **KHÔNG đổi tên hay ghi đè các handoff trước** — `p0-handoff.md` và mọi handoff sau đó được giữ nguyên vẹn như lịch sử bất biến; `status.md` là bảng trạng thái sống duy nhất. Handoff phải tự đủ (self-contained): baseline commit, đường dẫn bằng chứng, lệnh đã chạy + exit code thật, blocker, quyết định mở, điều kiện resume — người nhận không cần đọc lại hội thoại. **[Cập nhật 2026-09-05 theo user authorization: checkpoint không còn bắt buộc STOP chờ reviewer ngoài — tự động advance khi gate đạt và bằng chứng được ghi trên disk đầy đủ (path + exit code thật); reviewer độc lập xác minh tập trung ở final quality review cuối phiên. Quy tắc bằng chứng không thay đổi: gate chỉ pass khi có receipt thật.]**
5. **Honesty gates:** mọi claim `[EVIDENCE]` phải có path:line hoặc digest; `[INFERENCE]` phải được đánh dấu. Gate BLOCKED > gate "pass bằng giả định".
6. Không commit/stash hộ người dùng; không tương tác native toàn cục (global daemon/config) nếu chưa chứng minh scratch isolation.

## 1. P0 — Baseline, compatibility spike, ADR (2–3 ngày)

**Mục tiêu:** khóa baseline chính xác — biết binary/operation nào được hỗ trợ, không còn giả định.

Work packages:
- WP0.1 Ghi baseline git/env, hash binary đã cài (không chạy), hash golden suite bằng thuật toán tái lập. **[ĐÃ LÀM — xem status.md]**
- WP0.2 Phân định identity wrapper/payload; đối chiếu claimed pin `0.10.8@010569f` với payload thực tế. **[IDENTITY CLOSED — release-manifest binding + byte-identity: `evidence/provenance-upstream.md`; build commit thật = tag `v0.10.8` → `46ae198f`, golden `@010569f` là mis-attribution]**
- WP0.3 Spike chạy sống an toàn trên scratch repo (lifecycle, cancellation, artifact side effects). **[DONE 2026-09-05 live, scope hẹp — `evidence/wp03-live-spike.md`; raw mirror `evidence/wp03-spike-receipts.txt`; baseline 4/15 native tools live-verify qua 6 scenarios, cancel đo trong 2 scenario SIGKILL n=1, daemon latency chưa đo]**
- WP0.4 Audit license/packaging/source availability của candidate `3c7427e`. **[DONE — MIT + notices đầy đủ; upstream pin chuẩn = `v0.10.8` = `46ae198f`; distribution repo = `DeusData/codebase-memory-mcp`; candidate `3c7427ef…` clone sẵn ở scratch (1.5 GB / 2119 files)]**
- WP0.5 Bằng chứng CI (config) + chạy test mocked/golden tại chỗ. **[ĐÃ LÀM]**
- WP0.6 ADR: hướng đã chấp nhận vs quyết định còn mở. **[ĐÃ LÀM — draft]**
- WP0.7 Tool-schema inventory + operation compatibility matrix + runtime capability report (historical/mock vs live-unknown, blocker ledger). **[ĐÃ LÀM — live: baseline subset đo được, còn lại UNKNOWN; ledger B1 CLOSED, B2 CLOSED, B3 MỞ]**

**Gate G0 (nguyên văn tài liệu gốc):** biết chính xác supported binary/operation; không còn giả định kill CLI = cancel worker. Nếu candidate không đạt thì giữ baseline, không nâng version chỉ theo tên.
**Trạng thái G0 hiện tại: PASS — baseline subset, scope hẹp (2026-09-05).** Supported binary = installed `996bad5f…` (release v0.10.8 content, identity closed qua release-manifest binding — user authorization: external attestation không bắt buộc). Supported native tools = **4/15** live-verified trên scratch (index_repository, search_graph, index_status, list_projects — đo qua 6 scenarios gồm version probe và 2 biến thể index; `evidence/wp03-live-spike.md` mục 8); **11/15 tool = UNKNOWN**. Giả định kill CLI = cancel worker ĐÃ bị xóa bằng đo thật (2 scenario SIGKILL, n=1; daemon supervisor tự cancel worker). Limits (watcher/UI off, cancel latency, 11 tool UNKNOWN, git-binding G0-B3) chuyển thành yêu cầu G2/P3 chưa implement. **Platform: Darwin arm64 = experimental spike ONLY — KHÔNG phải supported release platform; không native CI support claim; CI/storage budget CHƯA duyệt (chưa có measurement tách source/.git/build).** **ADR: ACCEPTED chỉ cho P1 limited subset** (autonomous authorization + independent review; checklist P0 incomplete = hard P4 prerequisites — mục D ADR). Round tài liệu này = **docs-only pass** (không native execution bởi agent authoring; spike kế thừa run agent trước). Raw receipts mirror: `evidence/wp03-spike-receipts.txt` (gồm failed/cancelled runs). Addendum hiện trạng: `p0-handoff-addendum.md`.

## 2. P1 — Chuẩn hóa contract, chưa đổi topology (3–5 ngày)

- Tái sử dụng `provider_contract.py`, `providers/base.py`, `normalization.py`; tách native envelope parsing / normalized outcome / trust assessment chỉ khi dependency map chứng minh phù hợp.
- Bổ sung capability-specific compatibility metadata; unsupported phải explicit.
- Golden fixtures: success/error/malformed/truncated/unknown fields/version mismatch; SOT CLI và MCP cùng interpretation.
- **Gate G1:** toàn bộ fixture/contract tests pass; output hiện có không đổi ngoài extension version hóa; no silent fallback.

## 3. P2 — Managed lifecycle và mutation isolation (4–8 ngày)

- Adapter dùng runtime helper hiện có hoặc module hẹp mới; không viết process manager song song với `proc.py`.
- Profile namespace riêng, disable background writes + artifact export theo capability đã kiểm chứng ở G0.
- Timeout/cancel/status/quarantine semantics; test native job sau khi client chết.
- **Gate G2:** query không đổi source/index generation/ledger; không đụng global daemon/config; cancellation được confirm hoặc báo unknown an toàn; no orphan writer báo success.

## 4. P3 — Snapshot và ledger integrity (4–7 ngày)

- Ban đầu dirty → stale; chuẩn hóa pre/post verification, generation availability, failure stage.
- Test: source đổi giữa parse/verify/commit, linked worktree, rename/delete, missing HEAD.
- Atomic run/binding/evidence, append-only history, immutable invalidation reason; fault injection ở native completion và ledger commit boundary.
- **Gate G3:** không false-fresh trong adversarial suite; crash không tạo successful run thiếu evidence; old evidence không bị supersede bởi failed sync.

## 5. P4 — Nhập source và packaging (3–5 ngày)

- **HARD PREREQUISITES (nợ P0 explicit — `adr-p0-baseline.md` mục D):** (a) grammar/generated inventory: phân loại generated grammar vs handwritten source; (b) source/git/build budget breakdown: tách source vs `.git` vs build artifacts vs binary vs cache từ số đo 1.5 GB clone — CI/storage budget chỉ quyết sau khi có; (c) independent publisher signature verification (sigstore bundle verify — hiện chỉ observed presence, trust = GitHub TLS same-channel checksum, `evidence/provenance-upstream.md` mục 8).
- Nhập upstream đã pin vào subtree sau G0–G3; giữ Python layout; manifest/build provenance/notices.
- Không build mọi grammar trên mọi Python test; native CI theo path filters + release matrix.
- External binary mode chỉ admin/developer opt-in; managed install explicit — không download-on-query, không PATH discovery, không public CBM shim.
- **Gate G4:** clean checkout build/install trên từng platform tuyên bố; working Python package không cần C toolchain khi dùng prebuilt; offline/no-engine fallback rõ ràng; GS-SURFACE phần installation đạt từng platform/harness.

## 6. P5 — End-to-end và vận hành (3–5 ngày)

- Một SOT entry point; doctor/status báo engine digest, compatibility, lifecycle, snapshot limitations.
- Test install/missing runtime/incompatible runtime/upgrade/rollback trên scratch stores; no-global-config-write qua filesystem manifest.
- Snapshot public MCP tools/resources/prompts/help/completions; mọi failure stage có remediation, không raw-native passthrough.
- **Gate G5:** acceptance scenarios mục 9 + toàn bộ GS-SURFACE pass; không giảm trust để che provider failure.

## 7. P6 — Benchmark và rollout opt-in (3–5 ngày)

- Builtin-only vs CBM qua cùng SOT verification, cùng corpus/commit; thu cold/warm/full/incremental/read latency, resources, correctness.
- Đăng raw artifacts, exclusions, failures, corpus hashes; không tuning trên frozen holdout.
- **Gate G6:** đạt tiêu chí mục 10; ưu tiên CBM theo language/task có bằng chứng, không bật toàn cục.

## 8. P7 — Release hygiene và handoff (1–3 ngày)

- Release checklist, compatibility support window, runbook vận hành, rollback rehearsal; diff-impact + full relevant tests + license review; known gaps vào changelog.
- **Gate G7:** rollback drill thành công, không mất notes/evidence, supported platforms khớp CI.

## 9. Dependency và song song

- Chuỗi cứng: P0→P1→P2→P3→P4→P5→P6→P7. P2 là điểm bất định cao nhất.
- Song song được phép (sau P0, không promote): corpus P6, packaging research P4, fixture authoring P1 — mỗi việc một agent, không trùng file.
- Ước lượng tổng giữ nguyên tài liệu gốc: **26–47 engineer-days** (23–41 cơ sở + 3–6 dự trù GS-SURFACE/installer/coexistence); hiệu chỉnh tại P0 khi platform/harness chốt — P0 hiện BLOCKED nên chưa hiệu chỉnh.

## 10. Gói song song theo phase (owner + test package)

Mỗi phase chốt bằng **STOP checkpoint**: reviewer độc lập xác nhận gate trước khi phase kế bắt đầu. Bên trong phase, các gói dưới đây chạy song song được — mỗi gói một owner, **không hai gói sửa cùng một file**, điểm giao duy nhất là file handoff/status do phase-lead viết.

| Phase | Gói song song (owner → deliverable) | Tiền đề nội bộ | Test package |
| :--- | :--- | :--- | :--- |
| P1 | (a) Contract freeze (owner A) → envelope/normalized outcome module; (b) Fixture authoring (owner B) → success/error/malformed/truncated/unknown-field/version-mismatch goldens — **chỉ viết sau khi (a) freeze schema**; (c) CLI/MCP parity check (owner C) → cùng interpretation | B, C sau A-freeze | fixture/contract suite; parity diff CLI vs MCP |
| P2 | (a) Lifecycle implementation (owner A) → runtime helper/profile namespace; (b) Isolated tests (owner B) → timeout/cancel/quarantine/orphan-writer suite — **sau khi interface A chốt**; không đụng store toàn cục | B sau A-interface | native-job-survives-client-death test trên scratch |
| P3 | (a) Snapshot/binding (owner A); (b) Ledger integrity (owner B); (c) Fault-injection suite (owner C) — **không shared writes**: mỗi owner scratch store/db riêng, chỉ gặp nhau ở adversarial suite chung | song song toàn bộ, C sau A+B API | adversarial false-fresh, crash-at-commit, stale-supersede |
| P4 | (a) Manifests/notices/provenance (owner A); (b) Packaging + CI wiring (owner B) — **sau khi A có manifest**; path filters + release matrix | B sau A-manifests | clean-checkout build/install từng platform; GS-SURFACE installation |
| P5 | (a) Doctor/status surface (owner A); (b) Lifecycle E2E install/upgrade/rollback trên scratch stores (owner B); (c) Harness/agent-surface tests (owner C) → GS-SURFACE | B, C sau A surface schema | acceptance mục 9 + toàn bộ GS-SURFACE |
| P6 | (a) Corpus prep — **song song chỉ sau G0 mở** (owner A); (b) Measurement — **hardware đo có kiểm soát, SEQUENTIAL**, một máy một lần đo, không tuning trên holdout (owner B) | B sau A corpus frozen | raw artifacts + corpus hashes đăng kèm exclusion/failure |
| P7 | rollback rehearsal + release checklist (tuần tự, một owner) | sau G6 | drill: không mất notes/evidence |
