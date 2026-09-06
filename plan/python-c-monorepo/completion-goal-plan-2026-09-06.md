# Kế hoạch hoàn thiện theo mục tiêu — 2026-09-06

Trạng thái: PLAN ONLY, chưa triển khai các mục tiêu bên dưới. Kế hoạch bổ sung `execution-plan.md`, không thay ngưỡng hoặc ghi đè bằng chứng/handoff lịch sử. Yêu cầu điều phối: hoàn thành từng mục tiêu, nhiều agent song song trong cùng mục tiêu, main agent tự commit từng checkpoint; không push/merge hoặc chạy remote workflow khi chưa được duyệt.

## 1. Baseline và phạm vi

- Nhánh `feat/python-c-monorepo-phased`, baseline commit `bbf38ab`; 14 checkpoint từ `0428c1b` đã commit.
- Full suite gần nhất: 1.944 passed / 4 skipped; độc lập review clean trong phạm vi đã sửa.
- Đã làm: full subtree release `46ae198f`, source verifier, build Darwin arm64, exact signed artifact acceptance, Python packaging, admin lifecycle, sync ledger, logical uninstall, pointer rollback, notes/evidence preservation, local surface tests và runbook.
- Còn: latency/benchmark chất lượng đại diện; persisted admin opt-in cho CLI/MCP thông thường; ma trận GS-SURFACE đầy đủ; bằng chứng native cross-version/schema; remote CI và quyết định release.
- G0–G3 giữ verdict scoped lịch sử. G4/G5/G7 chưa được chứng nhận release; G6 speed target FAIL lịch sử. Diagnostic n=3 khoảng 8,823s không thay benchmark 27s và không chứng minh đã tối ưu.
- Mục tiêu không bao gồm destructive garbage collection, FFI/Rust rewrite, thêm mọi native tool, hoặc bật CBM mặc định toàn cục.

## 2. Quy tắc thực thi mỗi mục tiêu

1. Main chốt packet: đầu ra, hợp đồng, file ownership, acceptance và danh sách file không được sửa. Search/reuse + pack tối đa khoảng 1.500 token trước giao code; explore/usages trước thay core symbols.
2. Tối đa **3 tác giả cùng ghi**, mỗi file một owner. Thường A viết implementation, B viết test/harness độc lập theo hợp đồng đã chốt, C chuẩn bị evidence/protocol hoặc integration trong file tách biệt. Không giao hai agent sửa `cli.py`, `mcp_service.py`, registry hoặc file runtime chung.
3. Reviewer riêng không sửa code; tester độc lập không tự chấm thay reviewer. Agent phụ trả receipt ngắn, không tự commit; lỗi trả đúng tác giả cũ.
4. Agent được chạy scoped unit tests khi không có slot measurement. Native/E2E dùng scratch HOME/config/store/runtime; main cấp **một slot đo độc quyền**, dừng test/build khác. Corpus prep có thể song song trước freeze; không chỉnh code/corpus trong lúc đo.
5. Khi production quiescent: scoped checks, review độc lập, full pytest, `scripts/quality_gates.sh`, claims lint theo CLI hiện hành, lint/type các file ngoài quality gate. Lỗi baseline phải được xác minh và ghi rõ; không gọi toàn gate PASS nếu chỉ scoped PASS.
6. Main tuần tự reconcile → doctor → diff-impact; kiểm tra snapshot và closure chứ không chỉ exit code. Lưu commands/exits/hashes/failures bền vững tại `evidence/completion-goals/M<n>/<run-id>/`; không ghi đè run cũ.
7. Main stage đúng allowlist và commit ngay sau acceptance, thường một code/test checkpoint và một evidence/docs checkpoint; không tích lũy qua mục tiêu kế tiếp. Manifest benchmark phải commit trước đo. Commit không đồng nghĩa gate release PASS.
8. Chỉ có một mục tiêu implementation đang mở. Nếu BLOCKED thật: ghi prerequisite cụ thể, checkpoint phần hoàn chỉnh, dừng nhánh phụ thuộc; main có thể chuyển sang mục tiêu độc lập được ghi trong dependency bên dưới. Không để blocker remote làm dừng việc local độc lập.
9. Mặc định giữ builtin; `builtin_only` không native spawn; `require_external` fail-closed; `prefer_external` chỉ fallback theo policy và trả lý do rõ. Query không tự prepare/index/sync/ghi ledger. Không bỏ runtime lock/quarantine hiện có dưới danh nghĩa read-only; phân biệt mutation lock của graph với khóa bảo vệ runtime.
10. Không cache integrity bằng size/mtime, không tăng timeout để che regression, không nới ngưỡng sau đo; dữ liệu repo không được tự cấp quyền thực thi binary hoặc chọn trusted registry.

