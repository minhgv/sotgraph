# Khảo sát repo và đề xuất roadmap tiếp theo

- Work ID: `2026-09-19-repository-roadmap-survey`
- Status: COMPLETED — khảo sát và đề xuất; roadmap chưa được triển khai hoặc phê duyệt.
- Next safe action: nếu người dùng yêu cầu triển khai, bắt đầu R-01, đóng baseline current HEAD rồi lập scope receipt cho R-02; không tự sửa mã từ hồ sơ khảo sát này.

## Context

Người dùng yêu cầu khảo sát repo sotgraph và đề xuất roadmap tiếp theo. Mục tiêu: xác định hiện trạng, những việc đã hoàn thành, các khoảng trống có bằng chứng và thứ tự đầu tư tiếp theo. Không sửa mã nguồn, không triển khai tính năng, không commit/push, không cài dependency hoặc truy cập ngoài workspace và ~/.omp. `docs/plans/` chưa tồn tại khi bắt đầu; các hồ sơ cũ trong `plan/` và `docs/` được khảo sát như bằng chứng lịch sử, không tự động tiếp tục triển khai chúng.

## Approach

Dùng SOT-Graph Fact Bundle cho kiến trúc và số liệu; Scout đối chiếu hồ sơ cũ, cấu hình, CI và các symbol có liên quan bằng graph/LSP/AST. Phân biệt dữ kiện hiện hành, kết quả lịch sử và [INFERENCE]. Không coi thiếu cạnh graph là không có caller; không coi conformance chưa đánh giá là đạt. Test-runner thực hiện smoke chỉ đọc, ngắn, không cài đặt/network, nếu runtime sẵn có. Roadmap là đề xuất, chưa được phê duyệt thực hiện.

## Critical files and ownership

- Main: duy nhất được ghi hồ sơ này; tổng hợp và ưu tiên roadmap.
- RepoSurvey (Scout): chỉ đọc `plan/`, `docs/`, manifest, release/CI evidence và các đoạn code được định vị; T-01/T-02.
- Main: tạo Fact Bundle tại `.sot/bundle/roadmap-2026-09-19/`, không ghi đè báo cáo cũ.
- Test-runner: smoke giới hạn khi đã xác định lệnh; không thay đổi source hoặc hồ sơ.
- DAG: khảo sát lịch sử và sinh bundle độc lập → đối chiếu runtime → ưu tiên và ghi nhận bằng chứng. Không có concurrent source writes.

## Verification

- AC-01: xác định stack, interface, phiên bản và hướng phát triển hiện tại, có nguồn cụ thể; không nhầm hồ sơ cũ với trạng thái hiện hành.
- AC-02: thu được năm Fact Bundle hoặc ghi rõ lý do không thể; nêu chất lượng/phạm vi graph và ít nhất một kết quả runtime nếu khả dụng.
- AC-03: roadmap có ưu tiên, mục tiêu, phụ thuộc, điều kiện nghiệm thu và những việc nên hoãn; không đề xuất lại milestone đã hoàn thành như việc mới.
- AC-04: kết quả tiếng Việt có bằng chứng, giới hạn khảo sát và hồ sơ bền vững; không có thay đổi mã nguồn từ nhiệm vụ này.

## Execution checklist

- [x] T-01 — Xác định hiện trạng và định hướng repo (AC-01).
- [x] T-02 — Khảo sát kiến trúc và khoảng trống kỹ thuật (AC-02).
- [x] T-03 — Ưu tiên lộ trình theo bằng chứng repo (AC-03).
- [x] T-04 — Ghi nhận đề xuất và giới hạn khảo sát (AC-04).

## Evidence and handoff

