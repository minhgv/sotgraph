# Khảo sát chức năng sotgraph tháng 10 năm 2026

Báo cáo này lưu trạng thái trước sửa. Kết quả khắc phục và nghiệm thu ngày
02/10/2026 nằm trong [REMEDIATION.vi.md](REMEDIATION.vi.md).

Repo có nền regression tốt nhưng **chưa đáp ứng yêu cầu 15 tính năng hoạt động hoàn hảo**. Ba vấn đề cần ưu tiên là pack báo complete khi bỏ caller, TypeScript gộp closure khác scope và Python nối receiver sang class trùng tên ở file khác. Các lỗi CLI quanh validation và error contract cũng đã tái hiện.

Ngày khảo sát: **01/10/2026**, timezone Asia/Ho_Chi_Minh. Version **0.3.8**, commit `9be1d24a61f2cd3fc895d9ab64c222f05c05a5e0`. Môi trường macOS arm64, Python **3.12.12**, SQLite **3.50.4**. Không sửa code production; các thay đổi skill tồn tại trước khảo sát được giữ nguyên.

## Phạm vi và cách đọc bằng chứng

Khảo sát source, CLI parser, service MCP, provider, test suite và các script benchmark có trong checkout. Toàn bộ 41 entry CLI cấp đầu gồm alias commits và 26 tool MCP đã được đối chiếu parser/registry và gán vào 15 nhóm trong [inventory command](command-inventory.csv). Đây là kiểm kê bề mặt, không đồng nghĩa từng lệnh/subcommand đã có end-to-end độc lập. Inventory source không tính vendor: 98 file Python, 53.060 dòng, 1.522 function/class kể cả nested. Source và disk được đối chiếu sau `sotgraph search`, `explore`, `usages`, `log`, `doctor`; search axes fresh vẫn là bằng chứng bounded, không phải compiler resolution.

**180 edge case là danh mục tình huống đã truy tìm, không phải tuyên bố đã chạy đủ mọi tổ hợp.** CSV ghi riêng tình huống đã tái hiện, probe đạt và nhánh có regression test liên quan nhưng chưa chứng minh tất cả biến thể. Các tổ hợp OS × Python × grammar × provider × filesystem × state × resource budget chưa thể kiểm chứng hết trên một máy.

[Ma trận 180 edge case](edge-cases.csv), [inventory testcase](test-inventory.csv), [dữ liệu kết quả](evidence-summary.json), [log và script tái hiện](evidence.zip). XML suite báo tổng 2.793 checks tính cả 176 subtest; CSV inventory liệt kê 2.617 testcase cơ sở.

## Kết quả thực thi

| Kiểm tra | Kết quả thực tế | Giới hạn |
|---|---|---|
| pytest tests/ với coverage nhánh | 2.612 pass, 5 skip, 176 subtest pass; 621,27 giây | 2.617 test cơ sở, không fail |
| Test packaging bị skip rồi chạy lại với setuptools cache | 1 pass | Đóng 1 skip; còn 4 skip theo môi trường |
| evaluation/tests/ | 5 pass | Độc lập với testpaths mặc định |
| Probe CLI và SQL trong fixture riêng | 87 case; 65 đáp ứng tiêu chí ban đầu | 2 case STOPPED watcher và empty map là hành vi thiết kế; sau phân loại 67 chấp nhận và 20 cần cải thiện contract |
| Probe tiếp theo | 6 CLI lỗi/receipt, 5 node cap, 2 alias path, 1 TS collision | Bằng chứng bổ sung, không cộng như 14 test regression đã pass |
| MCP stdio thật | core 7 tool, full 24 tool, ops 26 tool; handshake/search/dispatch đúng | Probe phát hiện node cap pack vẫn báo complete |
| CBM 0.10.8 thật | E2E script pass, federation/ledger/binding/receipt được assert | Fixture thực tế chỉ Python; SCIP artifact tự dựng, không chạy compiler sinh index |
| Wheel và sdist | Build và install isolated đều pass, CLI 0.3.8 | Không build private native submodule |
| Ruff và Pyright phạm vi core của quality gate | Pass; Pyright 0 error | Không chạy Bandit/pip-audit; không tuyên bố toàn bộ quality_gates.sh pass |
| Adapter docs, repository identity, claims lint | Pass | Claims lint là kiểm tra registry, không chứng minh mọi claim ngoài corpus |

Coverage statement toàn package **83.11%**, branch **74.88%**, combined **80.82%**. Phạm vi core theo script đạt statement **87.81%**, receipts **94.68%**, vượt các floor 85%/90%. Coverage này đo pytest process; CLI/harness chạy process hoặc interpreter khác có thể chưa được thu đầy đủ.

