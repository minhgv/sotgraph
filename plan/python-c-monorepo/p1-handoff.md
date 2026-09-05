# P1 Handoff — Contract chuẩn hóa + CLI/MCP parity (2026-09-05)

File này tự đủ (self-contained): baseline, scope, bằng chứng, lệnh + exit code thật, blocker, quyết định mở, điều kiện resume. Không cần đọc lại hội thoại. `p0-handoff.md` giữ nguyên như lịch sử bất kỳ; `status.md` là bảng trạng thái sống.

## 1. Baseline & scope

- Branch `feat/python-c-monorepo-phased` @ `01518f2` (chain trên branch: `a506f01` fix(provider) constrain public remediation → `fc1ec4d` feat(contract) exact artifact operation compatibility → `0f0539e` docs(native) signed release verification → `01518f2` feat(provider) gate strict dispatch on measured artifact evidence). Ngày làm gói này: 2026-09-05.
- Gói này CHỈ sở hữu: `tests/test_cbm_contract_parity.py` (MỚI), `plan/python-c-monorepo/p1-handoff.md` (MỚI), `status.md`, `execution-plan.md`.
- **Production: 0 file thay đổi. Không commit nào được tạo bởi agent này** (main sở hữu commit; working tree để lại nguyên trạng cho main review/commit).
- Không đụng golden fixtures (`tests/fixtures/cbm_golden` — canonical, unchanged), không chạy native binary, không đụng daemon/config toàn cục, không schema change (không ghi DB mới ngoài test scratch tmp; envelope legacy giữ nguyên mặc định).

## 2. Vấn đề gốc & thiết kế

Yêu cầu gốc của P1 gate: gate KHÔNG phải chỉ unit registry (exact-compat registry) — cần parity deterministic giữa SOT CLI và MCP: cùng interpretation cho failure/version/builtin_only policy, tại public entry boundary có sẵn, với **fake runner, KHÔNG native thật**.

`tests/test_cbm_contract_parity.py` (203 dòng; vượt ngân sách hướng dẫn 3 dòng để giữ inventory và kiểm thử portability):

- **2 surface so đối chiếu (2 API khác nhau, không phải assert cùng dict 2 lần):**
  - CLI: `sot_graph.assurance.federation_plan` / `federated_extras` (`src/sot_graph/assurance/orchestrator.py:35,600`) — orchestrator mọi lệnh federation của `cli.py:475,577,1697` đi qua.
  - MCP: `McpService.usages(provider_policy=…)` (`src/sot_graph/mcp_service.py:967..` với `_require_satisfiable_policy`/`_honest_policy_meta` tại `mcp_service.py:101,116`, gọi tại `:727,:984`).
- **3 policy parity:**
  1. **builtin_only**: spec `builtin` + MCP `builtin_only` → provider None, 0 spawn đo trên marker file; MCP meta `builtin_only=True`, note None.
  2. **failure**: `require:codebase-memory` với command trỏ file không tồn tại → CLI `fail_message` kết thúc "failing closed", `candidates=[]`, `providers_extra=[]`; MCP `require_external` → raise `McpServiceError` code `policy_unsatisfiable`. Không surface nào trả builtin evidence im lặng như thể provider đã được phục vụ.
  3. **version**: fake runner healthy → probe báo version pin `0.10.8`, đúng **1** spawn (đo, không suy diễn); fake runner version unparseable → `healthy=False`, `version=None`, degrade bằng warning explicit "unavailable (unhealthy: unparseable version…", provider KHÔNG được dùng; MCP `prefer_external` vẫn serve builtin với note honest "builtin served…".
- **Fake runner:** reuse `make_exe`/`spawns`/`VERSION` từ `tests/test_cbm_exact_compatibility.py` (script shebang python, ghi "spawn" vào marker file mỗi lần bị thực thi) — claim "no spawn" được ĐO, không giả định. Broken-version exe là helper 8 dòng nội bộ. Fixture `repo` (git repo + reconcile) reuse từ `tests/test_p2_orchestrator.py` — không nhân bản integration lớn. Config qua `<repo>/.sot/config.toml` (`allow_external` + `[providers.codebase-memory] command=[fake]`) — đúng layer `load_config` mà CLI dùng; env `SOT_PROVIDERS_*` được delenv để deterministic.

## 3. Bằng chứng — lệnh đã chạy + exit code thật (phiên này, tái lập được)

- `.venv/bin/pytest tests/test_cbm_contract_parity.py -p no:cacheprovider -q` → **5 passed, 1.42s, exit 0**.
- `.venv/bin/pytest tests/test_p2_orchestrator.py -p no:cacheprovider -q` → **32 passed, 1.65s, exit 0**.
- Full suite liên quan (12 file: `test_provider_contract.py test_provider_compatibility.py test_cbm_exact_compatibility.py test_cbm_adapter.py test_cbm_golden.py test_cbm_normalization.py test_cbm_verification.py test_cbm_snapshot_p2.py test_p2_orchestrator.py test_cli_provider_wiring.py test_adapters.py test_cbm_contract_parity.py -p no:cacheprovider -q`) → **297 passed, exit 0**, chạy 2 lần: 36.24s và 25.79s (deterministic pass; external timeout 180s không bị chạm). Log raw session-local ở `/tmp/p1-suite-run.log` (không bền) — số liệu trên là receipt; tái lập bằng lệnh nguyên văn trên.
- Fixture suite digest (thuật toán manifest P0: sha256 trên dòng `relpath\0sha256\n` sorted, walk sorted, qua `tests/fixtures/cbm_golden`) = `bd65c856ce16af5004109cd941c334a95446eff02d9dce6a98f5fd7eb0c40a64`, 8 file = 7 tool fixture + `_meta.json`. **Digest + danh sách file embed làm hằng số trong test** (`TestGoldenFixtureSuiteInventory`) — KHÔNG phụ thuộc `evidence/golden-fixture-manifest.json` (manifest lịch sử đó là untracked receipt, không có trên clean checkout; giá trị đã khớp, verify 2 lần phiên này). Golden không bị đổi.