- Khởi đầu: root listing xác nhận `.sot/sot.db`, Python manifest, `engines/`, `vendor/`, `tests/`, `evaluation/`, `benchmarks/`, nhiều hồ sơ `plan/` và release/quality documents.
- `docs/plans/` chưa tồn tại, không có hồ sơ trùng trong vị trí chuẩn.
- Scout model configuration đã đối chiếu: `google-antigravity/gemini-3.7-flash-medium:medium`.
- AC-01: `pyproject.toml:5-30` xác nhận package `sotgraph`, Python ≥3.10, Beta; CLI thực chạy `sotgraph -V` trả `0.3.7`. Phiên bản manifest là dynamic, không có mâu thuẫn với CLI.
- `RELEASE_DECISION.md:3-7`: quyết định hiện được dẫn chiếu là `CONDITIONAL_GO / HUMAN_GATED`; impact-assurance là advisory. Không sử dụng chứng nhận production/autonomous refactoring cũ đã bị supersede.
- `sot_git_history(limit=6, impact=false, json=true)` quan sát HEAD `a6c671d`; các commit gần nhất sửa Windows path/liveness, CBM store path shaping, CI và daemon/newest-wins/JIT. Đây là lịch sử commit, không phải bằng chứng CI hiện đang xanh.
- `sot_bundle(output=.sot/bundle/roadmap-2026-09-19, json=true)` thành công, sinh đủ năm file. Bundle: 35,905 nodes; 166,668 edges; 1,553 files; Q=0.7731. Số liệu tổng hợp gồm engine và các phạm vi khác, không phải số liệu riêng Python product core.
- `sot_doctor`: `quick_check: ok`; local SQLite schema v8, 75 nodes, 43 confirmed edges, 28 pending; engine read-through 35,854 nodes / 195,825 edges. Hai lớp lưu trữ có mẫu số khác nhau, không cộng hoặc coi khác biệt là corruption.
- `sot_verify(deep=false)` phát hiện 9 `mtime_size_mismatch`: scripts/e2e_real_cbm.py; src/sot_graph/assurance/resolution.py; src/sot_graph/engine_daemon.py; src/sot_graph/freshness.py; src/sot_graph/graphstore.py; src/sot_graph/pack.py; tests/test_engine_daemon.py; tests/test_pack_target_recovery.py; tests/test_precommit_gate.py. Chưa kiểm chứng SHA-256 sâu; không gọi đây là lỗi freshness logic.
- Raw diagnostic tool receipts đã lưu tại `.sot/bundle/roadmap-2026-09-19/diagnostics.json`.
- Test-runner smoke, tất cả exit 0: `sotgraph --help`; `sotgraph -V`; `sotgraph search --help`; `sotgraph pack --help`; `sotgraph search --reconcile off --no-jit --json CbmStore`; `sotgraph pack --reconcile off --tokens 1500 --json tests/test_cbm_store.py:170`.
- Search probe trả provider `codebase-memory`, một STRONG hit tại tests/test_cbm_store.py:170 và năm WEAK hits ở C store. Đây chưa phải bằng chứng tìm đúng định nghĩa class CbmStore. Pack của test anchor thành công với STRONG/source_partial và cap 1500; không phải bằng chứng đủ toàn bộ context hoặc đạt SG-202.
- Không chạy test suite, build, benchmark diện rộng hay manual reconcile. Freshness FRESH của một query không đại diện freshness toàn repo.
- `benchmarks/exit_gates/sg202_followup/ACCEPTANCE.md:9-51` là kết quả lịch sử gắn HEAD `8b45686a0ccf`: 35/43 measurable = 0.8140, frozen roster 90; 5 MISSING_TEST, 3 AMBIGUOUS_TARGET, floor 0.95 chưa đạt tại lần đó. Không khẳng định các lỗi này còn nguyên ở HEAD hiện hành; cần replay mới.
- Runtime receipt transcription: `.sot/bundle/roadmap-2026-09-19/runtime-probes.json`. Pack trả `completeness=PARTIAL`, `tokens_estimate=1500`, `truncated=true`, normalized target là module tests.test_cbm_store; chưa kiểm đếm tokenizer độc lập và không kết luận đúng function target. Tắt refresh không phải bằng chứng tuyệt đối không có metadata/cache write.
- Scout xác minh `docs/CBM_STORE_PLAN.md:3-7` ghi `Status: IMPLEMENTED`, có kết quả E2E lịch sử cho reconcile/search/explore/usages/map/pack/diff-impact qua CbmStore. Không đưa “triển khai CbmStore” vào việc mới.
- Chuỗi projection được Scout định vị: `src/sot_graph/graphstore.py:277-285` giữ `n.name AS symbol`, `n.qualified_name AS fqn`, nhưng `n.label AS label` là kind của CBM; `src/sot_graph/analytics/graph.py:128-136` chỉ đọc `label` để tạo analytics node; `src/sot_graph/analytics/bundle.py:427-433` in `gn.node_id` vào bảng God Nodes. Kết quả quan sát trong bundle mới khớp chuỗi này.
- `docs/THREE_GATE_PLAN.md:197-203`: G1 replay lịch sử mean recall 87.5%, mean precision 13.0% so với 28.4%, precision drop 15.4 điểm phần trăm vượt bar 10 → FAIL. `:264-266`: G3 still-hot precision so với hand labels trên mẫu 22 commit = 0.778, dưới bar 0.8 → FAIL. Chưa replay current HEAD.
- `plan/sg201-landmark-study-protocol.md:59-60,79-82`: tối thiểu 3 reviewers; hồ sơ ghi `NONE — PENDING_HUMAN_EVIDENCE`, gate `NOT MET (pending)`. Không suy ra hiện có đánh giá ngoài repo hay không.