| Module cần xem kỹ | Statement | Line và branch combined |
|---|---|---|
| cli.py | 59.06% | 55.43% |
| watcher.py | 53.41% | 51.09% |
| engine_daemon.py | 25.38% | 23.78% |
| reconciler.py | 70.13% | 68.74% |
| mcp_server.py | 63.59% | 61.03% |
| mcp_service.py | 82.56% | 79.43% |
| trace.py | 76.65% | 73.98% |
| pack.py | 91.58% | 89.60% |

Bốn skip còn lại: đổi ownership sang UID khác cần root; test directory khác case cần filesystem case sensitive; hai test Windows Job Object cần Windows. Bộ test không thay thế kiểm chứng trực tiếp Linux/Windows và Python 3.10/3.11/3.13/3.14.

## Mười lăm tính năng cốt lõi

Đề xuất chọn 15 tính năng theo contract người dùng và đường dữ liệu. Một tính năng có thể gồm nhiều lệnh CLI dùng chung lõi. Điều kiện hoàn hảo là đúng dữ liệu, đúng provenance, có giới hạn tài nguyên, graceful error và hành vi nhất quán trên bề mặt được hỗ trợ.

| ID | Tính năng | Điều kiện phải đạt | Đánh giá |
|---|---|---|
| F01 | Cài đặt cấu hình và tích hợp harness | Wheel và sdist chạy CLI đúng version; thứ tự config defaults rồi TOML rồi env rồi override; setup lặp lại không làm hỏng nội dung người dùng. | Cần cải thiện theo findings/coverage |
| F02 | Trích xuất và lập chỉ mục đa ngôn ngữ | Định nghĩa và cạnh đúng identity và span; parse lỗi không giữ cạnh xác nhận sai; reconcile incremental tương đương rebuild. | Cần cải thiện theo findings/coverage |
| F03 | Tìm kiếm xếp hạng và trust axes | Search trả anchor xác minh trên disk; identity trùng phải ambiguous; ranking và giới hạn đầu ra nhất quán giữa CLI và MCP. | Cần cải thiện theo findings/coverage |
| F04 | JIT freshness và tự phục hồi | Gated query phải thấy nội dung mới hoặc công bố stale; async fast tier và deep tier phải giữ snapshot nhất quán. | Đạt các luồng đã test; còn khoảng trống môi trường |
| F05 | Truy vết usages và kế thừa | Calls imports extends implements truy được hai chiều; unknown và ambiguous không chọn ngẫu nhiên; rename giữ đúng bản chất report only. | Cần cải thiện theo findings/coverage |
| F06 | Context pack và giới hạn tài nguyên | Payload giữ identity target và contract quan trọng; số token thực không vượt budget; mọi omission do budget phải đồng bộ truncated completeness accounting. | Cần cải thiện theo findings/coverage |
| F07 | Repo map và scope | Map ưu tiên production và công bố phần bị loại; focus và PageRank không vượt budget hoặc suy absence ngoài index. | Cần cải thiện theo findings/coverage |
| F08 | Import SCIP và compiler provenance | Compiler evidence chỉ exact khi symbol range root và snapshot đều được kiểm chứng; malformed import không publish partial như complete. | Fixture pass; chưa chạy compiler sinh index thật |
| F09 | Provider federation và managed engine | Registry capability policy chính xác; fallback disclosed; store và ledger bound canonical root snapshot version. | Đạt các luồng đã test; còn khoảng trống môi trường |
| F10 | Assurance receipt và lineage | Sáu trạng thái assurance nhất quán; digest bind scope snapshot và evidence; không nâng confidence khi thiếu coverage hoặc bị cắt. | Cần cải thiện theo findings/coverage |
| F11 | Diff impact lịch sử và safe commit | Changed lines map đúng node; reverse traversal đúng tests/API; git failure và missing evidence không biến thành báo cáo an toàn. | Cần cải thiện theo findings/coverage |
| F12 | MCP transport profile và parity | Discovery và dispatch cùng allowlist; startup và lỗi có cấu trúc; response cap và parity với CLI giữ trust semantics. | Cần cải thiện theo findings/coverage |
| F13 | SQLite bảo trì và ghi chú bền vững | Atomic publication và WAL bảo toàn dữ liệu; schema FTS thống nhất; clean all bảo toàn notes trừ khi explicitly include notes. | Cần cải thiện theo findings/coverage |
| F14 | Watcher process và concurrency | Watcher fold event đúng; stop theo process identity; subprocess timeout output cap và kill group không làm hại process khác. | Đạt các luồng đã test; còn khoảng trống môi trường |
| F15 | Trace analytics bundle và export | Artifact đọc được và scope honest; facts không thành kiến trúc chắc chắn khi heuristic; export escape metadata và deterministic. | Cần cải thiện theo findings/coverage |

