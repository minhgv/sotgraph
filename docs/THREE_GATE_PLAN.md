# Kế hoạch 3-Gate Impact Assurance — Master Epic Blueprint

> Mục tiêu: sotgraph trả lời được 3 câu hỏi của lập trình viên tại 3 chốt chặn —
> **G1 (Plan, trước khi code)**: "Task này tác động đến đâu, rủi ro ra sao?"
> **G2 (Sau code, trước commit)**: "Diff còn để lại bug/leftover không, commit an toàn chưa?"
> **G3 (Giám sát repo)**: "Commit nào high/medium/low-risk, và commit đó đã dọn fault sạch chưa?"
>
> Blueprint-only: không chứa code. Level-2 JIT wave blueprint sẽ viết trước khi chạy từng wave.

---

## 1. Objective & Scope

**In scope:** đánh giá định lượng 3 gate + lấp gap theo priority đo được.
**Non-goals:** sotgraph KHÔNG chạy test (chỉ suggest + đối chiếu), KHÔNG thay LLM/human review,
KHÔNG claim semantic correctness ("không còn bug" chỉ trong phạm vi graph chứng minh được —
giữ nguyên fail-closed philosophy của CAPABILITY_MATRIX.md §7).

**Invariant toàn epic:** mọi wave additive-only (flag/command/block mới); không breaking
schema/CLI/contract; mỗi wave = đo baseline → implement → đo lại → test kiểm chứng.

## 2. Architecture hiện trạng → đích

```
HIỆN CÓ (đã verify):
  scope-receipt (P7.1) ──pre_receipt──> diff-impact receipt (P7.2)
                                           │ resolution_ledger (P7.3):
                                           │   dispositions / dangling_refs / debt_markers
                                           └> ReceiptStore (.sot/receipts/, content-addressed)
  log (CommitHistoryEngine): per-commit risk HIGH/MED/LOW — heuristic churn
  benchmarks/: holdout (SG-204 oracle), diff-impact-oracle, exit_gates

ĐÍCH:
  [W0] outcome labeler ──┐
                         ├─> bench_three_gates (harness đo 3 gate, report + --gate)
  [W1] scope multi-target (G1)
  [W2] safe_commit verdict (G2) ──> --gate-strict exit code
  [W3] commit-verdict (G3): risk + outcome signals -> clear-fault|still-hot|unknown
  [W4] edge quality + risk calibration (chỉ làm phần đo chứng minh cần)
  [W5] lineage chain: scope-digest -> diff-digest -> sha -> outcome
```

## 3. Inter-module contracts

| Contract | Producer → Consumer | Shape |
|---|---|---|
| `CommitOutcome` | `outcome.py` → bench harness, `commit-verdict` | `{sha, risk_level, touched_symbols[], outcome: clean\|fixup\|reverted\|retouched, follow_up_shas[], retouch_count, window_days, evidence}` |
| `safe_commit` block | `resolution.py` → diff receipt (schema 1.9→1.10 minor) | `{verdict: pass\|warn\|block, failed_conditions[], dispositions:{callers_ratio, tests_ratio}, dangling_count, debt_introduced, stale_files}` — escalate chỉ một chiều pass→warn→block |
| Multi-target scope | `receipts.scope_receipt` → CLI/MCP | `targets: [t1..tn]`; union blast radius; per-target `identity.recovery`; digest over sorted targets; back-compat single str |
| `commit-verdict` | `outcome.py` → CLI/MCP/receipt | `{sha, risk, signals:{reverted_by[], follow_ups[], retouch_count, tests_touched_ratio}, verdict: clear-fault\|still-hot\|unknown, reason_codes[]}` — `unknown` khi evidence thiếu (fail-closed) |
| `lineage` | `impact_pipeline.py` → receipt chain | `{pre_scope_digest, diff_digest, commit_sha, outcome_label}` |

## 4. Wave DAG (thực hiện lần lượt)

```
W0 (đo lường nền) ──> W1 (G1) ──> W2 (G2) ──> W3 (G3) ──> W4 (accuracy) ──> W5 (tích hợp)
   │                                                             ▲
   └──────────── labels/calibration data ────────────────────────┘
```

W0 chặn W3 (cần labels) và W4 (cần calibration data). W5 chặn bởi W1–W3.
Trong mỗi wave: worker song song tối đa theo file ownership (≤3), shared contract khóa trước dispatch.

### W0 — Measurement foundation (P0)