### 1. Tổng quan hệ thống và phạm vi kiến trúc

**Dữ kiện ngoài bundle, dùng làm nền sản phẩm:** manifest mô tả knowledge graph có kiểm chứng cho AI coding agents; Python ≥3.10, Beta; CLI hiện chạy v0.3.7. Hướng phát triển gần nhất là CBM Store, newest-wins/JIT, daemon và sửa tương thích Windows/CI, không phải bắt đầu lại từ parser hoặc graph store.

**Dữ kiện bundle:** `05_system_metrics.json:3-18` báo primary language `C`, heuristic pattern `Modular Layered Architecture (C)`, Q=0.7731, 112 communities. Không coi đây là kiến trúc đã được chủ dự án tuyên bố hoặc thước đo riêng Python core.

**[INFERENCE] Sơ đồ phạm vi để định hướng, không phải call graph đã chứng minh:**

```text
Python product: CLI / MCP / assurance / context
    Storage boundary: local SQLite + CBM read-through
        Owned engine subtree: engines/codebase-memory-mcp
    Analytics consumers: graph / report / bundle
```

Cơ sở ngoài bundle: pyproject.toml; CBM_STORE_PLAN; doctor; graphstore/analytics anchors ở trên. Không vẽ container dịch vụ ngoài hay gọi các dòng module heuristic là domain nghiệp vụ đã được xác nhận.

### 2. Phân rã module và năng lực hiện có

Bundle `01_module_inventory.md:8-37` liệt kê các nhóm `Sot Graph Domain`, `Cbm Module`, `Cli Domain`, `Daemon Domain`, `Lsp Module`, `Pipeline Domain`, `Foundation Domain`, `Mcp Domain`, `Store Domain`, `Evidence Module`, `Ui Domain`, `Cypher Domain`. Đây là nhóm sinh bằng heuristic.

- Nhóm product/store: các file dưới `src/sot_graph`, CBM và store được bundle quan sát; runtime doctor xác nhận read-through.
- Nhóm engine: CLI, daemon, LSP, pipeline, foundation, MCP, UI nằm trong footprint của engine; không đồng nhất với public surface của Python package.
- Nhóm báo cáo/evaluation: bundle đang tính cả docs, scripts, plans, fixtures và benchmark trong taxonomy. Không diễn giải `157 functional modules` thành 157 module nghiệp vụ thực.
- Điểm mạnh thực chạy: CLI, no-refresh search và pack hoạt động; pack công bố PARTIAL/truncation thay vì ngầm coi đầy đủ.
- Năng lực theo hồ sơ, chưa re-certify: trust chain, Three-Gate assurance, CbmStore và quality/CI infrastructure đã có. Roadmap tập trung độ đúng và kiểm chứng lại, không dựng lại các khối này.

### 3. Vai trò và phân quyền

**UNKNOWN — bundle không chứa dữ liệu phân quyền theo vai trò.** Không suy diễn thiếu RBAC là một lỗi sản phẩm và không đề xuất xây RBAC cho công cụ local này khi chưa có yêu cầu.

### 4. Lifecycle và vận hành

`03_workflows_states.md:8-33` nhận các file GitHub workflows thành ứng viên state/lifecycle; `:39-64` nhận các row JSON benchmark thành ứng viên background tasks. Không có bằng chứng transition hoặc lịch chạy đủ để dựng state machine từ bundle.

**[INFERENCE] Ưu tiên vận hành:** bảo đảm quan hệ giữa snapshot engine, overlay mới hơn, drift detection và query-level freshness có thể giải thích được. Bằng chứng thúc đẩy là 9 drift files hiện tại và lịch sử newest-wins/JIT; chưa chứng minh logic JIT có lỗi. Không bật JIT để che baseline trước khi ghi lại.

### 5. Luồng xuyên suốt đã quan sát