## 3. Thứ tự và dependencies

`M1 Chẩn đoán → M2 Sửa latency → M3 Opt-in tích hợp → M4 GS-SURFACE local → M5 Rollback phiên bản → M6 Benchmark đại diện → M7 CI và quyết định release`.

- M2 chỉ viết code khi M1 đủ bằng chứng. M3/M4 độc lập với việc G6 có speed win: được tiếp tục experimental opt-in, không promote preferred.
- M5 live drill phụ thuộc có hai artifact/protocol/schema thực sự khác và provenance/compatibility hợp lệ. Nếu thiếu, ghi BLOCKED và chuyển M6; không dùng hai digest cùng source làm bằng chứng schema khác.
- M6 acceptance cần code M2/M3 đã freeze và không còn lỗi safety M4. Prep corpus được làm read-only sớm, không đo/tune sớm.
- M7 chỉ release PASS nếu các predecessor bắt buộc đạt. Không giả định có quyền push/workflow hay chữ ký release owner.

## 4. M1 — Khép chẩn đoán latency bằng phép đo có thể lặp

**Mục tiêu:** giải thích chi phí native envelope và điều kiện tạo chênh lệch 27s/8,8s, không suy ra idle từ CPU thiếu descendants.

- A: diagnostic timestamp theo factory/artifact verification/guard/transport/startup/query/teardown; chỉ script mới và evidence, không sửa engine source pin.
- B: audit lifecycle Python và native source đúng manifest; vẽ timeline bằng bảng, kiểm tra số lần khởi động/kết thúc daemon và điểm chờ; không giả định enclosing Git HEAD là pin native.
- C: preflight/runner ghi hardware, software, env allowlist, trace/profile state, file/digest, cache và daemon trạng thái; đối chiếu run cũ nhưng không sửa artifact cũ.
- Main: ≥3 paired samples trong cùng environment, timeout và transport; chạy đơn luồng đo. Ghi phần không instrument được, không ép tổng thời gian giả về 100%.
- **Exit:** script lặp được, timeline có direct timestamps; phần dominant cost được đo đủ để lựa chọn một sửa cụ thể, hoặc verdict INCONCLUSIVE kèm điểm thiếu. M2 không bắt đầu nếu chỉ có suy đoán. Native log không đủ thì đề xuất build instrumented riêng, digest/manifest mới, không sửa âm thầm release.
- **Checkpoint:** `bench(latency): freeze repeatable phase diagnostic` và evidence kết quả.

## 5. M2 — Sửa đúng bottleneck, giữ process boundary và isolation

- A: một implementation owner sửa đúng đường đã chứng minh. Ưu tiên local fix hẹp; nếu startup/IPC thật sự dominant, thiết kế batching hoặc session-bounded persistent IPC trước FFI theo §10.4.
- B: regression/fault tests: tamper, crash, cancellation unknown, quarantine, hai workspace/version, no-global-daemon-contact; không sửa production của A.
- C: compatibility/transport contract và test differential đầu vào/đầu ra; giữ normalization/trust ceilings, digest binding, source/ledger invariants.
- **Chốt trước code nếu đổi lifetime:** ADR nêu ownership, expiry/shutdown, socket permissions, memory/process budget, no-public-listener và compatibility. Session-bounded managed transport khác global daemon; không tự cho phép daemon toàn cục. Genuine architecture/budget change cần user duyệt riêng.
- **Exit code:** safety/fault/differential suites đạt, review sạch, không integrity bypass. **Exit experiment:** paired diagnostic mới đo lợi ích với cùng protocol; không đặt nhãn G6 PASS từ microbenchmark. Không có lợi ích thì không giữ speculative optimization.
- **Checkpoint:** implementation+tests có biên; evidence before/after phiên bản mới. Coverage-first opt-in có thể tiếp tục dù không đạt speed, nhưng không được gọi performance win.

## 6. M3 — Persisted managed opt-in cho CLI/MCP thông thường

Chia ba micro-checkpoint tuần tự để tránh integration diff lớn:

### M3a — Trusted configuration
- A: loader/admin configuration trong file chuyên biệt; reuse `config.py`, registry, installation theo audit, không dựng runtime thứ hai.
- B: schema/security tests độc lập: default off, malformed/oversized config, paths overlap/symlink, repo cannot opt itself in, artifact/protocol mismatch.
- C: migration/disable documentation và config fixtures không chứa credentials.
- **Thiết kế mặc định:** administrator explicit registration lưu ngoài repo; có binding tới canonical project identity. Repo config chỉ có thể hạn chế policy, không chọn executable/registry hay nâng quyền. CLI và MCP đọc cùng hợp đồng. Không tự tạo thư mục/global config khi query.
- **Exit:** config đọc được sau restart; tắt opt-in phục hồi builtin không mất dữ liệu; không repo-induced execution.

### M3b — Shared dispatch rồi mới adapters
- Một owner shared factory/dispatch trước, freeze hợp đồng; sau đó A sở hữu CLI wiring, B sở hữu MCP wiring, C sở hữu parity/fault tests trong file riêng.
- Reuse installation + orchestrator + policy, không gọi CLI print handler như library API, không song song hai trust paths.
- **Exit:** `builtin_only` zero native spawn; `require_external` không silent fallback; `prefer_external` fallback có reason; CLI/MCP policy tương đương; query không auto-prepare/index/ghi ledger; vẫn khóa runtime đúng thiết kế.

### M3c — Status/recovery
- A: operational status/doctor binding; B: restart/disable/rollback integration tests; C: runbook cập nhật.
- **Exit:** chỉ operation SOT đã implement được dùng để remediation, không raw native next_action; restore config và namespace rõ; installation thiếu/incompatible/quarantined đều có đường recovery an toàn.
- **Checkpoint:** config, dispatch, status/recovery thành ba nhóm code/test riêng; main không gom tất cả M3 vào một commit.

## 7. M4 — Ma trận GS-SURFACE local đầy đủ

Lập matrix SUR-01..12 theo đúng §9.1, đối chiếu các test hiện có trước khi thêm. Ma trận ghi platform/harness cụ thể, test level (mock/live), artifact hash, PASS/FAIL/BLOCKED và lý do; không lấy static snapshot thay behavioral acceptance.

- A packaging owner: SUR-01/03/06/08/09 — scratch install/setup, entrypoints/completion, upstream hooks, coexistence, upgrade-race/rollback/uninstall; chỉ test/harness packaging riêng.
- B provider owner: SUR-02/05/10/11 — catalog/invocation/policy, failure remediation, workspace/version isolation, crash/quarantine, env/PATH/UI/network injection; không sửa runtime dùng chung song song nếu phát hiện lỗi, báo main cấp ownership sửa tuần tự.
- C harness owner: SUR-04/07 — generated help/onboarding không direct-CBM operation, dependency instructions không auto-load, default self-index exclusion; explicit source content vẫn untrusted.
- **SUR-12** là E2E setup/probe/sync/query/status/recovery/upgrade/uninstall chỉ qua SOT, không phải chỉ một chữ ký. Main chạy sau integrate A–C; release owner review evidence matrix, không giả ký thay người thật.
- **Exit local:** từng row có behavioral receipts hợp lệ cho môi trường đã đo, inventory process/listener/config before-after, dữ liệu có sẵn không bị sửa/adopt/kill. Local PASS không chứng nhận platform chưa chạy.
- **Checkpoint:** từng packet SUR độc lập sau acceptance; matrix tổng riêng. Remote rows chuyển M7, không gán PASS.

## 8. M5 — Rollback native khác phiên bản/schema

- A: xác định native index schema/protocol và hai phiên bản thực sự khác, provenance + exact operation evidence. Không nhầm SOT SQLite schema v8 với native index schema.
- B: fault harness dùng index cũ/mới, fixture khai báo rõ; tests tương thích/không tương thích, namespace separation và refusal trước mở index không phù hợp.
- C: preservation oracle cho notes/run/evidence và ownership/filesystem/process manifests; không tạo điểm chất lượng native từ synthetic evidence.
- Main chạy live upgrade → query → rollback → query với verified old/new binaries, restore old generation hoặc rebuild new namespace, không overwrite index cần giữ.
- **Exit:** live proof binary cũ không mở nhầm index mới, notes/evidence intact, namespaces/version binding đúng, refusal/remediation qua SOT. Mock tests và two-digest-same-source drill chỉ supplemental.
- **Blocked prerequisite:** hiện chưa xác minh có đủ cặp artifact/native schema. Chuẩn bị definition/test vẫn được commit; live gate BLOCKED cho tới khi có, không ép cung cấp artifact giả.

## 9. M6 — Benchmark đại diện và quyết định opt-in/preferred

