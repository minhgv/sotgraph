# Kế hoạch hoàn thiện theo mục tiêu — 2026-09-06

Trạng thái: LOCAL FIXES VERIFIED, chưa release PASS. M1 INCONCLUSIVE; M2 BLOCKED; M3a–c scoped acceptance đã commit; M4 packaging PASS_SCOPED và lifecycle v6 SUPPLEMENTAL_PASS (17/17 commands), v4/v5 failures preserved; M5/M6/M7 external gates BLOCKED. Bằng chứng và checkpoint hiện tại ở mục 13 bên dưới. Kế hoạch bổ sung `execution-plan.md`, không thay ngưỡng hoặc ghi đè bằng chứng/handoff lịch sử. Yêu cầu điều phối: hoàn thành từng mục tiêu, nhiều agent song song trong cùng mục tiêu, main agent tự commit từng checkpoint; không push/merge hoặc chạy remote workflow khi chưa được duyệt.

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

## 13. Local execution receipt — 2026-09-06

Scope: Darwin arm64 / Python 3.14.6 only; no remote actions, downloads, publication, global native adoption or release signoff. Evidence root: `evidence/completion-goals/M4/20260906-surface-v1/`.

- M3c acceptance: `b7c1fe1`, `ff40695`, 2130 passed / 4 skipped; runbook pending wording corrected. M4 baseline full suite: 2198 passed / 4 skipped (freeze.md); runner-only corrections subsequently pass 14 tests plus scoped Ruff/Pyright. Whole quality remains FAIL on 10 baseline provider type errors, not release PASS.
- Checkpoints: `f001e1f` runner disjoint layout; `e9828a9` committed v2 manifest/previous receipts; `d15e187` v3 records-only registry input; `3cbea72` short runtime root/v4 freeze; `dddc903` actual v4 receipt. Each rerun manifest committed before execution; no timeout or production validator relaxed. v1–v4 failures remain immutable.
- v1 refused overlapping evidence/config paths; v2 refused legacy registry envelope; v3 refused Darwin socket108 >104-byte budget. v4 fixed only runner root basename to `r`; native import/promote/register/prepare/probe/sync succeeded, then search abstained (exit1). Downstream status/recovery/rollback/disable/uninstall were not attempted. Fixtures preserved and source_drift false. Exact underlying search outcome is not retained by the redacted CLI; next diagnostic requires a new frozen protocol, not speculative parser/security edits.

### M4 SUR-01..12 scoped matrix

All rows are local supplemental evidence, not full GS-SURFACE acceptance. Tests below are `tests/test_completion_surface_{packaging,provider,harness}.py` and `tests/test_surface_lifecycle_runner.py`; freeze.md records packaging23/provider10/harness22 and baseline runner13, updated runner14.

| Row | Actual evidence | Acceptance / remaining gap |
| --- | --- | --- |
| SUR-01 | Packaging behavioral suite; packaging-live receipt16 commands | PASS_SCOPED local wheel/setup; other platforms BLOCKED |
| SUR-02 | Provider catalog/invocation/policy behavioral tests | PASS_SCOPED synthetic; ordinary persisted native CLI/MCP live BLOCKED |
| SUR-03 | Packaging entrypoint/help/completion behavioral tests and live install | PASS_SCOPED tested shell/entrypoint scope; actual client apps BLOCKED |
| SUR-04 | Harness generated-help/onboarding tests | PASS_SCOPED generated resources; actual clients BLOCKED |
| SUR-05 | Provider failure/remediation tests | PASS_SCOPED synthetic; v4 search safely abstains, successful recovery live incomplete |
| SUR-06 | Offline wheel/poisoned upstream hook build in full-suite freeze | PASS_SCOPED configured offline backend; not all source/platform builds |
| SUR-07 | Harness injection/exclusion/content-authority tests | PASS_SCOPED synthetic; no native instruction-authority promotion |
| SUR-08 | Packaging coexistence tests; retained legacy sentinel in v4 | PASS_SCOPED scratch; host-wide process lifetime noninterference BLOCKED |
| SUR-09 | Packaging upgrade/race/rollback/uninstall tests | PASS_SCOPED synthetic; native end-to-end operations after v4 search NOT RUN |
| SUR-10 | Provider workspace/version-isolation tests | PASS_SCOPED synthetic; distinct native-version drill BLOCKED |
| SUR-11 | Provider quarantine/env/PATH/UI/network-injection tests | PASS_SCOPED synthetic; descendant lifetime/network coverage BLOCKED |
| SUR-12 | lifecycle-live-v4/receipt.json:8 commands, seventh sync successful, eighth search refused | FAILED/incomplete live E2E; no same-artifact rollback or uninstall claim |

### M5 prerequisite/protocol — BLOCKED, specification only

Available release2412e017 and scratch8953ad08 share native source pin46ae198f; distinct bytes do not establish versions/schema. Prior distinct-artifact rollback was synthetic, not a native schema downgrade. Native get_schema is graph labels/count introspection, not index-format version; SOT SQLite v8 is unrelated. No genuine old/new artifact pair, format compatibility mapping or live dual-version fault harness is available. Do not acquire artifacts without separate permission.

Before a future drill freeze two genuine version pins, binaries/digests/provenance, exact operation registries, explicit old/new index compatibility declarations, isolated namespaces and refusal criteria. Capture notes/evidence/index hashes and process ownership before upgrade; test compatible and incompatible indexes, refusing the latter before open; query old → upgrade/query new → rollback/query old through SOT. Preserve both namespaces and old index; restore old generation or rebuild a new namespace, never overwrite retained indexes. Unknown format compatibility blocks execution. Synthetic fault cases remain supplemental, not live proof.