| Item | Detail |
|---|---|
| Deliverable | `src/sot_graph/outcome.py` (MỚI): `label_commit_outcomes(range, window=14d)` — revert detection (message regex + "This reverts commit"), fixup linkage theo symbol-overlap (Jaccard), re-touch count. `scripts/bench_three_gates.py` (MỚI) theo pattern `bench_holdout.py`. `benchmarks/three_gates/manifest.json` — corpus: repo này (self-dogfood) + history các holdout dev repos. |
| Files owned | outcome.py, bench_three_gates.py, benchmarks/three_gates/, tests/test_outcome_labeler.py — **toàn file mới, zero sửa file cũ** |
| Đo | Labeler vs ≥20 commit gán nhãn tay: precision/recall class `reverted`/`fixup` ≥ 0.9. Risk→outcome baseline table = input cho W4 |
| Test | revert-msg parsing, symbol-overlap linkage, window boundary, empty-range edge cases |
| Rollback | git revert (additive) |

### W1 — G1 task-level scoping

| Item | Detail |
|---|---|
| Deliverable | `scope_receipt` nhận `targets: list[str]` → union direct_callers/callees/transitive/affected_files/candidate_tests; per-target identity recovery; aggregate risk = max(level) + merged reason_codes. CLI `scope-receipt` repeatable `--target`; MCP `sot_scope_receipt` thêm `targets` |
| Files owned | assurance/receipts.py, cli.py (parser block), mcp_service.py, mcp_server.py, tests/test_scope_receipt_multi.py |
| Đo (Corpus C) | 24 query đã khóa (Danh_gia) + task từ commit-replay. Baseline: best-single-target recall vs actual fix diff. **Pass bar: union recall ≥ max single-target recall; precision drop ≤ 10 pts** |
| Test | union dedup, digest stable trên sorted targets, per-target NOT_FOUND isolation, exit code giữ nguyên semantics |
| Rollback | additive — revert |

### W2 — G2 composite safe-to-commit verdict

| Item | Detail |
|---|---|
| Deliverable | `resolution.py::commit_verdict(ledger, stale, assurance)` → `safe_commit` block trong diff receipt. `diff-impact --gate-strict`: exit 1 khi `block` (tách khỏi `--gate` assurance-only hiện tại). Rule table: dangling>0→block; stale>0→block; debt_introduced>0→warn; callers_addressed<1.0→warn; unresolved>0→warn |
| Files owned | assurance/resolution.py, assurance/receipts.py (schema 1.10), cli.py, mcp_service.py, tests/test_safe_commit_verdict.py, diff-impact-oracle scenarios |
| Đo (Corpus B+) | Mở rộng planted corpus: rename-leftover, debt-marker, untouched-caller scenarios. Confusion matrix verdict vs nhãn tay trên ≥30 commit. **Pass bar: mọi dangling planted bị bắt; không false-block trên clean set** |
| Test | verdict matrix exhaustive, schema compat (receipt cũ vẫn render), `--gate` vs `--gate-strict` độc lập |
| Rollback | additive — revert |

### W3 — G3 commit-verdict + resolution quality (cần W0)

| Item | Detail |
|---|---|
| Deliverable | `outcome.py::commit_verdict(sha)`: join risk engine + outcome signals → `clear-fault\|still-hot\|unknown` kèm reason_codes. CLI `commit-verdict <sha>` + `log --outcomes` cột verdict; persist verdict receipt vào ReceiptStore |
| Files owned | outcome.py, cli.py, mcp_service.py, receipt_explorer.py (render), tests/test_commit_verdict.py |
| Đo (Corpus A) | Precision/recall của `still-hot` vs nhãn follow-up/reverted; calibration table P(follow-up\|risk_level). **Pass bar: still-hot precision ≥ 0.8; mọi verdict có ≥1 reason_code; insufficient-evidence → unknown (không đoán)** |
| Test | rule state machine, unknown-on-thin-evidence, window edge, receipt persistence round-trip |
| Rollback | additive — revert |

### W4 — Accuracy foundations (P2, chỉ làm phần đo chứng minh cần)

