# Khắc phục và nghiệm thu chức năng sotgraph

Đã sửa 12 finding A01–A12 của khảo sát ban đầu và 9 nhóm vấn đề phát hiện thêm
trong quá trình kiểm thử. Các lỗi ban đầu không còn tái hiện trong probe/regression
đã chạy. Kết luận này giới hạn ở bằng chứng bên dưới; chưa chứng nhận mọi tổ hợp
OS, Python, grammar, provider và runtime đều không thể có bug.

Khảo sát bắt đầu 01/10/2026; nghiệm thu local 02/10/2026, Asia/Ho_Chi_Minh.
Base commit `9be1d24a61f2cd3fc895d9ab64c222f05c05a5e0`, version 0.3.8.
Phần chính của bản sửa nằm trong commit `ab21cb9c850eb38e1067de8f6fc99f0390757fe7` trên nhánh
`codex/functional-audit-remediation`; oracle claims được bind vào commit này.
Lỗi overflow của CLI được sửa bổ sung trên cùng nhánh sau kiểm tra Python matrix.
Workflow CI cũng được bind interpreter để kết quả matrix đúng phiên bản được ghi.
CSV review dùng LF; archive khảo sát gốc được giữ nguyên.
Hai thay đổi skill có sẵn trong `.omp` và `.opencode` được giữ nguyên.

## Finding và bản sửa

| ID | Bản sửa | Bằng chứng chính |
|---|---|---|
| A01 | Node cap luôn đồng bộ omitted, truncated và PARTIAL trong pack. | Regression cap 1/2/3; CLI/MCP probes. |
| A02 | Closure TypeScript/JS giữ identity của hàm/method bao ngoài. | Hai method cùng tên closure gọi hai callee khác nhau. |
| A03 | Python receiver/class/base được phân giải theo module, path và import; known virtual override abstain; import/re-export giải đến fixed point. | Receiver trùng tên khác module, re-export, inheritance và polymorphism tests. |
| A04 | Rust alias và call trong macro đánh giá argument; Java static import; sửa oracle TS để đo direct call. | Static oracle 236 file, 1.013 TP, 0 FN, 0 FP. |
| A05 | JSON error envelope có code; parser errors, provider/pack failures, secondary errors, SQLite integer overflow và schema-reset diagnostics giữ stdout parse được. | 87 CLI probes; error-boundary regressions trên Python 3.10–3.14; human receipt error giữ stderr. |
| A06 | Config validation chuyển thành diagnostic ở CLI boundary. | TOML malformed và wrong-type probes. |
| A07 | SQLite initialization/corruption lỗi có diagnostic; không ghi đè file DB lỗi. | Corrupt DB regression và doctor probe. |
| A08 | Receipt không tồn tại/malformed trả error có cấu trúc. | Missing PRE receipt và receipt explorer tests. |
| A09 | Dùng validators chung; từ chối bool/float cho integer, số âm/zero không hợp lệ, NaN/Infinity và threshold ngoài miền; integer vượt miền SQLite trả invalid_argument. | CLI/MCP/direct-core domain tests; limit 2**63 và 10**100 được chạy qua SQLite thực. |
| A10 | Lỗi thu thập Git được giữ trong result/receipt; risk UNKNOWN, assurance UNVERIFIABLE, safe_commit block, exit khác 0. | Invalid ref và non-Git tests; strict gate giữ exit 2. |
| A11 | Pack canonicalize root và node paths trước khi tính relative path. | macOS `/var`–`/private/var` và symlink-alias regression. |
| A12 | OMP dùng fixture, interpreter hiện tại, timeout và temp outputs; evaluation đóng DB trước cleanup; scoped/reference fixture không phụ thuộc `.sot/tmp`; pack test dùng source đủ lớn và đo YAML thay vì giả định metadata vừa 600 token. | 11 OMP test; bốn DB handle đóng; năm evaluation test/runtime; 32 scoped/reference test và pack test (native/fallback tokenizer) đạt trên Python 3.10–3.14. |
| A13 | SCIP protobuf đọc/ghi đúng documentation, relationship, kind, display name, signature và packed occurrence ranges; sửa escaping/URI/position encoding. | Index compiler thật, optional-field fixture từ SDK độc lập, fresh compiler E2E và independent export decode. |
| A14 | Daemon serialize startup giữa client bằng khóa ổn định; gửi initialize đúng RPC; frame stdout theo deadline; xử lý malformed JSON/PID; restart/retry; reap child, SIGTERM/idle cleanup; Windows dùng cold fallback. | Concurrent startup tái hiện 2 daemon trước sửa, sau sửa chỉ 1; strict MCP child, deadline/framing, crash/recovery và cleanup tests. |
| A15 | Receiver type không rò giữa function/block; untyped shadow không thừa hưởng kiểu của local scope khác. | TypeScript same-name variables, block shadow và unknown receiver test. |
| A16 | Watchfiles nhận stop_event và timeout tick; retry LockBusy dù không có edit mới. | Hai backend chạy create/modify/rename/delete thực, ignore và idle stop; retry regression. |
| A17 | Thành công của tool index chưa đủ để chuyển ownership: store phải đọc được, bound root và đạt schema contract trước khi bỏ builtin rows; regression assertion dùng đường dẫn native của OS. | Real CBM 0.10.8 thiếu store_meta tái hiện lỗi; contract fallback test và polyglot E2E đạt; 26 CBM store test đạt local sau sửa Windows path assertion. |
| A18 | Lockfile cập nhật PyJWT 2.13.0 → 2.15.1, urllib3 2.7.0 → 2.8.0. | pip-audit từ 16 advisory về 0 advisory đã biết. |
| A19 | Source verifier và manifest mới khớp gitlink/release pin e477a32d; giữ nguyên manifest lịch sử 46ae198f. | Hash/mode/blob verify 2.052 entries; live pin-parity test; native scratch build đạt. |
| A20 | Module-eval quy diagnostic Ruff absolute/relative path về đúng scope; quality gate giữ log pytest khi thất bại; dọn unused import và sửa parser type contracts. | Planted diagnostic bắt buộc gate fail; pytest failure marker trước sửa bị nuốt, sau sửa được in với stage; Ruff/Pyright toàn src đạt. |
| A21 | CI bind UV_PYTHON mặc định 3.12 và override theo matrix; assert interpreter trước pytest, gồm cả evaluation/tests/. | uv 0.12.10 thực: install 3.10 nhưng sync chọn 3.14 trước sửa; sau sửa dry-sync và live guard đúng cả năm runtime; guard từ chối interpreter sai. |

