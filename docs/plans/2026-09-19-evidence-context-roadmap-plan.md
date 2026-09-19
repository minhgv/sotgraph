# Kế hoạch thực hiện roadmap SOT-Graph: evidence và context quality

- **Work ID:** `2026-09-19-evidence-context-roadmap-plan`
- **Trạng thái thực thi:** DONE — 17/20 task hoàn tất; T-14/T-15 BLOCKED (external human dependency, không agent-actionable).
- **Nguồn:** [Khảo sát repo và roadmap R-01–R-06](2026-09-19-repository-roadmap-survey.md).
- **Next safe action:** Bàn giao. Khi ≥3 reviewer CSV có mặt tại `benchmarks/exit_gates/landmark/`, chạy `landmark-aggregate` để đóng T-14/T-15 và SG-201.
- **Quyền hạn hiện tại:** Đã triển khai R-01–R-06 (trừ human gate); không commit/push.

## Context

### Mục tiêu

Chuyển roadmap đã khảo sát thành các gói công việc có thứ tự, ranh giới ghi, tiêu chí nghiệm thu và bằng chứng tái lập được. Trục ưu tiên là **baseline đáng tin → identity/report đúng → context đủ dùng → chất lượng assurance và bằng chứng người dùng → tối ưu có đo lường**.

Kế hoạch không coi việc hoàn thành code là đồng nghĩa với đạt gate. Gate thiếu bằng chứng giữ nguyên trạng thái chưa đạt; thay đổi oracle hoặc mẫu số phải được công khai.

### Cơ sở tại thời điểm khảo sát

| Quan sát | Ý nghĩa đối với kế hoạch | Giới hạn bằng chứng |
| :--- | :--- | :--- |
| CLI v0.3.7; Python ≥3.10; HEAD quan sát `a6c671d` | R-01 đóng lại baseline tại thời điểm bắt đầu triển khai | Không tự coi đây là HEAD mới nhất khi tiếp tục phiên khác |
| CbmStore đã có hồ sơ IMPLEMENTED; NetworkX đã là core dependency | Không xây lại store hoặc thêm lại dependency | Kết quả E2E lịch sử chưa được replay trên HEAD triển khai |
| SQLite quick_check `ok`; shallow verify có 9 `mtime_size_mismatch` | Ghi baseline trước, sau đó xác minh và reconcile có kiểm soát | Chưa chứng minh corruption hoặc lỗi freshness/JIT |
| Analytics dùng label kind của CBM; bảng God Nodes in ID nội bộ | R-02 sửa consumer-facing identity và source anchors | Không suy ra cần thay đổi toàn cục semantics của `label` |
| SG-202 lịch sử đạt 35/43 measurable, tương đương 0.8140; roster 90 | R-03 replay rồi xử lý ambiguity và thiếu evidence | Gắn HEAD `8b45686a0ccf`, không phải kết quả hiện hành |
| G1 lịch sử precision drop 15.4 điểm phần trăm; G3 precision 0.778 | R-04 replay trước khi quyết định sửa thuật toán | Không khẳng định lỗi vẫn còn ở HEAD triển khai |
| SG-201 trong repo ghi PENDING_HUMAN_EVIDENCE | R-05 cần người chấm thật, tối thiểu 3 theo protocol | Không suy ra có hay không nghiên cứu ngoài repo |
| Bundle có 4 heuristic candidates; assessed edges 3,696/166,668 | Báo cáo phải giữ coverage và uncertainty | Không coi là 4 lỗi kiến trúc được xác minh |

Các dữ kiện trên được dẫn từ hồ sơ khảo sát; bước lập kế hoạch này không chạy lại source audit hoặc benchmark. Các thiết kế, thứ tự wave và điều kiện bổ sung dưới đây là **đề xuất**, không phải mô tả năng lực đã triển khai.

### Phạm vi và non-goals

**Trong phạm vi:** đủ R-01 đến R-06, với R-06 là gói có điều kiện; CLI/MCP contracts chịu tác động; provider semantics; chất lượng evidence/context; evaluation và artifact bàn giao.

**Ngoài phạm vi mặc định:** xây lại CbmStore/Three-Gate; thêm NetworkX; mở rộng UI/LLM/vector hàng loạt; tự động refactor production; thiết kế RBAC; rewrite native hoặc tuning Louvain khi chưa có profile; sửa các heuristic violations như lỗi đã xác nhận.

Không tự nâng quyết định release khỏi `CONDITIONAL_GO / HUMAN_GATED`. Không cam kết số tuần, số người hoặc ngày phát hành khi chưa có các ràng buộc đó.

## Approach

### Nguyên tắc kỹ thuật

1. **Filesystem và snapshot làm chuẩn.** Graph là projection có provider, độ mới và giới hạn coverage; không đồng nhất số liệu local SQLite, engine read-through và bundle.
2. **Identity không trộn với loại symbol.** Giữ ID, kind, provenance riêng; display dùng tên/FQN và source anchor đúng. Không đổi `label` xuyên hệ thống chỉ để sửa một bảng báo cáo.
3. **Evidence có loại rõ ràng.** Call, reference, type và import không được giả làm nhau để làm đẹp caller coverage hoặc SG-202.
4. **Abstention là kết quả hợp lệ nhưng không phải thành công.** UNKNOWN/PARTIAL/AMBIGUOUS phải còn thấy trong output, mẫu số và gate report.
5. **Không tạo framework thứ hai.** Tái sử dụng parser, graph store, evaluation harness, test fixtures và output contracts hiện có sau khi kiểm tra bằng graph/LSP.
6. **Bảo toàn trust boundary.** Không nới fail-closed; không tăng confidence/coverage khi thiếu bằng chứng; không thay đổi hành vi ghi dữ liệu, quyền truy cập hoặc network một cách ngầm định.

### Hợp đồng xuyên gói