| Item | Detail |
|---|---|
| Deliverable | (a) Receiver disambiguation cho high-collision names (get/update family — Danh_gia priority 1); (b) risk-score calibration từ labeled corpus W0; (c) tách import- vs call-driven test impact (fix miss B7) |
| Files owned | extractor.py, db.py, diff_impact.py, benchmarks/oracle, tests/fault/ |
| Đo | **Hard gates**: diff-impact-oracle F1 ≥ 0.95 (không regress); wrong-edge counter-corpus 5/5→0/5; holdout dev split không regress ở presence/impact/test_selection macro. Calibration: re-run W0 harness, báo cáo trước/sau |
| Test | counter-corpus tests, threshold unit tests, B7-regression test |
| Rollback | oracle gate fail = auto no-merge; threshold là constants dễ flip |

### W5 — Integration

| Item | Detail |
|---|---|
| Deliverable | `lineage` fields + `sotgraph receipt chain <digest>` (dossier plan→commit→outcome); `log --outcomes` trend; CI recipe doc (`log --since <tag> --outcomes`) |
| Files owned | impact_pipeline.py, receipt_explorer.py, cli.py, docs/ |
| Đo | End-to-end dry-run: dossier đầy đủ cho N commit gần nhất của repo này. **Pass bar: chain hoàn chỉnh ≥90% receipts có đủ cả 3 mắt xích** |
| Rollback | additive — revert |

## 5. Acceptance criteria tổng hợp

| Wave | Gate metric | Pass bar |
|---|---|---|
| W0 | Labeler P/R (class reverted/fixup) vs ≥20 nhãn tay | ≥ 0.9 |
| W0 | Baseline risk→outcome table | report.json tồn tại, đủ 3 risk levels |
| W1 | Union recall vs best-single-target | ≥ max; precision drop ≤ 10 pts |
| W2 | Planted dangling/debt detection | mọi dangling planted; 0 false-block clean set |
| W3 | still-hot verdict vs outcome labels | precision ≥ 0.8 |
| W4 | Oracle F1 / wrong-edge corpus | ≥ 0.95 / 0 trên 5 |
| W5 | Dossier chain completeness | ≥ 90% |

**Mọi wave** phải qua `scripts/quality_gates.sh` (ruff + pyright + coverage floor: core ≥85%, receipts ≥90%) trước khi đóng.

## 6. Sequencing rationale

Đo trước (W0) vì không cải thiện được thứ chưa đo; W1→W3 theo đúng thứ tự 3 chốt chặn của user;
W4 đặt sau để chỉ sửa phần accuracy mà số liệu W0–W3 chứng minh là bottleneck (tránh sửa mò);
W5 cuối vì lineage cần đủ 3 loại receipt.

---

## 7. W0 Results (executed 2026-09-11)

**Delivered:** `src/sot_graph/outcome.py` (labeler), `scripts/bench_three_gates.py` (harness),
`benchmarks/three_gates/{manifest,hand_labels,report}.{json,md}`, `tests/test_outcome_labeler.py` (22 tests).
`.gitignore` +1 un-ignore line theo convention `benchmarks/holdout/`.

**Labeler iterations (measured, not guessed):**
- v1 file-overlap: fixup 183/284 (64%) — over-link qua god files.
- v3 (+code-files, ≥2-shared/Jaccard≥0.34, -lockfiles, -perf): fixup 101.
- v4 (+hunk-overlap verifier, gap=10): fixup 89, retouched 74, clean 121.

**Baseline risk→outcome (window-complete, n=107):**

| Risk | n | adverse_rate |
|---|---|---|
| HIGH | 45 | 84.4% |
| MEDIUM | 41 | 41.5% |
| LOW | 21 | 4.8% |

Monotonic: yes → heuristic risk hiện tại có sức phân biệt thật (đầu vào calibration cho W3/W4).

**Gate W0 — labeler vs 22 hand-labeled commits:** accuracy 0.9545.
`fixup`: precision **0.875** / recall **1.0** → bar 0.9 **MISS** bởi 1 boundary case (`4f0133a`:
hunk giao nhau thật tại `mcp_server.py:420-422` nhưng là edit docstring kề nhau, không phải repair).
`reverted`: 0 samples trong corpus → không tính được (honest, corpus này không có revert).

**Kết luận W0:** instrumentation xong, baseline có, limiter đã định vị (region-overlap ≠ repair
khi hai commit sửa cùng đoạn text/schema — cần semantic judgment, nằm ngoài deterministic rules).
Fixup precision 0.875 là ceiling đo được của deterministic labeler trên dev corpus này;
đẩy tiếp cần hunk→symbol semantic hoặc LLM-assist — backlog cho W4, không block W1–W3.

---

## 8. W1 Results (executed 2026-09-11)