## Lỗi và điểm cần cải thiện đã xác minh

P1: dữ liệu hoặc trust contract có thể dẫn agent tới kết luận sai. P2: lỗi chẩn đoán, interoperability, edge coverage hoặc vận hành. Chưa xác minh lỗi P0 trong phạm vi khảo sát.

### A01 Pack bỏ caller nhưng vẫn báo complete

**P1.** Tình huống: `pack normalize --max-nodes 1 --json`. discovered=5, returned=2, omitted callers=3 nhưng truncated=false và COMPLETE_WITHIN_INDEX_CAPABILITY. MCP core/full/ops tái hiện cùng kết quả.

Điểm xử lý: `pack.py:841, pack.py:1200`. Đề xuất: Đồng bộ mọi node_cap với truncated và completeness; thêm assertion omission kéo theo partial trên CLI và MCP.

Bằng chứng trong evidence.zip: `pack-nodecap-probes.json`, `mcp-stdio.json`.

### A02 TypeScript gộp closure khác lexical scope

**P1.** Tình huống: `Hai method Stage.first và Stage.second đều có const inner`. Chỉ có một node Stage.inner; node này có calls tới cả normalizeA và normalizeB. Hai method bị gộp graph qua closure chung.

Điểm xử lý: `ts_extract.py:647`. Đề xuất: Identity closure phải chứa cả method scope; kiểm tra hai closure trùng tên và giữ span riêng.

Bằng chứng trong evidence.zip: `ts-closure-collision.json`, `oracle-inspection.json`.

### A03 Python receiver nối sang class ở file khác

**P1.** Tình huống: `notify_dynamic(base: Notifier) trong py_pkg/dyn/dispatch.py`. Cạnh confirmed trỏ Notifier.send ở py_pkg/dyn/inheritance.py dù file dispatch có Notifier riêng. Đây là sai identity, ngoài giới hạn dynamic dispatch vốn cần công bố.

Điểm xử lý: `db.py:1864, db.py:2013`. Đề xuất: Phân giải type theo module và lexical scope trước bare class name; giữ unresolved nếu runtime dispatch không chứng minh được.

Bằng chứng trong evidence.zip: `oracle-inspection.json`, `oracle.json`.

### A04 Bỏ sót cạnh Rust và Java trong oracle

**P2.** Tình huống: `Rust import alias, Rust trait self.area, Java static import`. Rust digest -> hash_data, Circle.describe -> Circle.area và Java UseStatic.check -> Validator.isValid bị bỏ sót. Oracle static còn 4 FN tổng gồm TS closure.

Điểm xử lý: `scripts/sot_evaluator.py:1304, scripts/sot_evaluator.py:1614`. Đề xuất: Thêm resolver cho các trường hợp static đã chứng minh; không ép heuristic thành compiler exact.

Bằng chứng trong evidence.zip: `oracle.json`.

### A05 Các nhánh lỗi JSON trả văn bản

**P2.** Tình huống: `pack --tokens 1 --json; pack stale --json; usages --provider require:scip --json`. Exit khác 0 là đúng nhưng stdout không phải JSON; client automation phải đổi parser theo nhánh lỗi.

Điểm xử lý: `cli.py:1117, cli.py:667`. Đề xuất: Chuẩn hóa error envelope gồm code message candidates freshness trên mọi nhánh --json.

Bằng chứng trong evidence.zip: `functional-probes.json`.

### A06 Config lỗi gây traceback qua CLI

**P2.** Tình huống: `reconcile --json với TOML lỗi hoặc allow_external="banana"`. ValueError từ load_config không được cmd_reconcile chuyển thành error có cấu trúc. Unit loader đúng nhưng CLI contract chưa đủ.

Điểm xử lý: `cli.py:906, config.py:240`. Đề xuất: Catch validation error ở command boundary và giữ diagnostic path key.

Bằng chứng trong evidence.zip: `functional-probes.json`.

### A07 Doctor crash khi file DB không SQLite

**P2.** Tình huống: `doctor --json với sot.db chứa bytes không phải SQLite`. sqlite3.DatabaseError tại PRAGMA journal_mode=WAL thoát ngoài initialization handler.

Điểm xử lý: `db.py:503, cli.py:3281`. Đề xuất: Catch sqlite3.DatabaseError và trả corruption diagnostic; không tự ghi đè DB hoặc notes.

Bằng chứng trong evidence.zip: `functional-probes.json`.

### A08 Receipt không tồn tại gây traceback

**P2.** Tình huống: `diff-impact --pre-receipt no-such-file.json --json`. FileNotFoundError từ _resolve_receipt_input không được cmd_diff_impact xử lý.