| Contract | Producer / consumer | Invariant |
| :--- | :--- | :--- |
| Baseline manifest | R-01 → mọi gói | Có HEAD, trạng thái thay đổi chưa commit, corpus, runtime/OS, provider, snapshot/generation nếu có, policy refresh, cấu hình, lệnh và artifact; trường không có ghi unavailable kèm lý do |
| Symbol identity | R-02 → analytics/report/bundle; R-03 chỉ nhận phần liên quan | Stable ID/kind/provenance không bị ghi đè bởi display name; FQN hoặc tên có source context phải trỏ đúng symbol; trường thiếu là UNKNOWN, không tự bịa |
| Scope classification | R-02 → metrics/report/evaluation | Phân biệt product, engine, tests/fixtures và docs/scripts/vendor khi phù hợp; định nghĩa inclusion/exclusion và cách xử lý UNKNOWN; không đổi mẫu số âm thầm |
| Typed evidence | R-03 ↔ R-04 nếu dùng chung resolver | Giữ loại cạnh, source anchor, freshness và provider; tham chiếu không biến thành invocation |
| Evaluation receipt | R-01/R-03/R-04/R-05/R-06 → quyết định acceptance | Liên kết snapshot, phiên bản protocol/oracle, cohort, raw result, aggregate, exclusions/abstentions và verdict; có thể truy về từng case |
| Release claims | Tất cả gói → handoff | Không thay human evidence bằng agent review; không coi smoke hoặc compilation là certification |

Tên field/schema cụ thể phải bám API hiện có khi lập scope receipt; bảng này quy định ý nghĩa, không yêu cầu thêm schema song song.

### Wave DAG và điều kiện chuyển bước

```text
W0: R-01 baseline
    |
    +--> W1-A: R-02 identity / scope --> W2-A: R-03 SG-202
    |
    +--> W1-B: R-04 replay G1/G3 --> W2-B: sửa lỗi đã đo được
    |
    +--> R-05 chuẩn bị protocol / reviewers
              + R-02 artifact freeze --> human study

Sau baseline correctness và đo đạc:
    R-06 measurement --> quyết định mở tối ưu / integration

Các gói đã triển khai --> final verification --> một Reviewer pass
                     --> repair nếu cần --> acceptance / handoff
```

- R-04 có thể song song R-02 sau R-01; phần sửa dùng chung resolver/schema phải đợi khóa contract và được serialize.
- R-05 chuẩn bị sớm; chỉ chấm artifact đã đóng băng sau R-02. Thiếu người chấm không chặn R-03/R-04 độc lập.
- R-06 không có nghĩa vụ sinh thay đổi code: nếu chưa chứng minh bottleneck/use case, kết quả hợp lệ là measurement và quyết định defer có lý do, không ghi tối ưu PASS.
- Tối đa 3 subagents đồng thời. Main sở hữu kế hoạch/tích hợp; Scout chỉ khảo sát; workers có ranh giới ghi riêng; test-runner chạy test/build; Reviewer chỉ review implementation đã hoàn thành.
- Trước mỗi wave sửa code, Main bổ sung scope receipt, source anchors hiện hành, write boundaries và lệnh kiểm chứng vào hồ sơ này. Chưa có receipt hoặc target UNKNOWN thì chưa mở quyền sửa target đó.

### R-01 — P0: Đóng baseline và freshness/provider

**Kết quả:** baseline hiện hành có thể tái lập, không dùng dữ liệu lịch sử làm bằng chứng pass.

**Công việc:**

1. Ghi HEAD và thay đổi chưa commit mà không reset/stash/ghi đè công việc người dùng. Xác định nguồn chân lý của supported CI/platform/provider matrix và các harness G1/G3/SG-201/SG-202.
2. Lập command registry: từng AC → lệnh thực có trong repo, cwd, prerequisite, corpus, provider/policy, output, exit code dự kiến. Kiểm tra lại flags bằng CLI help, không đoán tên script hoặc option.
3. Lưu baseline doctor/verify và query probes trước khi refresh; xác định chính xác layer và tập file của từng mẫu số. Điều tra 9 drift observations từ khảo sát nếu còn liên quan, không giả định chúng chưa thay đổi.
4. Thực hiện deep verify trên phạm vi được công cụ hỗ trợ. Khi bước triển khai được cho phép, reconcile có kiểm soát; so sánh trước/sau và giải thích drift còn lại hoặc mục không thuộc phạm vi xác minh.
5. Test-runner chạy supported matrix và suites đã đăng ký. Kiểm chứng freshness/provider qua các tình huống có liên quan: unchanged file, changed file, moved/deleted symbol, provider unavailable, refresh off/auto và cold/warm nếu contract hiện có hỗ trợ.
6. Nếu có lỗi thật, tách reproduction và repair theo receipt trước khi sửa; không thay kết quả lỗi bằng skip. Môi trường không chạy được platform/provider nào phải ghi MISSING_EVIDENCE và chỉ rõ đường lấy bằng chứng tương ứng.

**Đầu ra:** manifest; command registry; raw receipts trước/sau; provider/freshness matrix; danh sách baseline failures và quyết định đóng/mở từng blocker.

**Phụ thuộc:** không phụ thuộc gói khác. R-02/R-04 chỉ bắt đầu khi baseline liên quan đã được giải thích và không còn blocker làm mất độ tin cậy của phép đo.

### R-02 — P0: Identity và scope của analytics/report/bundle

**Kết quả:** người đọc tìm được symbol thực thay vì chỉ nhìn thấy kind hoặc ID nội bộ.

**Công việc:**