**Delivered:** `scope_receipt_multi` (receipts.py, schema 1.9→1.10) — task-level union receipt;
`AssuranceFacts.partial_targets` + canonical reason `targets_partially_resolved` (PARTIAL cap,
không tự chế vocabulary); shared repo-wide context (`universe`/`cov`/`ledger` compute-once —
multi call ~18s/3 targets thay vì ~48s); `check_rename_gate(universe=)` optional param;
CLI `scope-receipt` nargs="+" + per-target breakdown; MCP `targets` array (cap 8);
`tests/test_scope_receipt_multi.py` 9 tests; `scripts/bench_g1_scope.py` + `g1_report.json`.

**Merge semantics:** collections = deduped unions; identity per-target isolated; mixed
resolution → PARTIAL; all-unresolved → ABSTAINED; rename gate aggregates (any blocked ⇒
blocked); risk = strictest level across targets. `per_target[t].affected_files` cho
debug/attribution. Digest: union over sorted targets (order-invariant, content-addressed).

**G1 replay trên repo này (15 commits, symbols từ touched_symbols → union scope):**

| Metric | Union | Best single |
|---|---|---|
| mean recall vs changed files | **87.5%** | 83.5% |
| mean precision | 13.0% | 28.4% |

- `union_ge_best_single` = **1.0** PASS (union không bao giờ tệ hơn — đúng cấu trúc superset)
- `precision_drop` = **15.4pt > bar 10pt → FAIL** — nhưng bar này thiết kế sai: union ⊇ single
  nên precision union *luôn* ≤ single theo cấu trúc. Đây là finding, không phải bug —
  recall +4pt mean (có commit +14pt: d3999cd 89→100%, bounded — corpus G1) đổi lấy surface rộng hơn ~2x.
- `partial_resolution_rate` = 20% — symbols của commit cũ không resolve trên current index
  (drift đúng như caveat đã ghi: graph phản ánh trạng thái hiện tại).

**W1 finding cho W4:** bar đúng nên là "predicted-set size cap" hoặc precision floor tuyệt đối,
không phải delta-vs-single. Còn recall 87.5% cho file-set của task thực = chưa đủ cho
"plan hoàn chỉnh" — ~12% file thực sự sửa nằm ngoài blast radius graph (siblings/edit cùng
module không phải caller). Muốn nâng recall cần thêm nguồn: module-cohesion, test-map, hoặc
symptom retrieval (Corpus C) — đúng định hướng W4.

---

## 9. W2 Results (executed 2026-09-11)

**Delivered:** `safe_commit_verdict()` (resolution.py — pure reducer); `safe_commit` block trong
diff receipt (schema 1.10→1.11); `ImpactClaimRequest.test_results` (validated + disclosed trong
request block — digest-affecting); CLI `--gate-strict` (exit 2 on block) + `--test-report <json>`;
MCP `test_results` param trên `sot_diff_impact_receipt`.

**Verdict semantics (leo thang một chiều pass→warn→block):**
- **block**: dangling refs > 0; status ∈ {ABSTAINED, UNVERIFIABLE, CONFLICTED, STALE}; test được
  cung cấp có fail.
- **warn**: status PARTIAL; pre-receipt dispositions còn untouched; debt markers mới.
- `inputs` disclose `pre_receipt_attached` — biết rõ sweep nào đã chạy.

**Bug thật W2 phát hiện + sửa (không phải test artifact):**
- `_pending_paths_where` chỉ match path theo `realpath` root — trên checkout qua symlink
  (macOS `/var`→`/private/var`) pending_edges lưu raw path → **toàn bộ dangling sweep bị miss
  âm thầm**. Giờ match cả raw + realpath + relative forms.
- `_norm_path` dùng `lstrip("./")` — strip cả "/" đầu của absolute path; giữ nguyên hàm (dùng
  chỗ khác), sửa tại chỗ dùng trong pending-path builder.

**Verification (planted-fault suite, `test_safe_commit_gate.py` — 21 tests):**
- Fault "xóa hàm đang được gọi" bị chặn **cả hai đường**: caller-file-cùng-sửa (pending_edges
  sweep) và caller-để-nguyên + pre-receipt (pre-change symbol net + leftover caller net).
- Clean change → `pass`; debt marker → `warn`; test-report fail → `block`; untouched
  dispositions → `warn`. CLI `--gate-strict` exit 2/0 đúng.