Điểm xử lý: `cli.py:1781, cli.py:1849`. Đề xuất: Bắt lỗi receipt reference JSON schema và digest trước pipeline; error envelope rõ.

Bằng chứng trong evidence.zip: `extra-probes.json`.

### A09 Validate numeric không nhất quán

**P2.** Tình huống: `Limit và depth âm, threshold NaN/Infinity, pack nodes/hops/bytes âm`. Nhiều lệnh CLI trả exit 0; search limit âm trả rỗng, map budget âm trả zero symbols, pack có metadata budget âm. MCP search và byte/token budget có validation tốt hơn. Không có bằng chứng limit âm mở unbounded SQL.

Điểm xử lý: `cli.py:2772, cli.py:2980, mcp_service.py:466`. Đề xuất: Chia sẻ validators giữa parser service core API; phân biệt zero hợp lệ với số âm và nonfinite.

Bằng chứng trong evidence.zip: `functional-probes.json`.

### A10 Git collection error bị biến thành diff rỗng

**P2.** Tình huống: `diff-impact definitely-not-a-valid-ref --json hoặc repo không Git`. Exit 0, changed_files=[], LOW risk, warnings=[]; nested assurance vẫn UNVERIFIABLE và safe_commit=block. Strict gate trả 2. Không phải bypass safe commit, nhưng diagnostic thất bại bị mất.

Điểm xử lý: `diff_impact.py:289`. Đề xuất: Truyền git stderr và collection_error qua pipeline; phân biệt empty successful diff với unavailable diff.

Bằng chứng trong evidence.zip: `extra-probes.json`, `functional-probes.json`.

### A11 Relative path pack lệch canonical root

**P2.** Tình huống: `Root qua alias /var và /private/var trên macOS hoặc symlink root`. Target relative_path chứa ../../../../../../../private/var/... thay vì util.py; missing span hint dùng cùng đường dẫn traversal. Đây là lỗi biểu diễn path, chưa có bằng chứng đọc file ngoài canonical repo.

Điểm xử lý: `pack.py:723, pack.py:851`. Đề xuất: Canonicalize root trước relpath và kiểm tra commonpath; kiểm chứng alias root trên CLI và MCP.

Bằng chứng trong evidence.zip: `path-alias-probes.json`, `extra-probes.json`.

### A12 Integration suite phụ thuộc checkout và interpreter thực

**P2.** Tình huống: `TestOMPIntegrationScenarios.run_sot truyền --db nhưng cwd=REPO_ROOT và thiếu --root`. Launcher bin dùng python3 hệ thống 3.14 thay vì venv 3.12; qdb có thể đọc CBM store hiện hữu của repo. Suite ghi GRAPH_REPORT.md ignored trong checkout. Hai scenario mất 33.818s và 81.250s ở máy này.

Điểm xử lý: `tests/test_omp_integration.py:47, bin/sotgraph:9`. Đề xuất: Fixture repo root riêng, interpreter sys.executable, timeout subprocess và output_dir temp; tách real-repo smoke khỏi unit regression.

Bằng chứng trong evidence.zip: `pytest.xml`, `source-inventory.json`.

## Cách diễn giải các benchmark

Exact edge oracle có 236 file, 1.162 ground truth records trên 5 ngôn ngữ. Static precision 99,90%, recall 99,60%, F1 99,75%; 1 FP và 4 FN. Dynamic corpus gồm 26 case: 4 claim đúng, 1 claim same bare name sai, 21 không claim. Dynamic metrics được tách khỏi static precision/recall, nên static gate pass không có nghĩa dynamic dispatch đúng.

Chênh lệch TypeScript trong oracle cần xem lại **quy ước cạnh trực tiếp và bắc cầu**. Source có normalizeStage gọi inner, rồi inner gọi normalize; oracle kỳ vọng normalizeStage gọi normalize tại line gọi inner. Đồ thị hiện trả hai cạnh trực tiếp nên không nên chỉ dựa FP/FN này để kết luận mọi cạnh đều sai. Lỗi A02 được chứng minh bằng fixture riêng có hai closure cùng tên bị gộp; lỗi này độc lập với quy ước oracle.

Search benchmark với 48 planted probe đạt Hit@1/5/10 và MRR 100%. Search corpus polyglot 20 query của exact oracle chỉ đạt Hit@1 65%, Hit@5 100%; riêng ambiguous Hit@1 33,33%. Hai corpus khác nhau, không dùng kết quả planted để tuyên bố search luôn chính xác ở top 1. Diff-impact benchmark đạt P/R/F1 100% cho 6 scenario dựng trước; chưa chứng minh monorepo thực, mọi ngôn ngữ hoặc mọi semantic break.