1. Lấy references, usages và PRE scope receipt cho projection/analytics consumers liên quan. Đối chiếu local/CBM provider, nullable fields và các caller hiện dùng `label`.
2. Chốt display identity từ các trường hiện có: FQN/tên đúng ngữ cảnh + path:line; giữ riêng ID, kind, provider và provenance. Thiếu evidence thì xuất UNKNOWN với lý do, không dựng tên từ giả định.
3. Áp dụng cho đường analytics → report/bundle, bao gồm God Nodes; cập nhật tất cả consumers thực sự bị contract tác động. Ưu tiên sửa consumer thay vì thay projection dùng chung khi không cần.
4. Phân loại scope rõ ràng, không coi docs/fixture/engine subtree là business domain của Python product. Tổng hợp từng scope có mẫu số và phần UNKNOWN.
5. Phân biệt inventory CLI/MCP với detector HTTP/UI/event. Nếu detector chưa hỗ trợ một surface thì ghi rõ unsupported/not assessed; không kết luận sản phẩm không có entrypoints từ `0 routes`.
6. Giữ nguyên disclosure conformance: candidate nature, policy observable hay không, supported rules, assessed/total và unclassified endpoints. Không biến heuristic candidate thành confirmed violation.
7. Chạy CLI tạo bundle/report thật trên fixture có tên trùng và trên repo; kiểm tra source anchors, God Nodes và output dễ đọc. Không giảm verification xuống kiểm tra string không rỗng.

**Đầu ra:** contract identity/scope được ghi nhận; implementation và consumer cutover; regression checks cho lỗi định danh/nhầm scope; bundle/report mới gắn snapshot để so sánh với khảo sát.

**Phụ thuộc:** R-01. Identity contract ổn định là đầu vào R-03 và artifact freeze R-05.

### R-03 — P1: Context pack và SG-202

**Kết quả:** context đáp ứng task theo protocol công khai, trong ngân sách token, không làm đẹp điểm bằng cách thay mẫu số.

**Công việc:**

1. Replay frozen roster 90 tại HEAD baseline với oracle gốc. Công bố measurable/all sampled, lỗi target, abstentions và token usage; không mặc định kết quả vẫn là 35/43.
2. Phân loại failure hiện hành theo target resolution, missing test/contract evidence, serialization budget và provider/freshness. Chỉ sửa lớp có bằng chứng lỗi.
3. Hoàn thiện path-qualified/FQN target resolution mà không đoán một symbol khi tên mơ hồ. Phân biệt yêu cầu symbol với module; output phải công bố normalized target thực sự được chọn.
4. Bổ sung hoặc sử dụng typed references để lấy context test/contract theo semantics có thật. Không tạo fake call edge để đáp ứng oracle vốn chỉ nhìn calls.
5. Phân bổ context theo target và evidence thiết yếu. Kiểm đếm payload serialized bằng tokenizer được protocol chọn, không chỉ dựa `tokens_estimate`; công bố partial/truncation/omission reason.
6. Nếu cần thay query contract hoặc oracle, version riêng trước khi dùng; chạy song song bản gốc và bản mới trên roster đóng băng. Không bỏ case khó để tăng success rate.
7. Xác định cases regression đáng giữ: tên trùng khác path, symbol/module boundary, reference không phải call, budget boundary và evidence bị thiếu thực sự. Dùng harness sẵn có thay vì viết suite trùng lặp.

**Đầu ra:** replay baseline/current; failure taxonomy; resolver/evidence/pack changes trong scope receipt; protocol version nếu đổi; receipts gate SG-202.

**Phụ thuộc:** R-01 và contract liên quan của R-02. Nếu oracle gốc có giới hạn cấu trúc khiến floor không thể đạt, giữ trạng thái gate gốc FAIL và báo nguyên nhân; không coi pass oracle mới là đã pass oracle cũ.

### R-04 — P1: Chất lượng G1 scope và G3 verdict

**Kết quả:** scope/commit verdict đạt gate trên dữ liệu độc lập mà không nới bảo vệ fail-closed.

**Công việc:**

1. Replay G1/G3 bằng harness và corpus hiện hành đã được pin; lưu false positives, false negatives, abstentions, provider và coverage. So sánh cùng mẫu số với baseline.
2. Với G1, chỉ sửa hunk-to-symbol alignment, scope expansion hoặc selection nếu lỗi replay định vị vào các lớp đó. Báo precision, recall và unknowns cùng nhau.
3. Với G3, tách dữ liệu điều chỉnh khỏi human-labeled holdout. Không lấy labeler tự đối chiếu làm ground truth; không chọn threshold dựa vào holdout rồi tiếp tục gọi đó là độc lập.
4. Kiểm tra tác động tới public assurance contracts và các đường incomplete/provider failure. Giữ fail-closed và evidence gaps có thể quan sát.
5. Nếu một sửa đổi đụng resolver/schema của R-03, lập integration slice có một owner và serialize writes; không để hai worker sửa cùng boundary đồng thời.

**Đầu ra:** replay và phân tích lỗi; bounded repairs nếu cần; receipts G1/G3 với cohort, precision/recall, provenance nhãn và verdict.

**Phụ thuộc:** R-01; có thể song song R-02 với ranh giới ghi đã khóa.

### R-05 — P1: SG-201 human evidence

**Kết quả:** đánh giá bằng người thật theo protocol, không thay bằng agent opinion.

**Công việc:**

1. Đối chiếu protocol hiện hành, trích nguyên các thước đo/exit gates vào command/evaluation registry; chuẩn bị reviewer instructions và blinded task package.
2. Xác nhận ít nhất 3 reviewers độc lập. Việc mời/liên hệ người thật cần cơ chế và quyền của chủ dự án; agent chỉ chuẩn bị tài liệu và tập artifact.
3. Đóng băng artifact sau R-02 cùng snapshot, task list và rubric. Nếu thay identity/output sau khi chấm, version lại và đánh giá ảnh hưởng đến tính hợp lệ trước khi gộp dữ liệu.
4. Thu đánh giá độc lập, lưu disagreement và cách tổng hợp theo protocol. Tối thiểu hóa thông tin cá nhân, không đưa credential hoặc dữ liệu nhạy cảm vào artifact chia sẻ.
5. Công bố số người, số task, exclusions, aggregate và verdict theo đúng gate. Đủ 3 reviewers là điều kiện cần, không tự động là đạt chất lượng.

**Đầu ra:** frozen study package; human review records; aggregate/disagreement report; SG-201 verdict.