Luồng CLI thực chạy: root help/version → search `CbmStore` với refresh tắt → chọn hit đã trả → pack với cap 1500. Đây là chuỗi thao tác khảo sát, không khẳng định internal call order từ bundle.

- Search: tìm thấy `_store` trong test, không phải bằng chứng tìm trúng định nghĩa class CbmStore.
- Pack: normalized target là module, STRONG nhưng PARTIAL, có source bị cắt. Không suy từ “exit 0” thành “task-sufficient”.
- Report/bundle: symbol name bị mất trên đường từ CBM projection sang analytics; God Nodes in ID nội bộ. Đây là khoảng trống hiện hành có cả output và source anchors.
- Không đủ bằng chứng để khẳng định một luồng refactor tự động an toàn end-to-end; giữ `CONDITIONAL_GO / HUMAN_GATED`.

### 6. Đánh giá và roadmap đề xuất

#### Conformance và giới hạn

Copy trạng thái từ bundle: **`VIOLATIONS_DETECTED`**.

Summary: “4 candidate finding(s) from heuristic rules; each is anchored to the observed edge (source/target symbols and paths) and is NOT verified against any declared layer policy.”

- Coverage: **3,696 / 166,668 assessed edges**, fraction **0.0222**; 1,389 / 35,905 classified nodes.
- Không ingest declared layer policy; chỉ hỗ trợ `LAYER_BYPASS` và `INVERTED_DEPENDENCY`; endpoints UNKNOWN bị loại khỏi assessment.
- Bốn dòng là **HEURISTIC_RULE_CANDIDATES**, không phải bốn lỗi kiến trúc đã xác minh. Có cả test/script edges. Không refactor dependency theo các dòng này trước khi sửa identity/scope.
- Q cao không chứng minh search precision, caller coverage hoặc task sufficiency cao.

#### Thứ tự thực hiện [INFERENCE — đề xuất, chưa phê duyệt triển khai]

| ID / Ưu tiên | Kết quả cần đạt | Bằng chứng thúc đẩy | Exit gate và phụ thuộc |
| :--- | :--- | :--- | :--- |
| R-01 / P0 | Chốt baseline current HEAD và hành vi freshness/provider | 9 drift files; benchmark SG-202 gắn HEAD cũ; recent Windows/CI fixes | Sau khi lưu baseline, reconcile có kiểm soát; verify trên phạm vi khai báo hết drift hoặc mọi ngoại lệ có nguyên nhân; chạy lại supported CI/provider matrix và lưu commit, corpus, provider/snapshot, kết quả. Không công bố xanh toàn repo từ smoke. Không phụ thuộc R khác. |
| R-02 / P0 | Sửa identity và scope của analytics/report/bundle | Projection `n.label`/consumer `label`; bảng in `gn.node_id`; fixture/docs lẫn taxonomy | Symbol được hiển thị bằng name/fqn và path:line; ID/kind vẫn giữ làm metadata; không âm thầm đổi contract label ở toàn bộ caller. Fixture đối chiếu tên không rỗng/sai và separation product/engine/test; God Node actionable; tìm không ra phải UNKNOWN. CLI/MCP entrypoints cần được liệt kê hoặc nêu rõ chưa hỗ trợ thay vì suy từ 0 HTTP routes. Conformance giữ coverage/inference disclosure. Bám snapshot R-01. |
| R-03 / P1 | Đóng khoảng trống context pack SG-202 | Frozen roster: 35/43 measurable, 90 sampled tại HEAD cũ; ambiguity và test reference/call distinction | Replay current HEAD trước. Giữ nguyên frozen-90 baseline để so sánh; bổ sung protocol có phiên bản cho path-qualified/FQN targets và evidence loại reference/type/import, không giả call edge. Mục tiêu gate hiện có ≥0.95 trên cohort khai báo, cap serialized 1500; công bố cả measurable/all sampled và abstention. Nếu đổi oracle phải báo cũ/mới song song. Phụ thuộc R-01 và identity contract phù hợp R-02. |
| R-04 / P1 | Nâng chất lượng G1 scope và G3 commit verdict | Historical G1 precision drop 15.4pt; G3 human-label precision 0.778 | Replay current HEAD/corpus trước; G1 đạt bar precision drop ≤10pt mà không che recall/unknowns; G3 đạt precision ≥0.80 so với nhãn người trên holdout, không lấy labeler tự đối chiếu làm chuẩn. Chỉ tối ưu hunk-to-symbol/scope selection khi lỗi replay xác nhận. Phụ thuộc baseline R-01; không nới fail-closed. |
| R-05 / P1 song song | Hoàn tất SG-201 bằng chứng người dùng | Protocol ghi ≥3 reviewers, `PENDING_HUMAN_EVIDENCE` | Chạy protocol mù với ít nhất 3 người độc lập; lưu đánh giá, bất đồng và aggregate; đối chiếu đúng gate của protocol. Agent không được thay người chấm. Phụ thuộc tuyển reviewers, dùng artifact version đóng băng sau sửa identity; không chặn R-03/R-04 độc lập. |
| R-06 / P2 có điều kiện | Tối ưu scale hoặc mở rộng semantic/provider sau khi có số đo | NetworkX đã core; bundle 35k nodes chạy thành công; chưa có p95/RSS hiện hành | Đo latency p50/p95, peak RSS, cold/warm, graph size trên corpus có provenance; chọn một bottleneck thực và đặt budget dựa baseline. SCIP/vector federation chỉ vào phạm vi khi integration tests hoặc use case chứng minh thiếu. Không mặc định rewrite thuật toán hoặc chuyển thêm sang native. |