A13 được đối chiếu với [schema SCIP chính thức](https://raw.githubusercontent.com/sourcegraph/scip/main/scip.proto).
SCIP reference không bị suy thành call. Compiler E2E mới là gate release riêng;
fixture JSON tự dựng trong CBM E2E được ghi đúng là kiểm tra federation.

Các dependency được cập nhật theo release của [PyJWT](https://github.com/jpadilla/pyjwt/releases/tag/2.15.1)
và [urllib3](https://urllib3.readthedocs.io/en/stable/changelog.html). Kết quả scan
là trạng thái advisory tại thời điểm chạy, không phải bảo đảm an toàn vĩnh viễn.

## Kết quả chạy

| Kiểm tra | Kết quả | Phạm vi/giới hạn |
|---|---|---|
| Suite pytest tests/ và evaluation/tests/, Python 3.12 | 2.688 pass, 4 skip, 176 subtest pass; 439,21 giây | Mã production hiện tại, gồm hai regression overflow; trước điều chỉnh lifecycle fixture evaluation. |
| Full suite Python 3.10.20 / 3.11.15 | Mỗi runtime 2.685 pass, 5 skip, 176 subtest pass | Bản nguồn trước sửa boundary overflow; thêm skip do ast.parse chưa hỗ trợ PEP 695. |
| Full suite Python 3.13.13 / 3.14.4 | Mỗi runtime 2.686 pass, 4 skip, 176 subtest pass | Bản nguồn trước sửa boundary overflow; venv riêng, locked all-extras/dev. |
| CLI regression trên 5 runtime Python 3.10–3.14 | Mỗi runtime 78 pass, 0 skip | Bản nguồn cuối; chạy audit, CLI smoke/provider wiring và engine admin. |
| Evaluation fixture sau sửa lifecycle trên Python 3.10–3.14 | Mỗi runtime 5 pass, 0 skip | Dùng Database context manager để đóng handle trước cleanup; không thay đổi mã production. |
| CI interpreter selection, uv 0.12.10 | Năm dry-sync và năm live guard local đạt; negative guard đạt; 15 guard CI thực đạt | CI run đầu chọn đúng Python trên ba OS; suite còn lỗi fixture được nêu riêng bên dưới. |
| Native verifier focused | 38 pass | Gồm gate gitlink–manifest–release pins mới; không cần private source trong CI Python. |
| Linux aarch64, Python 3.12.14, root, case-sensitive FS | 211 pass, 2 skip | Container dùng init để reap orphan; hai skip dành riêng cho filesystem không phân biệt case. |
| Linux Python 3.12.14, package tối thiểu | 2 regression overflow pass | Core dependencies từ uv sync --locked --no-dev, không optional extra; pytest 9.0.2 cài riêng làm test tool. |
| CLI fixture probes | 87 case; 85 PASS, 2 kết quả phân loại chấp nhận | STOPPED watcher và empty map chủ ý exit 1; mọi lỗi contract cũ đã đóng. |
| MCP stdio | core 7, full 24, ops 26 tool PASS | Profiles và dispatch thực; không cộng số tool như testcase pytest. |
| Static oracle | 1.013 TP, 0 FN, 0 FP; 124 TN | Synthetic 236 file, 5 ngôn ngữ; không suy ra repo-wide recall. |
| Dynamic oracle | 5 exact observed claims, 0 wrong target, 21 abstention | 26 fixtures; tách khỏi static P/R/F1. |
| Holdout 11 repo thực | Các gate đều đạt | Denominator và sampling được công bố bên dưới. |
| Real CBM 0.10.8 E2E | PASS | Python, TypeScript, Go; federation, ledger, snapshots, fallback và receipts. |
| Fresh compiler SCIP E2E | PASS | scip-typescript 0.4.0; SDK độc lập decode export: 3 documents, docs/reference/relationship có dữ liệu. |
| Wheel/sdist build và isolated install | PASS, CLI 0.3.8 | Distribution smoke; không publish package. |
| Ruff/Pyright toàn src và changed modules | PASS; 0 type error | Pyright phân tích 99 file, 0 error/warning; module static gates và 12 strict probes đạt. |
| Bandit / pip-audit | PASS / 0 known vulnerabilities | Editable sotgraph được pip-audit skip theo thiết kế; source scan là Bandit. |
| Identity, claims lint, diff whitespace | PASS | Claims registry gắn metric với artifact; không chứng minh mọi product claim ngoài corpus. |
| Native experimental source/build | PASS | Current pin e477a32d; build trong scratch, không installer/UI hooks; chưa chạy toàn bộ C test suite hoặc certify các platform. |
| Reconcile / doctor / diff-impact / history | Đã chạy | Reconcile 0 failure; doctor healthy; impact vẫn phải đọc scope/gaps. |

Coverage statement toàn package **83,88%**, branch **75,65%**, combined **81,59%**.
Core statement **87,95%** trên 38 module theo COVERAGE_INCLUDES trong
scripts/quality_gates.sh; receipt statement **94,68%**, vượt floor 85%/90%.
Engine-daemon statement từ 25,38% lên 57,23%; watcher từ 53,41% lên 57,50%.
Lifecycle/event tests còn chạy child process nên coverage pytest process không
đại diện đầy đủ cho các nhánh thực thi trong child.

Các full suite Python 3.10/3.11/3.13/3.14 được chạy khi mã nguồn giữ ổn định;
thời gian lần lượt 428,53 / 424,18 / 428,24 / 430,57 giây. Sau đó, probe
`search --limit 10**100 --json` phát hiện OverflowError từ SQLite làm stdout
rỗng và lộ traceback. Hai regression tái hiện thất bại trước sửa. Boundary CLI
giờ trả JSON invalid_argument, exit 1, không traceback. Bản cuối được chạy full
suite Python 3.12 và 78 CLI regression trên cả năm runtime, cùng hai regression
trên Linux package tối thiểu. Không coi bốn full suite trước sửa là full suite
đã chạy lại trên bản cuối. Bốn skip macOS là root ownership, case-sensitive FS
và hai Windows Job Object; PEP 695 là skip bổ sung trên Python 3.10/3.11.

Holdout đo presence trên 6.725/6.725 task và false absence trên 5.707 definition;
0 false absence, 8 syntax files nằm ngoài scope. Impact recall macro **99,45%**
được tính trên **228/592** edge (364 bị sampling cap, 27 ambiguous ngoài scope).
Test-selection recall macro **100%** trên **23/23 task của 10/11 repo**;
jsonschema không có test reference thuộc mô hình, 10 attribute-only references
nằm ngoài scope. Retrieval Hit@1 **87,57%**, Hit@5 **96,36%**, MRR **0,9136**.
Không biến các mẫu đo này thành độ đầy đủ toàn repo.

Impact working tree ban đầu đo 60 file (gồm hai skill thay đổi từ trước), 282 node
trực tiếp, 960 caller và 1.715 test liên quan; risk HIGH, runtime 193,67 giây.
Receipt STALE khi cập nhật tài liệu/test fixture; gate block với 302 reference
UNRESOLVED/AMBIGUOUS. Sau commit b4171c4 và explicit reconcile, impact main...HEAD
đo 55 file, 276 node, 935 caller, 1.689 test; risk HIGH, runtime 192,08 giây.
Run này vẫn STALE do `.gitignore` và ba CSV không được journal index, cộng
unresolved budget/dynamic dispatch; safe_commit block với 334 reference.
Đây là chính sách fail closed của receipt với file chưa index, không phải bằng
chứng các CSV có nội dung lỗi hoặc 334 runtime bug.

Impact staged riêng cho sửa overflow đo hai file, bốn node, mười caller và
22 test; không stale file, nhưng assurance PARTIAL và gate block với sáu
reference chưa phân giải. Không sửa hoặc bỏ qua gate để tự nhận safe_commit.
Các receipt không có test-result provenance; graph gate không chứng nhận đã
chạy test. Kết quả suite/oracle/E2E ở trên là bằng chứng thực thi riêng và vẫn
cần review/CI.

Một run giữa lúc sửa annotation CLI đọc file chưa đủ import; run ổn định sau đó
đạt 2.686 test, rồi bản cuối đạt 2.688 test. Linux từng bị checksum download và
fixture sys.path; các lỗi setup đã được đóng. Container không init giữ grandchild
đã chết ở trạng thái zombie Z;
run có init đạt kiểm tra group kill. Các log trung gian được giữ trong archive.

## Nghiệm thu 15 tính năng

| Nhóm | Bằng chứng nghiệm thu |
|---|---|
| F01 Config/install/harness | Distribution smoke, malformed config, hermetic OMP, safe setup/maintenance và CI interpreter guard. |
| F02 Multi-language extraction/index | Static/dynamic oracle, lexical scopes, Rust/Java regressions, incremental reconcile tests. |
| F03 Search/trust axes | CLI/MCP probes, search oracle, holdout và SQLite overflow regression; axes vẫn là bounded heuristic. |
| F04 JIT/self-healing | Full freshness/concurrency regression; explicit final reconcile. |
| F05 Usages/hierarchy | Scoped classes, import/re-export fixed point, polymorphic abstention và resolver tests. |
| F06 Pack/budgets | Omission → PARTIAL, strict token tests, cap/alias regressions. |
| F07 Map/scope | Focus/budget suites, numeric validation; empty result không suy absence. |
| F08 SCIP/provenance | Actual compiler artifact, independent SDK optional fields/decode, truncation/import tests. |
| F09 Federation/engine | Real CBM polyglot E2E, contract-before-ownership fallback, ledger/binding suites. |
| F10 Receipts/lineage | Receipt floor đạt; assurance, snapshot, digest, safe-commit và history regression. |
| F11 Diff/history | Collection error giữ nguyên và fail closed; holdout impact/test selection gate đạt. |
| F12 MCP/parity | 3 stdio profiles; strict numeric/error boundary tests; provider policies. |
| F13 SQLite/notes | Doctor healthy; corruption diagnostics; migration/maintenance/concurrent-writer suites. |
| F14 Watcher/process | Real events cho 2 backend, daemon restart/framing/cleanup, Linux ownership tests. Windows Job Object còn cần runner Windows. |
| F15 Trace/bundle/export | Full regression và CLI probes; SCIP export được decode độc lập; native source/build checked. |

## Phần còn cần CI và cách review

Nhánh được push sau xác nhận và [draft PR #24](https://github.com/minhgv/sotgraph/pull/24)
được mở ngày 02/10/2026. [CI run đầu](https://github.com/minhgv/sotgraph/actions/runs/36943194155)
chạy Ubuntu/macOS/Windows × Python 3.10–3.14 tại head 1510c77. Claims lint,
diff-impact, oracle, SCIP, CBM E2E, module checks và packaging đã đạt. Suite
Ubuntu/macOS phát hiện sáu fixture case phụ thuộc `.sot/tmp` có sẵn trong
checkout local; fresh cwd tái hiện sáu lỗi rồi đạt 32/32 sau sửa trên năm Python.
Windows có thêm assertion CBM dùng đường dẫn pha trộn dấu phân cách; riêng
Python 3.11 có pack fixture giả định 600 token luôn đủ metadata. Pack từ chối
đúng khi metadata cần 622 token. Probe local với fallback tokenizer cũng cho
thấy giả định ngược: 11/12 lần bundle không cần truncate. Test mới dùng source
lớn, chạy native/fallback tokenizer và assert trực tiếp YAML <= cap, bỏ tolerance
25 token. Suite focused sau sửa đạt 72 test và 71 subtest. Quality gate được
sửa để in traceback/test summary khi pytest fail; không giảm coverage floor.

Cả năm Windows job đã chạy và đạt hai test Job Object, gồm kill grandchild khi
timeout. Suite Windows run đầu có 490–494 skip theo các điều kiện POSIX,
shebang exec và runtime/dependency trong test; các skip không được tính là PASS.
Run đầu đã kết thúc thất bại; cần run CI mới tại commit sửa fixture để nghiệm thu
matrix. Không coi probe local là kết quả matrix đã đạt.

Native CI dừng ở bước yêu cầu NATIVE_SOURCE_READ_TOKEN, trước checkout/build.
Người dùng chọn nghiệm thu native bằng bằng chứng local; không cấu hình token,
đổi settings hoặc biến preflight thất bại thành PASS. Source/build local ở pin
e477a32d vẫn là bằng chứng native được nghiệm thu trong phạm vi này.

Workflow trước đó chỉ chạy `uv python install <matrix-version>` rồi sync mà
không chọn interpreter. Với uv 0.12.10 và nhiều interpreter đã cài, probe thực
install 3.10 nhưng sync chọn 3.14.4. Bản sửa bind UV_PYTHON ở workflow/job và
assert minor version trước pytest; matrix cũng chạy evaluation/tests/ thay vì
chỉ tests/. Năm dry-sync local chọn đúng phiên bản, năm live guard đạt, guard
với actual 3.14/expected 3.10 fail đúng. Đây là kiểm chứng selection/guard ở
local, chưa phải remote CI pass.

Khi đưa evaluation/tests/ vào matrix, kiểm tra lifetime thấy bốn Database chưa
đóng sau test. Các fixture dùng context manager hiện có để đóng DB trước khi
TemporaryDirectory cleanup, kể cả assertion thất bại. Probe lifetime chuyển
từ bốn handle mở sang bốn handle đóng; cả năm evaluation test được chạy lại
trên năm Python runtime. Full suite 2.688 case chạy trước thay đổi fixture này;
mã production giữ nguyên. Hành vi xóa file trên Windows vẫn cần CI thực.

Native manifest cũ được giữ nguyên. Git diff 46ae198f → e477a32d chỉ thêm
`.github/workflows/engine-release.yml` và `docs/RELEASING-ENGINE.md`; không đổi C
source. Scratch build current pin tái dùng object của cùng C inputs rồi để make
kiểm tra dependency graph; đây là build smoke, không phải benchmark hiệu năng
hoặc native release certification.

Không tự đặt SLA production cho latency/RSS. Các hard cap/token checks hiện có
được giữ và test; các benchmark đo chỉ được báo với corpus/denominator thực.
Compiler/profile và runtime dynamic ngoài scope tiếp tục cần bằng chứng riêng.

Xem [evidence nghiệm thu](remediation-evidence.zip), [ma trận 180 edge case ban đầu](edge-cases.csv)
và [báo cáo trước sửa](REPORT.vi.md). Archive chứa logs, JSON/XML, regression
commands và SHA-256 manifest để tái kiểm tra mà không cần suy kết quả từ mô tả.