## Edge case theo từng tính năng

Mỗi nhóm dưới đây có 12 tình huống với expected outcome trong CSV. Danh sách module là test liên quan thực sự tồn tại và được thu trong lần pytest này; test cùng nhóm không tự chứng minh từng edge case hoặc mọi tổ hợp. Đặc biệt unit config loader có thể pass nhưng CLI config vẫn crash.

### F01 Cài đặt cấu hình và tích hợp harness

Lõi được truy tìm: `cli.build_parser, config.load_config, adapters.installer`.

Tình huống: Cài wheel trong môi trường sạch; Cài sdist trong môi trường sạch; Python tối thiểu và tối đa được hỗ trợ; Thiếu dependency tùy chọn; Root chứa khoảng trắng hoặc Unicode; TOML sai cú pháp; TOML sai kiểu hoặc giá trị enum; Env mâu thuẫn TOML; Setup hai lần cùng harness; Setup workspace only; Root hoặc file cấu hình là symlink; Launcher bin dùng Python khác venv.

Test liên quan: `test_adapter_docs_consistency`, `test_cli_smoke`, `test_completion_surface_packaging`, `test_config_loader`, `test_omp_integration`, `test_p3_adapters`, `test_repository_identity`.

### F02 Trích xuất và lập chỉ mục đa ngôn ngữ

Lõi được truy tìm: `reconciler.Reconciler, extractor, ts_extract, db.Database._resolve_pending_edges_pass`.

Tình huống: Repo rỗng không có file code; File có syntax error hoặc parse partial; File rất lớn hoặc hàng cực dài; File encoding sai hoặc binary giả source; Nested function hoặc closure TypeScript; Import alias hoặc static import Java và Rust; Self receiver và trait method Rust; Python lambda comprehension và shadowing; Virtual dispatch reflection hoặc function pointer; Thêm sửa xóa và đổi tên file; File đổi khi worker đang parse; Workers chạy nối tiếp và song song.

Test liên quan: `test_c_cpp_extractor`, `test_dart_extractor`, `test_force_reindex`, `test_group1_extractors`, `test_group2_extractors`, `test_java_extractor`, `test_lambda_comprehension_coverage`, `test_multilang`, `test_parallel_reconciler`, `test_php_extractor` và các module còn lại trong CSV.

### F03 Tìm kiếm xếp hạng và trust axes

Lõi được truy tìm: `cli.cmd_search, db.Database.search_fts, verifier.TrustVerifier`.

Tình huống: Query trống hoặc toàn whitespace; Query chứa quote NEAR dấu sao hoặc SQL text; Symbol và đường dẫn tiếng Việt; Bare name trùng nhiều module; Path qualified hoặc semantic query; Scope chứa phần trăm underscore hoặc backslash; Scope path giống từ trong body; Limit bằng 0 âm hoặc quá lớn; Threshold NaN Infinity hoặc ngoài khoảng; Anchor đã xóa hoặc chuyển vị trí; Hybrid vector chưa embed hoặc thiếu extra; Top k cắt candidate đúng target.

Test liên quan: `test_p4_ranking`, `test_p4_search_safety`, `test_precision_and_metamorphic`, `test_search_bare_name_ranking`, `test_trust_axes`, `test_trust_v2_evidence`, `test_truthfulness`, `test_vector`, `test_verifier`.

### F04 JIT freshness và tự phục hồi

Lõi được truy tìm: `freshness.ensure_fresh, freshness.staleness_probe, engine_daemon`.

Tình huống: Index fresh; Sửa file giữa hai query; Thêm file chưa journal; Xóa file đã index; Mode off; Mode force; Mode auto async; DB bị lock hoặc parse failure khi heal; Background spawn thất bại; PID chết hoặc lock stale; Sửa cùng size trong cùng millisecond; Đổi branch hoặc delta vượt fast tier cap.

Test liên quan: `test_jit_freshness`, `test_jit_reconcile`, `test_p0_freshness_semantics`, `test_reconcile_audit_receipts`, `test_snapshot_content_binding`.

### F05 Truy vết usages và kế thừa

Lõi được truy tìm: `cli.cmd_explore, cli.cmd_usages, db.Database.usages, inheritance_edges`.

Tình huống: Đồ thị có cycle tự gọi hoặc recursion; Depth bằng 0 âm hoặc rất lớn; Symbol không tồn tại; Bare name ambiguous; Call ở nhiều dòng cùng caller; Import và re export xuyên module; Kế thừa nhiều lớp interface abstract; Caller vừa là test vừa là production name; File rename làm đổi FQN; Edge pending unresolved hoặc ambiguous; Rename plan; Cạnh compiler và heuristic mâu thuẫn.