## 4. Reviewer verdict & lịch sử sửa

- Vòng review trước: reviewer độc lập bắt **deadlock** trong attempt của author trước; claim "**40 passed**" của author đó đã bị **withdrawn** — handoff này KHÔNG thừa kế số đó; các con số ở mục 3 là run đo thật phiên này. Số "51 passed / 0.15s" và "160 passed / 15.78s" do main đo: **các run đo hợp lệ, riêng biệt, scope khác nhau trong cùng session — được tin nhận/confirmed (main claims trusted)**; bộ 12 file của gói này đo thêm 297 (không thay thế, chỉ bổ sung scope).
- **Round 1 (self-fix, chỉ test mới):** run đầu 4/5 — literal `\0`/`\n` control-char vs escaped-backslash trong chuỗi `algorithm`; sửa assert → 5/5. Không đụng production.
- **Round 2 — reviewer xác nhận 4 bug, đã fix tất cả (chỉ test mới + docs sở hữu):**
  1. *Test phụ thuộc manifest trong plan/ (untracked, không có trên clean checkout).* **Fix:** embed hằng số `EXPECTED_SUITE_DIGEST` + `EXPECTED_FILES` (7 tool + meta) + `EXPECTED_ALGORITHM` ngay trong test; test không đọc file nào ngoài golden suite. Manifest JSON lịch sử = untracked receipt, không phải dependency canonical.
  2. *Windows skip phải bọc đúng class fake-subprocess, không bọc pure digest.* **Fix:** marker `_fake_exec` (skipif `os.name == "nt"`) chỉ trên `TestBuiltinOnlyPolicy` + `TestVersionPolicyParity` (dùng shebang launcher); `TestFailurePolicyParity` (không fake exe) và `TestGoldenFixtureSuiteInventory` (pure digest) chạy mọi platform.
  3. *Gắn nhãn sai cho số đo của main (51/160).* **Fix:** xem bullet đầu mục này — separate valid measured runs, trusted/confirmed.
  4. *Wording "8 tool payload" sai.* **Fix:** "8 file = 7 tool fixture + `_meta.json`" (status.md + file này).
- Sau round 2: `.venv/bin/pytest tests/test_cbm_contract_parity.py -p no:cacheprovider -q` → **5 passed, 1.56s, exit 0** (receipt của agent sau round 2; 203 dòng test). Các findings được sửa trước khi main tích hợp.

## 5. G1 verdict (scope có biên) — PASS

Bộ fixture/contract liên quan đạt 297 tests, exit 0. Gói parity không sửa production; toàn phase P1 có thay đổi production ở các commit mục 1: thêm metadata exact-compatibility và thay thông báo lỗi/remediation công khai bằng nội dung SOT-only. Không tuyên bố output byte-identical; envelope/schema legacy giữ mặc định khi các trường mới không được cung cấp. No silent fallback được kiểm tra bằng fail-closed, explicit degrade và đo no-spawn. **Ngoại lệ explicit — không pretend hoàn tất:**

1. Automated canonical importer (tự đồng bộ registry từ golden suite) = **P2**, không phải yêu cầu G1; G1 dùng digest tính trong test bằng đúng thuật toán manifest P0, registry per-operation user/test-supplied là đủ.
2. Strict context **programmatic-only**: chưa có public CLI cho managed default (P2); parity test đi Python entry.
3. Parity ở mức policy/interpretation (fail-closed, version explicit, no-spawn) — KHÔNG phải byte-parity output native thật trên binary 0.10.8.
4. Command/pinning **TOCTOU** (đổi binary giữa verify và spawn) = P2.
5. Kế thừa từ G0, không thuộc P1: G0-B3 git binding UNVERIFIABLE trên 0.10.8 (vẫn mở); 11/15 native tool UNKNOWN; daemon latency chưa đo — chuyển G2/P3.
6. Packaging/platform/budget = P4 (legal/build budgets vẫn pending; signature đã verify scope hẹp 2/49 assets — `evidence/release-signature-verification.md` @ `0f0539e`).

## 6. Điều kiện resume (sang P2)

- Bắt đầu từ bằng chứng G1 trên disk (status.md + file này + test chạy được); không promote theo tên.
- P2 cần: managed lifecycle (runtime helper, không viết process manager song song `proc.py`), profile namespace, disable background writes/artifact theo capability đã kiểm chứng, cancel/timeout/quarantine, native-job-survives-client-death test trên scratch. Owner phân cấp theo `execution-plan.md` mục 10.
- Không đổi `p0-handoff.md`; status.md cập nhật tiếp; mỗi owner một file, không đụng chéo.