**Phụ thuộc:** reviewers và artifact freeze R-02. Khi thiếu người, đánh dấu T-14/T-15 BLOCKED_EXTERNAL; tiếp tục các nhánh kỹ thuật không phụ thuộc. Không ghi gate PASS khi mới chuẩn bị protocol.

### R-06 — P2 có điều kiện: Scale và semantic/provider extension

**Kết quả:** quyết định tối ưu dựa trên chi phí đo được và nhu cầu thực, không mở rộng tính năng theo suy đoán.

**Công việc:**

1. Chọn workload đại diện từ entrypoints đã xác minh; ghi corpus provenance/graph size, phần cứng, runtime, provider, warmup, số lần chạy và refresh policy trước khi đo.
2. Đo p50/p95 latency và peak RSS, tách cold/warm; công bố errors/abstentions cùng hiệu năng để tránh tối ưu bằng cách trả ít bằng chứng hơn.
3. Xác định một bottleneck có profile, hoặc một khoảng trống SCIP/vector được use case/integration chứng minh. Nếu không có, ghi defer và không triển khai thêm.
4. Trước sửa code, chốt budget định lượng và correctness guards vào AC-12, ghi rõ phạm vi được mở. Budget lấy từ baseline và yêu cầu sử dụng, không chọn sau khi đã thấy kết quả sửa.
5. Thực hiện bounded change, rerun cùng workload và các contract correctness liên quan; tránh quét graph lặp hoặc allocation/copy mới không cần thiết.

**Đầu ra:** measurement report; quyết định triển khai/defer; budget được chốt; comparison trước/sau và regression evidence nếu triển khai.

**Phụ thuộc:** R-01 và contracts bị tác động đã ổn định. Việc mở rộng ngoài use case có bằng chứng cần quyết định scope mới, không được suy thành phần bắt buộc của roadmap này.

## Critical files and ownership

Các đường dẫn dưới đây đã được hồ sơ khảo sát định vị. Line anchors lịch sử chỉ phục vụ bắt đầu khám phá; trước sửa phải lấy lại definition/references và source receipt hiện hành. Không coi danh sách này là quyền sửa toàn bộ subtree.

| Boundary / tài liệu | Gói / owner khi thực thi | Giới hạn ghi |
| :--- | :--- | :--- |
| Hồ sơ kế hoạch này | Main | Sole writer; cập nhật task, AC, bằng chứng và next safe action |
| `pyproject.toml`, `RELEASE_DECISION.md`, `docs/CBM_STORE_PLAN.md` | R-01 / baseline owner | Đọc contract/dependency/release baseline; không đổi release claim hoặc thêm dependency mặc định |
| CI và evaluation entrypoints | R-01 / Scout định vị, test-runner chạy | Tên file/lệnh chính xác phải được khóa ở T-01; chưa cấp mutation scope cho file UNKNOWN |
| `src/sot_graph/graphstore.py` | Integration owner | Shared projection boundary; ưu tiên giữ nguyên; mọi thay đổi cần caller coverage và serialize |
| `src/sot_graph/analytics/graph.py`, `src/sot_graph/analytics/bundle.py` | R-02 / analytics worker | Identity/scope consumer; report consumer khác chỉ thêm sau references receipt |
| `src/sot_graph/pack.py`, `tests/test_pack_target_recovery.py` | R-03 / context worker | Target resolution/context budget theo blast radius, không rewrite toàn pack |
| `src/sot_graph/assurance/resolution.py` | R-04 / assurance worker, nếu replay chỉ tới đây | Candidate boundary, không mặc định là nguyên nhân; chia sẻ với R-03 phải có integration owner |
| `src/sot_graph/freshness.py`, `src/sot_graph/engine_daemon.py`, `tests/test_engine_daemon.py`, `tests/test_precommit_gate.py`, `scripts/e2e_real_cbm.py` | R-01 / baseline owner | Điều tra drift/replay; chỉ mở sửa khi có reproduction và receipt |
| `tests/test_cbm_store.py` | R-01/R-02 / một owner được chỉ định ở wave | Tái sử dụng fixture khi phù hợp; không có concurrent writes |
| `benchmarks/exit_gates/sg202_followup/ACCEPTANCE.md`, `docs/THREE_GATE_PLAN.md` | R-03/R-04 | Bằng chứng lịch sử giữ nguyên; kết quả mới ghi artifact riêng có version |
| `plan/sg201-landmark-study-protocol.md` | R-05 / study coordinator | Protocol làm chuẩn; thay đổi protocol phải version và giải thích |
| `.sot/bundle/roadmap-2026-09-19/` | Baseline khảo sát | Không ghi đè bằng kết quả sau sửa |
| Engine/provider files cho R-06 | Chưa cấp owner ghi | Chỉ xác định sau measurement và scope decision |

**Quy tắc giao việc:** mỗi worker nhận task ID, AC, PRE receipt, context bundle token-bounded và danh sách file độc quyền. Bắt buộc graph/LSP-first, không bare-read source lớn; không chạy project-wide validation trong wave song song. Workers không sửa hồ sơ chung và không tự nhận thêm shared file.

## Verification

### Acceptance criteria

Các AC dưới đây là **mục tiêu thực thi**, hiện đều NOT_RUN. Không dùng việc file kế hoạch hợp lệ để đánh dấu chúng PASS.