**Phụ thuộc:** R-01 → R-02 → R-03; R-04 có thể chạy song song sau R-01 khi write boundaries được tách; R-05 chuẩn bị reviewers song song, chấm artifact đóng băng; R-06 chỉ mở theo measurement.

**Đầu việc nên bắt đầu:** R-01 để có baseline đáng tin; ngay sau đó R-02 với phạm vi consumer-facing identity/report contract. Đây là lỗi nhìn thấy trong chính báo cáo repo, tránh quyết định refactor trên dữ liệu tên sai.

**Không nên làm lúc này:** xây lại CbmStore/Three-Gate, thêm NetworkX lần nữa, nâng claim autonomous refactoring, mở rộng UI/LLM/vector hàng loạt, tuning Louvain không có profile, hoặc sửa “bốn violations” như lỗi đã xác minh.

**Lịch và nhân lực:** chưa biết; dùng dependency/exit gate thay vì hứa số tuần hoặc ngày phát hành.

#### Acceptance và bàn giao

- **AC-01 PASS:** manifest, CLI version và lịch sử gần nhất đã đối chiếu; quyết định release superseded và benchmark cũ được phân biệt với hiện trạng.
- **AC-02 PASS:** sinh đủ năm Fact Bundle; doctor/verify thực chạy; sáu CLI probes exit 0 qua Test-runner. Kết quả PARTIAL/drift/coverage đều giữ nguyên, không coi là suite đạt.
- **AC-03 PASS:** sáu work packages có ưu tiên, bằng chứng, phụ thuộc và exit gates; có danh sách hoãn. Không có cam kết lịch hoặc scope triển khai ngầm.
- **AC-04 PASS:** báo cáo sáu phần bằng tiếng Việt nằm trong hồ sơ này; source anchors, diagnostic receipts và runtime receipt transcription có đường dẫn cụ thể. Nhiệm vụ không sửa source, test, cấu hình sản phẩm, không commit/push.
- Giới hạn còn lại: chưa chạy full CI/benchmark trên HEAD hiện tại, chưa xác minh deep SHA-256 drift, chưa đo p95/RSS, chưa có human study mới, chưa chứng minh JIT có khắc phục search discoverability hay không. Không có kết luận security audit hoặc production certification.
- Tạo mới: hồ sơ này, năm Fact Bundle và hai JSON evidence tại `.sot/bundle/roadmap-2026-09-19/`. Không có implementation nên không gọi Reviewer để review kế hoạch, không chạy code cleanup/reconcile nhằm thay baseline.

## Assumptions and contingencies

- Không suy đoán mục tiêu kinh doanh, số người, lịch phát hành hoặc ngân sách. Nếu chưa có các ràng buộc này, roadmap dùng thứ tự và exit gate, không cam kết ngày.
- Graph có thể stale hoặc heuristic; giữ nguyên trust verdict, provider và coverage. Không reconcile tự động để che mất baseline trước khảo sát.
- Nếu môi trường thiếu runtime/dependency, báo rõ giới hạn; không cài đặt hay tự mở rộng quyền truy cập.
- Kiến nghị nằm ngoài bundle phải có nhãn [INFERENCE] và nguồn hỗ trợ; không tự tạo RBAC/state machine/sequence không được chứng minh.