- A corpus/oracle owner: bốn nhóm Python backend, TS/JS monorepo, C/C++ hoặc Rust, polyglot/generated/vendor/ambiguous. Ưu tiên repo có sẵn được phép; xác minh license/commit/hash/file selection. Dev vs evaluation tách rõ, cấm tune frozen unseen.
- B runner owner: engine-only và SOT end-to-end cùng scope/budget; cold cache state được định nghĩa đo được, warmup, full rebuild, changed-source incremental; ≥5 index runs, ≥30 queries/workload. Không purge OS cache toàn máy; nếu OS-cache cold không kiểm soát được phải ghi unknown và không claim true-cold.
- C quality/resource owner: task oracle precision/recall/ranking, abstention, false-fresh, partial/unresolved, response tokens; descendant CPU/RSS bao phủ có bằng chứng hoặc ô resource BLOCKED.
- **Freeze trước chạy:** commit manifest corpus/protocol/thresholds/hardware; main mới cấp exclusive benchmark slot. Interruptions giữ riêng, resume là segment rõ ràng; run lỗi không bị loại im lặng.
- **Acceptance theo §10.3:** zero false-fresh/ledger corruption; không mất case đúng frozen; workload target end-to-end p50 cải thiện ≥20%, p95 regression ≤10%, peak RSS tăng ≤20% trừ ADR coverage/quality đã chốt trước đo. Kết luận per-language/task, không aggregate che regression.
- **Kết quả hợp lệ:** PASS, FAIL hoặc BLOCKED từng cell; không hứa speed PASS. Coverage-first opt-in có thể là quyết định sản phẩm minh bạch theo §10.3, không được đổi nhãn performance FAIL. Rerun chỉ vì bug/protocol change phiên bản rõ, không thử tới khi may mắn PASS.
- **Checkpoint:** corpus/protocol trước đo; runner tests; raw measured results; verdict/rollout policy riêng.

## 10. M7 — Remote CI, release hygiene và quyết định cuối

- A CI owner: path-filtered workflows, scratch isolation/process/network audits, exact artifact checks and archive integrity; không coi hash output là reproducible-build proof, không so digest khác toolchain như cùng artifact.
- B release tester: clean-checkout source/prebuilt/no-engine packaging và install matrix, GS-SURFACE receipts theo từng harness/platform; so supported claims với kết quả thật.
- C docs/evidence owner: release checklist, compatibility support window, rollback runbook, license/provenance/notices packaging, final matrix và changelog known gaps; không bịa legal approval/chữ ký.
- **Remote boundary:** chuẩn bị/local commit được phép; push, dispatch workflow, publish/download/upload thay đổi phạm vi phải theo quyền thực tế và user approval khi cần. Không có remote run ⇒ BLOCKED chứ không FAIL code giả.
- **Exit:** G4/G5 bắt buộc có đủ artifact/platform/surface receipts; G6 verdict và policy đúng bằng chứng; G7 rollback/hygiene + supported matrix khớp CI, release owner xác nhận quyết định. Platforms chưa test loại khỏi supported matrix hoặc experimental; không miễn GS-SURFACE bằng ADR.
- **Checkpoint:** CI/test changes, measured remote receipts sau khi được chạy, final release decision. Không publish tự động.

## 11. Điểm cần user quyết thật sự, chỉ hỏi khi chạm

- Lifetime/global service/platform CI budget mới nếu giải pháp M2 vượt session-scoped opt-in và baseline đã duyệt.
- Quyền push/remote workflow/publish. Commit local từng chặng đã được yêu cầu; không suy ra quyền push.
- Artifact/version acquisition hoặc lựa chọn release support matrix nếu không thể suy ra từ artifact sẵn có và kết quả thực tế.
- Coverage-first opt-in/preferred exception phải chốt đúng policy, không tự nới ngưỡng speed sau đo.

Không cần hỏi lại việc builtin mặc định, CLI/MCP parity, giữ notes/evidence, hay full subtree đã duyệt. Không xem immutable historical docs chứa 'uncommitted' là trạng thái Git hiện tại; mỗi checkpoint mới ghi HEAD và evidence binding riêng.

## 12. Kết thúc mỗi mục tiêu

Receipt ≤1 trang: mục tiêu/subtasks, author/tester/reviewer, file allowlist, HEAD/worktree hashes, commands/exits, acceptance code vs product, artifact paths/SHA, commit IDs do main tạo, rollback, và blocker cụ thể nếu có. Main báo rõ 'đã làm', 'đã test', 'chưa đạt' thay vì tuyên bố hoàn tất từ số lượng file hoặc test.