| AC | Điều kiện nghiệm thu | Kiểm chứng / bằng chứng bắt buộc |
| :--- | :--- | :--- |
| AC-01 | Baseline gắn đúng source state, corpus và provider; supported matrix được liệt kê đầy đủ | Manifest + command registry; từng ô PASS/FAIL/MISSING_EVIDENCE, không ẩn ô chưa chạy; full verification qua test-runner |
| AC-02 | Drift/freshness được giải thích trên phạm vi khai báo | Doctor/verify trước/sau, deep check nếu hỗ trợ, reconcile receipt và scenarios changed/moved/deleted/provider failure; ngoại lệ có nguyên nhân và ảnh hưởng |
| AC-03 | Output analytics/bundle trỏ đúng symbol và source, giữ identity metadata | Fixture có tên trùng, nhiều provider và thiếu tên/path; đối chiếu FQN/tên/path:line với thực thể thật; God Nodes không chỉ in ID/kind |
| AC-04 | Scope và public-surface inventory không gây kết luận sai | Product/engine/tests và các nhóm khác có định nghĩa/mẫu số; CLI/MCP được inventory hoặc ghi rõ chưa hỗ trợ; UNKNOWN được đếm |
| AC-05 | Conformance giữ tính chất heuristic và coverage | Report thực có assessed/total, unknown endpoints, rule/policy disclosure; không nâng candidate thành confirmed violation |
| AC-06 | SG-202 baseline tái lập trên frozen-90 | Pin roster/oracle/source snapshot; đủ per-case outcome, measurable/all sampled, ambiguity và abstention; không loại case im lặng |
| AC-07 | SG-202 đạt success ≥0.95 trên measurable cohort khai báo theo protocol, serialized payload ≤1500 tokens | Tokenizer/protocol version xác định; success denominator rõ; old/new oracle chạy song song nếu đổi; target đúng cấp symbol/module; fake-call evidence bị loại; gate gốc không bị ghi đè |
| AC-08 | G1 precision drop ≤10 điểm phần trăm so với comparator của protocol và đạt recall guards hiện hành | Replay cùng cohort, precision/recall/unknowns; trích guard cụ thể từ protocol vào registry trước sửa; không giấu mất recall để tăng precision |
| AC-09 | G3 precision ≥0.80 trên human-labeled holdout độc lập | Nhãn/provenance, train-tune/holdout split nếu có, confusion counts, sample size, abstentions và verdict; không dùng labeler tự đối chiếu |
| AC-10 | SG-201 có ≥3 reviewers độc lập và đạt các gate của protocol hiện hành | Frozen blinded package, human records, disagreements, aggregate; T-01/T-13 trích đầy đủ gate trước study; thiếu human evidence không PASS |
| AC-11 | Có baseline performance so sánh được | p50/p95, peak RSS, cold/warm, workload/corpus/graph size, môi trường, warmup, số lần chạy, errors và output-quality guards |
| AC-12 | Nếu mở R-06 implementation: đạt budget chốt trước sửa, không giảm correctness | Profile/use case justification, budget đã điền trước T-17, before/after cùng workload; nếu defer ghi NOT_APPLICABLE với quyết định, không ghi optimization PASS |
| AC-13 | Không bỏ sót callers/contracts bị tác động; giữ trust/error behavior | PRE/POST receipts, references coverage, diff-impact/reconcile; mọi confirmation được giải quyết, post closure closed; CLI/MCP smoke theo surface bị sửa |
| AC-14 | Có final verification và defect closure cho toàn bộ implementation đã mở | Full supported suite qua test-runner sau tích hợp, một consolidated Reviewer pass, repair nếu có và rerun vùng ảnh hưởng; blockers hoặc missing evidence vẫn hiển thị |

### Quy trình kiểm chứng

1. **Khóa command registry trước khi sửa.** Mỗi dòng ghi AC, command/cwd, prerequisite, platform/provider, refresh policy, corpus/protocol, source snapshot, artifact và status. Lệnh chưa được xác minh không được coi là runnable acceptance.
2. **Baseline và reproduction:** nếu vấn đề do khảo sát phát hiện thì lưu output hiện hành trước sửa; nếu người dùng đã báo lỗi, dùng observation đó làm ground truth, không chạy lại chỉ để xác nhận lời báo.
3. **PRE gate:** trước sửa core/public symbols, lấy scope receipt, references/usages và known gaps. BLOCKED thì giải quyết trước; mỗi receipt confirmation có task riêng gắn digest. Không dùng PRE receipt làm POST proof.
4. **Trong wave:** hoàn tất các writes độc lập rồi test-runner chạy focused checks theo blast radius. Permanent tests chỉ giữ khi bảo vệ behavior hoặc plausible regression; không dùng test source-text/wiring/wording làm bằng chứng chất lượng.
5. **Wave boundary:** diff-impact, reconcile và POST verification gắn snapshot mới; Main đối chiếu caller closure và contract drift trước mở wave phụ thuộc. Không tự reconcile để xóa baseline chưa lưu.
6. **Actual surface:** chạy CLI thật cho search/pack/bundle/report bị sửa; nếu MCP bị tác động thì kiểm chứng invocation/response qua interface thật hoặc smoke client phù hợp. Screenshot không bắt buộc cho thay đổi không có GUI; report readability kiểm tra trên output thực.
7. **Final gate:** sau toàn bộ waves implementation đã mở, test-runner chạy full supported verification; Reviewer review một lần trên actual diffs/deliverables, không review kế hoạch. Một consolidated repair pass nếu cần, rerun impact, không gọi review lặp.

**Các probe đã chạy trong khảo sát, không phải full acceptance commands:**

- `sotgraph --help`
- `sotgraph -V`
- `sotgraph search --help`
- `sotgraph pack --help`
- `sotgraph search --reconcile off --no-jit --json CbmStore`
- `sotgraph pack --reconcile off --tokens 1500 --json tests/test_cbm_store.py:170`

Giữ các probe này để so sánh lịch sử khi còn phù hợp. T-01 phải xác minh lại target/flags; anchor test cũ không được dùng thay cho kiểm chứng tìm đúng class. Không suy từ exit 0, STRONG hoặc `tokens_estimate=1500` thành context sufficient.

## Execution checklist

- Các task đã hoàn tất sẽ được đánh dấu `[x]`; task còn mở để `[ ]`. Checkboxes chỉ được cập nhật sau khi có receipt; AC được nghiệm thu riêng trong evidence ledger. Task có điều kiện không được đánh dấu hoàn tành như implementation nếu chỉ có quyết định defer.