Test liên quan: `test_edge_lifecycle`, `test_import_resolution`, `test_navigation`, `test_p3_builtin_recall`, `test_p4_identity`, `test_scoped_identity`, `test_wrong_edge_corpus`.

### F06 Context pack và giới hạn tài nguyên

Lõi được truy tìm: `pack.build_bundle, pack.render_yaml, cli.cmd_pack`.

Tình huống: Target unique và budget rộng; Target không tồn tại hoặc path line sai; Bare name ambiguous hòa điểm; Target disk stale khi reconcile off; Tokens dưới metadata floor; Tokens ngay trên dưới boundary; Node cap cắt caller hoặc callee; Hops nodes hoặc bytes âm; Source quá lớn vượt read cap; Caller test cạnh tranh với callee contract; Byte cap dưới metadata floor; Root là symlink hoặc var private var alias.

Test liên quan: `test_pack_sg202_priority`, `test_pack_target_recovery`, `test_sg202_pack_completeness`, `test_sprint4_compass_and_pack`.

### F07 Repo map và scope

Lõi được truy tìm: `repo_map.build_repo_map, repo_map.pagerank, classify_path`.

Tình huống: Repo chưa index hoặc rỗng; Graph không có edge; Graph cycle hoặc hub rất lớn; Focus không tồn tại; Focus nhiều symbol và path; Tokens bằng 0 âm hoặc rất nhỏ; Production test fixture vendor generated docs tooling; Include category không hợp lệ; Symbol trùng ở production và test; Scope alias hoặc path ngoài root; Map bị cắt giữa dòng Unicode; Map không chứa symbol có trong repo.

Test liên quan: `test_repo_map`, `test_sg201_external_corpus`, `test_sg201_repo_map_filters`, `test_sg201_sg202_exit_gates`.

### F08 Import SCIP và compiler provenance

Lõi được truy tìm: `importer.scip.ScipImporter, providers.scip.ScipProvider, translate_scip_range`.

Tình huống: SCIP JSON hợp lệ; SCIP protobuf hợp lệ; Varint bị cắt hoặc message size sai; Thiếu hoặc không đọc được file index; Range 3 hoặc 4 phần tử và UTF16 columns; Path absolute traversal hoặc symlink escape; Definition và reference cùng symbol; Symbol grammar escaped hoặc local symbol; File đã đổi sau lúc tạo compiler index; Import cùng artifact nhiều lần; Compiler identity trùng bare name; Provider SCIP thiếu capability impact.

Test liên quan: `test_identity_join`, `test_import_resolution`, `test_p3_scip_binding`, `test_scip_provider`, `test_scip_truncation`.

### F09 Provider federation và managed engine

Lõi được truy tìm: `providers_registry, providers.codebase_memory, providers.managed, cbm.reconcile_dispatch`.

Tình huống: External tắt mặc định; Require provider không cài; Auto provider chết hoặc timeout; Provider version không tương thích; Config command không trusted; PATH shadowing hoặc command argument injection; Engine JSON malformed hoặc stream vượt cap; Snapshot SHA manifest generation mismatch; Nhiều repo chung engine store; Builtin fast tier cạnh tranh engine snapshot; Native socket path quá dài và daemon restart; CBM thật và index SCIP trong luồng end to end.

Test liên quan: `test_cbm_adapter`, `test_cbm_exact_compatibility`, `test_cbm_managed_provider`, `test_cbm_snapshot_p2`, `test_cbm_store`, `test_managed_execution`, `test_managed_read_dispatch`, `test_managed_transport`, `test_provider_compatibility`, `test_provider_contract` và các module còn lại trong CSV.

### F10 Assurance receipt và lineage

Lõi được truy tìm: `assurance.receipts, assurance.state, assurance.impact_pipeline, receipt_explorer`.

Tình huống: Scope unique fresh covered; Scope missing ambiguous hoặc partial targets; Thay đổi HEAD giữa pre và post receipt; Receipt digest sửa tay hoặc schema tương lai; Receipt path không tồn tại; Symlink retarget hoặc repo root khác; Coverage chưa đo hoặc parse failures; Response bị trim do resource cap; Unjournaled file hoặc unsupported grammar; Ledger conflict hoặc stale provider run; Store receipt thất bại do disk lock; Receipt show diff chain thiếu predecessor.

Test liên quan: `test_assurance_state`, `test_collection_accounting`, `test_coverage_manifest`, `test_lineage_chain`, `test_mcp_receipt_tools`, `test_p6_ledger`, `test_p7_receipts`, `test_scope_receipt_multi`, `test_scope_receipt_recovery`, `test_sg205_receipt_explorer`.

### F11 Diff impact lịch sử và safe commit