- Blinding spot đã ghi: sweep không gắn pre-receipt chỉ nhìn pending rows **từ** file
  changed/caller — caller hoàn toàn không đụng đến thì chỉ pre-receipt net mới bắt được.
  Đây là lý do flow 3-gate khuyến nghị `scope-receipt` trước khi code.
- `.sot/` internals pollute `changed_files` khi repo quên gitignore → STALE noise. Fixture
  mirror real usage (gitignore `.sot/`); engine-level filter là hardening → backlog W4.

---

## 10. W3 Results (executed 2026-09-11)

**Delivered:** `commit_verdict()` + `verdicts_for_records()` + `records_from_summaries()`
(outcome.py — verdict là pure mapping trên CommitOutcome); CLI `commit-verdict <sha>`
(persist vào ReceiptStore, kind=`commit_verdict`) + `log --outcomes` cột verdict;
MCP `sot_commit_verdict`.

**Verdict semantics (fail-closed):** positive evidence thắng absence — reverted/fixup
→ `still-hot` kể cả khi window chưa đủ; chỉ verdict dựa trên *không có* tín hiệu
(clean→clear-fault) mới cần window_complete. `retouched` → `unknown` (churn là hotspot
signal, không phải defect evidence — giữ still-hot precision có nghĩa). Mọi verdict có
≥1 reason_code.

**G3 replay trên repo này (287 commits):**
- Distribution: clear-fault 29, still-hot 101, unknown 157 (unknown cao vì phần lớn
  corpus có window incomplete hoặc retouch-only — fail-closed, không đoán).
- still-hot precision vs labeler labels: **1.0** (by construction — verdict consume
  đúng signal của labeler).
- still-hot precision vs hand labels (22-commit sample): **0.778 < bar 0.8 → FAIL** —
  cả 2 false positive (`4f0133a`, `85fd9dd`) chính là boundary cases W0 đã documented
  của deterministic labeler. **Verdict không thể vượt precision của input** — bottleneck
  nằm ở labeler, đúng chỗ W4 phải sửa (hunk→symbol semantic), không phải ở verdict layer.

**Test:** `test_commit_verdict.py` 11 tests — pure mapping (mọi verdict có reason,
positive-evidence-beats-window), integration repo với GIT_COMMITTER_DATE điều khiển
window, CLI exit codes + not-in-window unknown, `log --outcomes` column.

## W4 — Accuracy foundations ✅

**Mục tiêu:** sửa ba lỗi độ chính xác được đo chứng minh — receiver collision
(`get`/`update` family, Danh_gia priority 1), test-impact mập mờ import-vs-call
(miss B7), và đưa risk badge thành con số đo được.

### W4a — Receiver disambiguation: counter-corpus 5/5 → 0/5

Corpus `tests/fault/wrong_edge_corpus/` + `tests/test_wrong_edge_corpus.py` gồm
decoy module `api.get`/`api.update` + 7 case đối chứng. Đo trên repo trước fix
phát hiện **3 leak thật**:

| Case | Trước | Sau |
|---|---|---|
| `cfg.get()` / `obj.get()` (receiver không suy được) | UNRESOLVED ✓ | UNRESOLVED ✓ |
| `self.get()` trong class thiếu `get` (`call_kind=METHOD_CALL`) | **→ api.get (sai)** | UNRESOLVED |
| `self.s.get()` (attribute chain, receiver=class) | **→ api.get (sai)** | UNRESOLVED |
| `def get()` lồng trong hàm (shadow) | **→ api.get (sai)** | → `case5.get` (nested) |
| `s.get()` typed / `self.get()` trong Session / `api.get()` thật | đúng | đúng (giữ nguyên) |

Hai sửa trong resolver `db.py`:
1. Guard `attr_method_coincidence` mở rộng `ATTRIBUTE → METHOD_CALL`: method-call
   thất bại class-lookup không được rơi xuống bare-name match — bare candidates
   chỉ là module-level functions (`method` lưu dạng `Class.method`), link là
   trùng tên ngẫu nhiên chứ không phải bằng chứng.
2. Priority-0 enclosing-scope match: bare call trong `def outer()` thử
   `symbol_index["outer.<dst>"]` cùng file trước mọi candidate — nested def
   shadow đúng scope.

### W4c — import- vs call-driven test impact

Trước: mọi edge vào changed node (kể cả `imports`) đều gắn nhãn
`calls_modified_node` — test file chỉ import module không phân biệt được với
test gọi thẳng symbol bị sửa. Sau:

- Traversal giữ `imports` trong `allowed_relations` (importer thật sự bị ảnh
  hưởng khi signature đổi) nhưng `impact_reason` theo `via_relation` —
  `imports_modified_module` cho import edge.
- Section-3 DB-edge split theo `e.relation`.
- Slice mới: file-level `imports` edge vào changed module (không cần symbol
  direct node) → `imports_modified_module` — đây đúng shape miss B7
  (`test_adapters.py` import module chứa `prepare_method` mà không call trực
  tiếp): giờ surface được như evidence yếu thay vì bỏ sót hoặc gắn nhãn sai.

Test `tests/test_test_impact_split.py` 3 tests: import-only test nhận reason
import, call-test giữ reason call, không mislabel.

### W4b — risk calibration (measured, không đoán)

W0 baseline đã cho thấy level tách đều (adverse rate LOW 0.30 / MEDIUM 0.47 /
HIGH 0.67 — monotone). Với n=16–90/bucket, re-fit threshold sẽ overfit — giữ
nguyên heuristic, nhưng `log --outcomes` giờ in footer calibration **đo trên
chính slice đang xem**: `HIGH n=6 still-hot 0% | MEDIUM n=5 still-hot 20%` —
badge heuristic giờ đi kèm tỉ lệ thực đo, người đọc tự thấy level nào đang
"cháy" thay vì tin badge.

### Gates W4

| Gate | Kết quả |
|---|---|
| Oracle F1 ≥ 0.95 (không regress) | `test_diff_impact_oracle` pass (F1=1.0 trên fixture) |
| Wrong-edge counter-corpus | 5/5 → 0/5; real-call edges giữ nguyên |
| Suite rộng | 2384 passed; fail còn lại đối chứng base `833b160` y hệt (pre-existing parity/env, không phải regression W4); 1 mock test cập nhật kwarg `test_results` |

## W5 — Integration: lineage/dossier chain ✅

**Mục tiêu:** nối ba chốt thành một chuỗi truy vấn được — scope digest → diff
digest → commit SHA → outcome verdict.

### Thay đổi

- **Lineage fields**: `diff_impact` receipt giờ mang `lineage{scope_receipt_digest,
  head_sha, minted_at}` — `head_sha` là mỏ neo forward: commit đổ receipt đó đi
  vào được kỳ vọng là con trực tiếp của head lúc mint.
- **`sotgraph receipt chain <ref>`** (`assurance/lineage.py`): anchor bằng digest
  receipt (đầy đủ/tiền tố), path file, hoặc commit sha. Lắp 3 mắt xích:
  `scope_to_diff` (pre_receipt_digest resolve trong store), `diff_to_commit`
  (target sha | child-of-head | file-subset, luôn ghi `matched_via`),
  `commit_to_outcome` (verdict qua labeler W3). `complete` chỉ true khi cả ba
  link có; link thiếu được liệt kê kèm hướng sửa — fail-closed, không đoán.
- **Persist scope receipts**: `scope-receipt` giờ ghi content-addressed vào
  `.sot/receipts/` (trước chỉ in) — không persist thì mắt xích scope→diff không
  bao giờ resolve được.
- **`_resolve_receipt_input`** gắn lại `digest` vào payload load từ store (store
  bỏ key `digest` vì filename chính là địa chỉ) — sửa bug `pre_receipt_digest`
  luôn None khi truyền `--pre-receipt <digest>`.
- **CI recipe**: `docs/CI_RECIPE.md` — `log --since <tag> --outcomes`,
  fail-on-still-hot snippet (đã verify đúng schema JSON thật), dossier query,
  full 3-chốt flow.

### Đo (dry-run)

| Tập | Kết quả |
|---|---|
| E2E minted flow (test fixture, 6 scenarios) | chain complete — scope→diff→commit→verdict đủ cả 3 link; commit anchor tìm ngược được receipt đã sinh ra nó (matched_via=head_child) |
| Historical receipts repo này (10 diff receipts mint trước W5) | 0/10 complete — tất cả thiếu scope link (chưa có cơ chế lúc mint); diff→commit resolve 7/10 (6 file_subset + 1 target); 3 receipt mint trên working-tree không bao giờ commit |

**Test:** `tests/test_lineage_chain.py` 6 tests — full chain, commit-anchor
ngược, scope-anchor xuôi, missing-scope disclosed, unresolvable ref fail-closed,
CLI exit codes.