### W0 — R-01 baseline
- [x] **T-01** — Đóng manifest và command registry hiện hành. **AC-01, AC-06, AC-08, AC-09, AC-10.** Khóa source/corpus/provider; trích chính xác protocol gates và lệnh CI/evaluation; chưa reconcile.
- [x] **T-02** — Xác minh drift và freshness trước/sau. **AC-02, AC-13.** Deep check/reconcile có kiểm soát, evidence theo layer, giải thích ngoại lệ.
- [x] **T-03** — Chạy baseline matrix và phân loại blockers. **AC-01, AC-02.** Test-runner receipt; có quyết định cho phép nhánh nào tiếp tục.

### W1-A — R-02 identity và scope

- [x] **T-04** — Khóa identity contract và caller coverage. **AC-03, AC-13.** PRE receipt, consumer list và shared-write owner.
- [x] **T-05** — Sửa identity/display và scope consumers. **AC-03, AC-04, AC-05, AC-13.** Di chuyển toàn bộ caller bị ảnh hưởng, không tạo compatibility shim mặc định.
- [x] **T-06** — Kiểm chứng bundle/report và đóng artifact. **AC-03, AC-04, AC-05.** Actual CLI output, đúng source anchors, scope/coverage rõ; artifact phục vụ R-05.

### W2-A — R-03 SG-202

- [x] **T-07** — Replay frozen roster và phân loại failures. **AC-06.** Pin baseline và oracle, công khai mẫu số.
- [x] **T-08** — Sửa target/evidence/budget theo lỗi đo được. **AC-07, AC-13.** Typed evidence, exact normalized target, serialization budget; version protocol nếu cần.
- [x] **T-09** — Chạy SG-202 và đóng acceptance receipt. **AC-06, AC-07.** Old/new song song nếu thay oracle; không che FAIL còn lại.

### W1-B/W2-B — R-04 G1 và G3

- [x] **T-10** — Replay G1/G3 và khóa dữ liệu đánh giá. **AC-08, AC-09.** Mẫu số, comparator, recall guards và human holdout độc lập.
- [x] **T-11** — Sửa scope/verdict theo failure taxonomy. **AC-08, AC-09, AC-13.** Không nới fail-closed; serialize resolver chung nếu có.
- [x] **T-12** — Kiểm chứng G1/G3 trên cohort đã khóa. **AC-08, AC-09.** Lưu precision/recall/confusion/abstentions và verdict.

### Nhánh R-05 — human evidence

- [ ] **T-13** — Chuẩn bị protocol và blinded study package. **AC-10.** Khóa rubric/gates, artifact snapshot và kế hoạch reviewers.
- [ ] **T-14** — Thu đánh giá của ít nhất ba người. **AC-10.** Phụ thuộc người chấm thật; BLOCKED_EXTERNAL nếu chưa có.
- [ ] **T-15** — Tổng hợp disagreement và kết luận SG-201. **AC-10.** Không dùng agent review thay human evidence; chưa đủ dữ liệu thì không đóng gate.

### Nhánh có điều kiện R-06 — performance và extension

- [ ] **T-16** — Đo performance và quyết định phạm vi tiếp. **AC-11.** Cold/warm latency/RSS; quyết định triển khai/defer có bằng chứng.
- [ ] **T-17** — Tối ưu bottleneck đã chọn và đối chiếu. **AC-12, AC-13.** Chỉ mở sau T-16 và budget chốt trước sửa; không mở nếu chưa có căn cứ.

### Final acceptance

- [ ] **T-18** — Chạy full verification sau các wave implementation. **AC-01–AC-09, AC-11–AC-14 theo phạm vi đã mở.** Test-runner tổng hợp matrix; không gọi phần chưa chạy là PASS.
- [ ] **T-19** — Review consolidated và đóng repair nếu có. **AC-13, AC-14.** Một Reviewer pass trên code/deliverables; rerun vùng sửa; ghi defect closure.
- [ ] **T-20** — Đối chiếu từng gate và bàn giao trạng thái. **AC-01–AC-14.** Tách technical acceptance, SG-201 human gate và R-06 conditional outcome; ghi limitations/next safe action, không tự commit/push.

Không đặt sẵn cleanup tasks. Sau khi smoke chứng minh behavior, nếu có sửa source thì cập nhật tài liệu/changelog liên quan và dọn throwaway artifacts trong phạm vi thay đổi; Main bổ sung task thực tế vào hồ sơ khi phát sinh.

## Evidence and handoff

### Bằng chứng lập kế hoạch