Lõi được truy tìm: `diff_impact.GitDeltaExtractor, DiffImpactEngine, CommitHistoryEngine, assurance.resolution`.

Tình huống: Sửa body và signature API; Rename hoặc delete file symbol; Staged unstaged và untracked; Repo không Git hoặc ref không tồn tại; Root commit không có parent; Filename quote tab newline backslash Unicode; Binary mode only và submodule changes; Depth cap và graph cycle; Test shaped callers và fixture code; Getattr args kwargs re export và non Python semantic breaks; Caller supplied test report giả provenance; Gate timeout SIGALRM hoặc Windows no SIGALRM.

Test liên quan: `test_commit_verdict`, `test_diff_impact`, `test_diff_impact_github`, `test_history_retention`, `test_impact_pipeline`, `test_precommit_gate`, `test_resolution_ledger`, `test_safe_commit_gate`, `test_semantic_breaks`, `test_test_impact_split`.

### F12 MCP transport profile và parity

Lõi được truy tìm: `mcp_server.create_server, mcp_service.McpService, sanitize_transport_value`.

Tình huống: Handshake qua process stdio thật; Profiles core full ops; Gọi hidden writer trực tiếp bằng RPC; Profile env sai và flag override; Argument unknown bool float âm NaN; Output directory traversal hoặc symlink; Response vượt byte cap hoặc một record quá lớn; Invalid UTF8 surrogate control chars; Request concurrent và client disconnect; Freshness reconcile thất bại; Pack node cap trên CLI và MCP; SDK extra chưa cài.

Test liên quan: `test_accounting_contract`, `test_managed_policy_parity`, `test_mcp`, `test_mcp_modern`, `test_mcp_profiles`, `test_mcp_prompts`, `test_mcp_receipt_tools`.

### F13 SQLite bảo trì và ghi chú bền vững

Lõi được truy tìm: `db.Database.integrity_check, plan_clean, apply_clean, cli.cmd_insert`.

Tình huống: Database file bị corrupt hoặc không SQLite; Schema cũ hoặc migration fail; FTS mismatch orphan node hoặc foreign key violation; Clean stale file và dangling edge; Clean all không include notes; Clean all include notes; Dry run clean và vacuum; WAL hard kill giữa transaction; ENOSPC hoặc connection drop; Concurrent reader writer; Lock timeout replace hoặc unlink lock; Database read only hoặc directory permission denied.

Test liên quan: `test_core_safety_fixes`, `test_hardening_fixes`, `test_history_retention`, `test_maintenance`, `test_p9_chaos_migration`, `test_storage_integrity`, `test_v2_upgrade`.

### F14 Watcher process và concurrency

Lõi được truy tìm: `watcher.run_watch, start_daemon, stop_daemon, proc.run_command, engine_daemon`.

Tình huống: Watcher chưa chạy và status request; Create modify rename delete burst; File bị ignore và dot directory; Watchfiles chưa cài; LockBusy khi batch reconcile; Daemon start hai lần đồng thời; PID reuse hoặc stale PID file; Symlink repo hoặc multi project watcher; SIGINT SIGTERM và child grandchild; Output quá lớn hoặc child ghi liên tục; Timeout spawn error và env secrets; Windows Job Object và macOS LaunchAgent systemd.

Test liên quan: `fault`, `property`, `test_engine_daemon`, `test_monorepo_ledger_concurrency`, `test_proc_environment`, `test_proc_process_group`, `test_proc_runner`, `test_proc_streaming_cap`, `test_proc_windows_job`, `test_watcher_daemon`.

### F15 Trace analytics bundle và export

Lõi được truy tìm: `trace.trace_fullstack, solution.generate_solution_bundle, analytics.bundle, export`.

Tình huống: Bundle facts; Graph rỗng hoặc không có edge; Hub nhiều node hoặc hàng chục nghìn node; Trace endpoint symbol ticket không tồn tại; UI branch API binding từ regex body; Solution inventory và steps; Architecture flow target không tồn tại; HTML metadata chứa script quote hoặc closing tag; GraphML JSON GraphRAG SCIP export; Obsidian filename collision Unicode reserved names; Scope tests hoặc repo path filter; Các bước integration dùng root checkout thật.

Test liên quan: `test_analytics`, `test_arch_flow`, `test_arch_html`, `test_arch_module`, `test_bundle`, `test_bundle_conformance`, `test_export`, `test_report_conformance`, `test_solution_trace`.

## Database của repo và giới hạn suy luận

Doctor trước và sau test đều healthy, SQLite quick_check ok, schema 8, WAL, FTS sync, không orphan node. Builtin slice có 608 path, 7.216 node, 18.789 edge; pending 15.682 gồm 889 ambiguous và 14.793 unresolved. Engine read-through có 36.330 node và 197.369 edge.