### M6 prerequisite/protocol — BLOCKED, no benchmark executed

M1 remains INCONCLUSIVE and M2 has no evidence-backed optimization. M4 successful live query/recovery is also missing. Small non-Python fixtures are not representative corpora. Require licensed/pinned local corpora in all four language groups, explicit file selections/hash manifests, independently fixed oracle and held-out evaluation split, descendants-aware resource measurement or explicit resource BLOCKED. Freeze §9 thresholds, at least5 index runs/30 queries per workload, cold-state definition (OS cache unknown if uncontrolled), hardware and per-task engine/SOT timing before any exclusive run. No fabricated results, performance win or preferred rollout; builtin remains default.

Final continuation scoped validation: **69 passed** with the original pinned offline setuptools backend; unconfigured run **68 passed / 1 skipped** is separately retained. Ruff/Pyright/claims clean. Doctor healthy schema8/no orphan nodes. Working-tree impact remains **STALE/open** due preserved untracked packaging scratch sources; this is not graph closure or release assurance. Coordinator confirmed no other active tests/builds/writers throughout all exclusive slots. Final command/exit/hash receipt is `final-local-receipt.json` in the M4 evidence root.

### M7 local hygiene / release decision

Local checkpoints/evidence only. Exact JSON evidence allowlists were force-staged because repository ignores JSON; packaging live venv/home/workspaces are not included. Preexisting untracked `plan/remaining-work-phased-plan-2026-09-05.md` remains untouched. Retained scratch states are not implicitly deleted or adopted. Supported-platform/remote CI/legal/release-owner signoff remain BLOCKED; G4/G5/G7 are not release-certified and historical G6 speed FAIL is unchanged. New live search refusal remains a known operational gap, not hidden by scoped unit-test success.

### 2026-09-06 local completion addendum (supersedes current blockers above, not historical receipts)

- Exact cause established by frozen v5 private harness outcome: `unsupported_managed`, duration 0 ms, because harness requested limit 5 while the evidence-backed managed wire contract is fixed at 20. No native query ran at the failing stage. Production redaction, query read-only behavior, authority, quarantine, and timeouts were unchanged.
- Frozen v6 corrects only harness limit to 20. `lifecycle-live-v6/receipt.json` is **SUPPLEMENTAL_PASS**, all 17 commands exit 0: import/promote/register/prepare/probe/sync/search/status, same-artifact rollback/re-register/prepare/probe/search/status, disable/uninstall. Fixtures and legacy sentinel preserved; source drift false. This closes the v4 live search gap and SUR-09/12 explicit-administrator drill, not genuine distinct-version/schema rollback or ordinary persisted OS-account CLI/MCP acceptance.
- All ten provider Pyright errors fixed using explicit optional-runtime/marker/fixture invariants, not suppressions. Checkpoints `d99298f`, `210ccdd`, `0a85ee3`, `0a4e544` preserve type fixes, diagnostic freezes, failed v5 and successful v6 receipts.
- Final configured source suite: **2199 passed / 4 skipped**; isolated detached worktree suite: **2199 passed / 4 skipped**. Skips require root chown, case-sensitive filesystem, and Windows Job Objects (2). Earlier unconfigured run: 2198 passed / 5 skipped (offline packaging backend missing). Pinned cached setuptools path/hash retained from environment.json; no downloads.
- Whole quality gate passes with `UV_OFFLINE=1`: Ruff, Pyright, coverage **core 88% / receipts 94%**, Bandit, pip-audit (no known vulnerabilities). Harness-specific Ruff/Pyright and claims lint pass. Existing pytest collection/deprecation warnings remain informational, not test failures.
- Scratch remains on disk. Exact `.gitignore` exclusions cover only retained packaging-live/home and packaging-live/workspaces, matching runtime exclusion policy; receipts remain tracked. Reconcile removed 9 obsolete scratch projections, doctor schema8 healthy/no orphans. Working-tree impact is **closed / ASSURED_WITHIN_SCOPE**, no stale files. Untracked user plan hash unchanged.
- Full `main...HEAD` scope reviewed through numstat inventory, exact-source verification (2050 native entries, 1,332,757,092 bytes), 183 license/notice hashes (all match), Python wheel boundary inspection (96 entries, no engines/plan/native artifacts), and full tests. Generated parser source dominates 38.6M added lines. This is mechanical provenance/package verification, not a legal signoff or manual review of every generated line. Full-branch graph receipt remains **UNVERIFIABLE/open** due explicit 200-file cap, excluded vendor/parser scope and unresolved dynamic dispatch; do not confuse local working-tree closure with repo-wide proof.
- Local integration uses detached worktree `/tmp/sot-completion-integration-yalc57xy/worktree`, retained. `main` is an ancestor; nonmutating `git merge-tree main HEAD` exactly equals HEAD tree at `0a4e544`. No source-branch switch/merge, remote action, publication or deletion occurred.
- Durable final logs and hash receipt: `evidence/completion-goals/M4/20260906-surface-v1/local-completion-v7/`. M5 genuine old/new version+schema artifacts, M6 representative licensed corpora/oracles/measurement protocol, M1/M2 evidence-backed performance, isolated OS-account/client/platform evidence and M7 remote/legal/release-owner approvals remain prerequisites. No performance or release PASS claimed.

## 12. Kết thúc mỗi mục tiêu

Receipt ≤1 trang: mục tiêu/subtasks, author/tester/reviewer, file allowlist, HEAD/worktree hashes, commands/exits, acceptance code vs product, artifact paths/SHA, commit IDs do main tạo, rollback, và blocker cụ thể nếu có. Main báo rõ 'đã làm', 'đã test', 'chưa đạt' thay vì tuyên bố hoàn tất từ số lượng file hoặc test.