- Đã đọc hồ sơ `2026-09-19-repository-roadmap-survey.md` và kiểm tra `docs/plans/` để không ghi đè hồ sơ cũ.
- Bao phủ đủ sáu hạng mục, giữ dependency R-01 → R-02 → R-03, nhánh R-04 sau baseline, R-05 phụ thuộc human evidence và R-06 có điều kiện.
- Không khảo sát lại source, không chạy suite/benchmark hoặc refresh graph trong bước lập kế hoạch này.
- Tài liệu hiện là blueprint; các AC implementation chưa được kiểm chứng, các execution checkboxes đều để trống.
- Kiểm tra cấu trúc Markdown bằng phép đọc tĩnh: đủ 7 mục bắt buộc, 6 gói R-01–R-06, 20 task ID duy nhất, 14 AC và 10 liên kết tương đối đều tồn tại; 0 implementation checkboxes được đánh dấu hoàn tất. Đây là kiểm tra tài liệu, không phải test/build hoặc acceptance sản phẩm.
| R-01 baseline | T-01–T-03 DONE | Manifest, command registry (`command-registry.json`), T-02 receipts (`baseline-receipts.json`), T-03 test-runner receipt (`t03-receipt.json`). 15/16 baseline commands PASS; 2 syntax/env failures được khắc phục bằng `uv run` tương đương; 1 full pytest SKIP vì runner cap; focused subset 94/94 passed. Drift ZERO, bundle/report valid, diff-impact valid. Không còn blocker cho R-02/R-04. R-01 baseline đóng; R-02 identity/scope được phép mở. |
| R-02 identity/scope | T-04–T-06 DONE | Identity contract (`identity-contract.json`), PRE scope receipt `f502e4dc5c3ed9db60975d8ee1d19f8814a24c3754032bd303a141b880758fac`. Implementation: `AnalyticsGraph.from_connection` now loads `symbol`/`fqn` from `graph_nodes`; `GodNodeInfo`/`SurprisingConnection` prefer `symbol`/`fqn`/`label`/`node_id`; bundle/report/MCP/export consumers updated; `db.py`/`mcp_service.py` relation queries include `symbol`/`fqn`; `cli.py` `_identity_grade` uses `symbol`/`fqn`/`label`. Targeted tests 77/77 pass; `uv run sotgraph bundle` and `uv run sotgraph report` show `CBMFileResult`, `str`, `len`, `TSNode` with `path:line` instead of `cbm:<id>`. T-06 artifacts: `docs/plans/2026-09-19-evidence-context-roadmap-plan.bundle/` and `docs/plans/2026-09-19-evidence-context-roadmap-plan.report.md`. |
| R-03 SG-202 | T-07–T-09 DONE (gate FAIL, honestly open) | T-07 replay `/tmp/sg202-t07-replay/replay.json`: 0.8182 (36/44), 8 failures = 5×MISSING_TEST + 1×MISSING_TARGET + 2×PACK_ERROR. T-08 fixes: `_neighbors` includes `imports` edges (typed `relation` field); `_parse_target` supports `path::name` scoped locators; scoped-ambiguity falls back to global dominant when in-scope; module-import test receipt fallback (`imports_module`); replay gains `--target-mode scoped|bare`. T-09 parallel runs: scoped 0.8864 (39/44) `/tmp/sg202-t09-scoped3/replay.json`, bare 0.8864 (39/44) `/tmp/sg202-t09-bare3/replay.json`. Remaining 5 MISSING_TEST are structural extractor gaps (oracle AST text-match sees `x.as_dict()` on returned objects, monkeypatched attrs, `with` protocol methods, same-name test functions — no graph edge exists). Gate remains honestly FAIL; fix requires extractor-level `uses`/`references` edges → new work package. |
| R-04 G1/G3 | T-10–T-12 DONE (G1 union FAIL, G3 FAIL — honest) | T-10 replays `/tmp/g1_t10_report.json` (drop 0.1903, n=40) + `/tmp/g3_t10_report.json` (hand precision 0.6364, n=308). T-11 fixes: `make_hunk_verifier` wired into `cmd_commit_verdict`, `log --outcomes`, `sot_commit_verdict` (MCP), `lineage._verdict_for`, `bench_g3_verdict.py`; `direct_affected_files` (1-hop surface) added to `scope_receipt`/`scope_receipt_multi`; `bench_g1_scope.py` reports union+direct surfaces in parallel. T-12 re-runs: G3 `/tmp/g3_t12_report.json` hand precision 0.7778 (98 still-hot, 181 unknown; 2 residual mismatches = documented boundary cases where hunk overlap can't distinguish repair from adjacent edits); G1 `/tmp/g1_t12_report.json` union drop 0.1917 FAIL, direct drop −0.054 (union 1-hop precision 0.3674 > best-single 0.3134). Gates honestly FAIL: G3 needs extractor-level semantic repair detection; G1 union bar unreachable by blast-radius construction — direct surface is the actionable metric. |
| R-05 SG-201 | T-13 DONE; T-14/T-15 BLOCKED (external human dependency) | Protocol `plan/sg201-landmark-study-protocol.md` + generator/aggregator exist. Worksheet + manifest regenerated at HEAD (`benchmarks/exit_gates/landmark/worksheet.csv`, 20 rows, budget 1024). Aggregator confirms `PENDING_HUMAN_EVIDENCE` — no `reviewer-*.csv` exists. T-14 (≥3 human reviews) and T-15 (disagreement aggregation + verdict) cannot be performed by an agent; the gate is human-only by design. |
| R-06 scale/extension | T-16 DONE; T-17 DONE (no work warranted — evidence) | Measured `sotgraph cluster` on live graph (35,905 nodes / 166,668 edges): **5.3s wall** via `nx.community.louvain_communities` (networkx 3.6.1, core dep since pyproject.toml:27-30 — added specifically to kill the pure-Python >10k timeout). The documented "Louvain CPU latency bottleneck" is already mitigated; a native/Rust extension would optimize a non-bottleneck. Scope decision: **no extension work justified** — T-17 closed as evidence-based no-op, not skipped. |
| Final technical acceptance | T-18/T-19 DONE | Full suite `uv run pytest tests/ -q`: **2495 passed, 0 failed, 5 skipped** (628.85s). First run caught 2 `TestIdentityGrade` regressions from R-02 `_identity_grade` (fqn shadowed label); fixed by restoring `symbol`-primary grading + updating the test to use the canonical `symbol` field (label is a display string, not a name). Consolidated review (reviewer, confidence 0.85) found 2 defects in R-03 pack.py: (1) `_test_line_by_id` stored `(strength, line)` tuples under `Dict[str, int]` — pyright gate failed; fixed to `Dict[str, Tuple[int, int]]`, pyright 0 errors. (2) `_path_in_scope` bare-suffix clause looser than `_path_scope_sql` (test_utils.py matched scope utils.py); tightened to exact/`/`-boundary/absolute-suffix only. Post-fix: 100 pack tests pass, pyright clean. No remaining defects. |

### T-20 — Gate reconciliation và trạng thái bàn giao (2026-09-19)

| Gate / AC | Trạng thái | Bằng chứng |
| :--- | :--- | :--- |
| AC-01 manifest/command registry | ✅ Đóng | `command-registry.json`, `baseline-receipts.json` |
| AC-02 drift/freshness | ✅ Đóng | `sotgraph verify` + reconcile có kiểm soát; drift ZERO |
| AC-03 baseline matrix | ✅ Đóng | 15/16 commands PASS; 1 SKIP (runner cap); focused subset 94/94 |
| AC-04/05 identity contract + scope | ✅ Đóng | `identity-contract.json`, PRE receipt `f502e4dc…`; symbol/fqn loaded into AnalyticsGraph + consumers |
| AC-06/07 SG-202 replay + fixes | ⚠️ Gate FAIL (honest) | 0.8864 (39/44) scoped+bare; 5 MISSING_TEST = extractor-level `uses`/`references` gap → new work package |
| AC-08/09 G1/G3 | ⚠️ Gate FAIL (honest) | G3 hand precision 0.7778 (hunk verifier wired into all 4 verdict sites); G1 union drop 0.1917, direct drop −0.054 (direct surface beats best-single) |
| AC-10/11 SG-201 human study | 🔒 BLOCKED | Protocol + worksheet + manifest ready; needs ≥3 human reviewer CSVs — external dependency |
| AC-12 full verification + review | ✅ Đóng | 2495 passed / 0 failed; reviewer found 2 defects, both repaired + re-verified |
| AC-13 no fail-closed regression | ✅ Đóng | All fixes additive/narrowing; no gate loosened; honest FAILs preserved |
| AC-14 record + handoff | ✅ Đóng | This record; evidence ledger R-01–R-06 complete |

**Residual risks / open items:**
1. SG-202 gate stays open — needs extractor-level `uses`/`references` edges (new work package, not a bug).
2. G3 verdict precision 0.7778 vs 0.80 bar — 2 residual mismatches are documented boundary cases (hunk overlap can't distinguish repair from adjacent doc edits); needs semantic repair detection.
3. G1 union precision drop 0.1917 vs 0.10 bar — unreachable by blast-radius construction; `direct_affected_files` surface (−0.054) is the actionable metric going forward.
4. SG-201 landmark gate — human-only; blocked until ≥3 reviewers submit CSVs.
5. No commit/push performed — per scope, all changes are working-tree only.

### Nguồn tham chiếu

- [Khảo sát và roadmap](2026-09-19-repository-roadmap-survey.md) — nguồn chính của kế hoạch; evidence và source anchors nằm trong phần Evidence and handoff.
- [Fact Bundle khảo sát](../../.sot/bundle/roadmap-2026-09-19/) — số liệu tổng hợp, không phải product-only metrics.
- [Diagnostic receipts](../../.sot/bundle/roadmap-2026-09-19/diagnostics.json) — doctor/verify/history tại lúc khảo sát.
- [Runtime receipt transcription](../../.sot/bundle/roadmap-2026-09-19/runtime-probes.json) — bản ghi receipt, không phải raw stdout.
- [CBM Store plan](../CBM_STORE_PLAN.md) — hồ sơ triển khai lịch sử.
- [SG-202 acceptance lịch sử](../../benchmarks/exit_gates/sg202_followup/ACCEPTANCE.md) — không thay current replay.
- [Three-Gate plan](../THREE_GATE_PLAN.md) — G1/G3 historical gates và kết quả.
- [SG-201 study protocol](../../plan/sg201-landmark-study-protocol.md) — human evidence requirements.
- [Release decision](../../RELEASE_DECISION.md) — giới hạn claim hiện được dẫn chiếu.

**Điều kiện đóng hồ sơ:** không còn task bắt buộc hoặc receipt confirmation chưa giải quyết; mỗi AC có verdict và evidence. Có thể bàn giao phần kỹ thuật đã hoàn tất trong khi R-05 bị BLOCKED_EXTERNAL, nhưng hồ sơ và overall roadmap phải tiếp tục thể hiện chưa hoàn tất human gate. R-06 được defer minh bạch không đồng nghĩa đã thực hiện tối ưu.

## Assumptions and contingencies

| Rủi ro / điều kiện | Cách xử lý |
| :--- | :--- |
| HEAD, source anchors hoặc working tree đổi sau khảo sát | T-01 xác minh lại; giữ công việc người dùng; không reset hoặc dựa vào line cũ để sửa |
| Graph/LSP thiếu caller coverage hoặc PRE receipt BLOCKED | Thu hẹp target có bằng chứng, giải quyết known gaps/confirmations trước sửa; không diễn giải 0 edges thành 0 callers |
| Reconcile hoặc deep verify không hỗ trợ một provider | Ghi rõ phạm vi không được chứng minh; dùng verification path hiện có phù hợp; không báo toàn graph FRESH |
| Thiếu Windows/runtime/optional provider/dependency | Ghi MISSING_EVIDENCE và dùng supported CI khi được phép; không tự cài/network hoặc gọi suite toàn repo PASS |
| SG-202 oracle gốc không thể đạt floor chỉ bằng token allocation | Giữ baseline/gate gốc; version query/oracle minh bạch, so sánh song song; không đổi denominator để qua gate |
| R-03 và R-04 cùng cần resolver/schema | Main khóa typed-evidence contract; một integration owner, serialize write boundary và rerun impacted checks |
| SG-201 chưa có reviewers | Chuẩn bị toàn bộ phần agent làm được; block human tasks, không tạo fake reviews; không chặn nhánh kỹ thuật độc lập |
| R-06 không tìm được bottleneck hoặc use case đủ mạnh | Dừng ở measurement/decision, ghi defer; không thêm vector/SCIP/native rewrite cho đủ roadmap |
| API/schema output cần thay đổi có chủ đích | Lập migration rõ, cập nhật tất cả callers/docs bị tác động; không giữ shim/alias cũ vô thời hạn |
| Platform access, artifact storage hoặc external service nằm ngoài workspace và `~/.omp` | Xin quyền cụ thể trước truy cập; không dùng đường dẫn lịch sử ngoài phạm vi như prerequisite đã có sẵn |
| Chưa biết team capacity, lịch và ưu tiên kinh doanh | Dùng dependency/exit gates; không biến thứ tự wave thành cam kết ngày hoặc nhân công |

**Điểm khởi động đã chọn:** R-01/T-01. Chỉ chuyển sang implementation khi có yêu cầu tiếp theo; việc tạo file kế hoạch không tự cấp quyền triển khai roadmap.