Số pending không tự chứng minh bug: một phần có thể là external/dynamic/symbol chưa phân giải. Không cộng hai store để thành coverage repo và không dùng tỷ lệ pending như recall thực. Cần breakdown theo language, relation, dynamic/external, scope và actionable debt để người dùng hiểu mức thiếu bằng chứng.

## Thứ tự cải thiện và điều kiện nghiệm thu

1. Sửa A01, A02, A03 trước. Regression phải có pack node cap ở mọi bề mặt, hai closure trùng tên trong hai method, hai class trùng tên ở hai module. Không cho confirmed edge sai identity hoặc omission báo complete.
2. Chuẩn hóa A05–A10 ở command boundary. Mọi --json phải có error envelope parse được; malformed config, corrupt DB, receipt thiếu và ref sai phải có code rõ. Chia sẻ domain validation và không làm mất git collection error.
3. Sửa A11 và làm hermetic A12. Fixture root và interpreter explicit; timeout subprocess; output ghi temp; kiểm tra canonical path trên macOS aliases và Windows case behavior.
4. Đóng A04 bằng fixture static và bổ sung release oracle độc lập cho mỗi grammar/provider combo được quảng cáo. Tách zero wrong-identity gate, dynamic misresolution gate và tolerated static recall budget.
5. Mở rộng kiểm chứng các nhánh còn yếu theo coverage: watcher/daemon, CLI failure surfaces, trace/solution heuristic. Chạy Windows Job Object, Linux service, case-sensitive filesystem, ownership isolation trên đúng môi trường.
6. Thêm holdout thực cho monorepo, multi-language provider, compiler-produced SCIP, deletion ghost, đổi branch, dữ liệu lớn và concurrent writers. Ấn định latency/memory/response-size budget trước khi đo; chưa có bằng chứng để tự đặt số SLA production.

Điều kiện nghiệm thu đề xuất: 3 P1 hết tái hiện; toàn bộ JSON error probe đạt; không wrong-identity trên corpus tĩnh; dynamic không chứng minh được phải abstain; omitted do budget luôn đồng bộ completeness; core/receipt floors tiếp tục đạt; các skip quan trọng được đóng trên CI phù hợp. Đây là đề xuất tiêu chí, chưa phải chứng nhận repo đã đạt.

## Tái hiện và bảo toàn bằng chứng

Giải nén evidence.zip vào một thư mục tạm mới. Đứng tại repo rồi chạy `.venv/bin/python <thu_muc_giai_nen>/functional_probes.py` và tiếp theo `.venv/bin/python <thu_muc_giai_nen>/mcp_stdio_probes.py`. Có thể đặt `SOT_AUDIT_SOURCE` tới source khác. Script tạo fixture trong thư mục giải nén; không chạy trên project thật. Probes giữ tiêu chí audit ban đầu nên một số FAIL là lỗi contract đã ghi, hai case STOPPED/empty-map có giải thích phân loại.

Các lệnh regression và benchmark đã chạy:

```bash
.venv/bin/python -m pytest tests/ -q -ra -o addopts='' --cov=sot_graph --cov-branch --cov-report=json --junitxml=pytest.xml
.venv/bin/python -m pytest evaluation/tests/ -q -ra -o addopts=''
SOT_EXTRACTOR=builtin .venv/bin/python scripts/sot_evaluator.py --gate --output <tmp>/oracle.json
SOT_EXTRACTOR=builtin .venv/bin/python scripts/bench_search_quality.py --gate --json <tmp>/search-quality.json
SOT_EXTRACTOR=builtin .venv/bin/python scripts/bench_diff_impact.py --gate --json <tmp>/diff-impact-oracle.json
SOT_ENGINE_BOOTSTRAP=off .venv/bin/python scripts/e2e_real_cbm.py
uv build --out-dir <tmp>/dist
```

evidence.zip lưu raw stdout/stderr, XML, coverage, oracle, inventory source, summary JSON, scripts và fixtures JSON tối thiểu. Fixture paths trong raw log là đường dẫn máy chạy; một số temp repository của E2E được script dọn. Không bao gồm engine database hoặc source private submodule. Kiểm tra manifest SHA256 để đối chiếu file trong archive. Ghi chú audit đã được lưu bằng sotgraph insert để tái sử dụng; không áp dụng fix production.

Diff-impact cuối đã chạy với working tree và no-auto-reconcile; report chứa cả hai skill file thay đổi trước audit và artifact tài liệu mới. Receipt là STALE nên không dùng nó làm chứng nhận an toàn code. Summary JSON standalone khớp *.json trong gitignore; bản JSON cũng nằm trong evidence.zip để giữ báo cáo portable khi commit tài liệu.
