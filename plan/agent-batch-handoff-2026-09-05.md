# Agent batch handoff — 2026-09-05

> Trạng thái sau hai lô giao sub-agent (issues #8–#13 + 4 nhóm P1 accuracy).
> Working tree sạch; mọi việc đã xong nằm trong 8 commit local trên `main` (chưa push).
> Lệnh tiếp theo khi mở lại máy: **làm tiếp Nhóm 4** (spec ở cuối file).

## Đã xong và đã commit

### Lô 1 — Issues #8–#13 (phase-4 + P2)

| Commit | Issue | Nội dung |
|---|---|---|
| `1254bdc` | SG-202 | Pack completeness thành thật: `PARTIAL` ⇔ truncated, ambiguity hiện rõ (tie → error + candidates), accounting theo category, snapshot binding, anti-inference note. Lưu ý: metadata floor tăng ~100–300 token → budget rất nhỏ fail-closed `BUDGET_TOO_SMALL`. |
| `d60f8c4` | SG-201 | Repo-map filter theo category (default production-only, ẩn 3118/4165 symbol trên repo thật), cross-root isolation (kèm fix bug thật: MCP path `../..` trên macOS symlinked root), deterministic, filter scope echo + absence note. CLI `--include`, MCP `include_categories`. |
| `dc3d1b3` | SG-205 | `sot receipt show/diff` — module `receipt_explorer.py` thuần read-only (không DB/IO), version gate (1.0–1.6 best-effort, unknown refuse exit 1), diff bỏ volatile fields. |
| `6082f1b` | SG-302 | Governance baseline: CONTRIBUTING, SECURITY (email còn placeholder), CODEOWNERS (`@minhgv` — chưa confirm), dependabot (uv + github-actions), PR template. |
| `262ec79` | SG-303 | Pin 5 actions về commit SHA (đã đối chiếu độc lập 5/5 bằng `git ls-remote`; `pypa/gh-action-pypi-publish` vốn pin theo branch float — giờ freeze), uv pin `0.12.10`, least-privilege `permissions:` cho mọi workflow. SBOM/provenance: **chưa làm**, 3 phương án trong report (PyPI đã có PEP 740 attestation qua OIDC). |
| — | SG-301 | **BLOCKED**: chưa có characterization tests cho hotspot modules (db.py/cli.py/diff_impact.py/mcp_service.py). Cần issue riêng xây characterization suite (effort L) trước khi split. |

### Lô 2 — 4 nhóm P1 accuracy (advisor review 2026-09-05)

| Commit | Nhóm | Kết quả đo được |
|---|---|---|
| `66f4295` | Nhóm 1 (P1-7) | Hedged wording "all calling sites" → "indexed calling sites within reported scope" (AGENTS.md, README, SKILL.md, SOT_GRAPH_GUIDE); diagnostic `commit-unknown` phân biệt shallow-clone vs not-ancestor (vẫn fail-closed). |
| `de021da` | Nhóm 2 (P1-1, P1-2) | TYPE_CHECKING declarations vào presence universe (tag `keywords: ["type_checking"]`, không tạo runtime edges từ guard); lambda/comprehension calls attribute đúng enclosing scope theo Python evaluation order (`_iter_owned_calls`). **Impact recall 0.9609 → 0.9798**; diff-impact oracle gate vẫn 1.00. |
| `3015e28` | Nhóm 3 (P1-4, P1-5) | Registry cap/collector ID thay tripwire line-bound (`assurance/accounting.py`, fail-closed `UnaccountedSource`, AST sweep không phụ thuộc số dòng); holdout công khai denominators (impact_recall: 592 universe / 228 measured / 364 `sample_cap_25` / 27 ambiguous; jsonschema unmeasurable). Scores không đổi. |

### Verification đã chạy (tôi tự chạy, không lấy báo cáo agent)

- Full suite: **1327 → 1372 passed, 2 skipped** (tăng theo số test mới; không regression).
- `scripts/quality_gates.sh`: all passed (ruff, pyright, coverage floors, bandit, pip-audit).
- `sot claims lint`: clean qua mọi bước (10 claims, 26 absolute-phrase hits covered).
- Holdout `--gate`: ALL PASS, scores byte-identical sau nhóm 3.

## Chưa làm — thứ tự ưu tiên

### Tiếp theo: Nhóm 4 (advisor P1-6) — retrieval bare-name matching

**Vấn đề**: query bare name (`render`) không match mạnh symbol qualified (`Class.method`); Hit@1 = 0.7879 (Hit@5 0.9515, MRR 0.8548) trên holdout.

**Spec đã chốt**:
1. Sửa ở tầng **ranker/indexing** (vector.py + FTS/BM25 trong db.py), không sửa CLI/MCP adapter; CLI và MCP dùng chung một interpretation.
2. Identifier-component analysis: tách `Class.method` / snake_case / camelCase thành component; index/query **last component** (bare name) như token mạnh; exact-bare-name boost có trọng số **bounded**.
3. Chống failure mode advisor: bare name ambiguous (nhiều symbol trùng tên) ⇒ boost phải damp theo match-count, không được đẩy symbol qualified thật sự relevant xuống.
4. Đánh giá theo thứ tự: (a) regression synthetic `benchmarks/search-quality.json` — exact-mode không được tụt; (b) holdout retrieval before/after (số before như trên); (c) adversarial probes tự viết (test file mới `tests/test_search_bare_name_ranking.py`): bare→Class.method, ambiguous không bury exact qualified match, prefix vs exact, bare name đúng là function ngoài class.
5. **Claims discipline**: `benchmarks/search-quality.json` được cite trong `claims/registry.yaml` (search-exact-row, search-semantic-row...) và `docs/BENCHMARKS.md`. Nếu số đổi: regenerate artifact + update docs row + sync registry (artifact_value + commit = HEAD sha trước thay đổi) rồi `sot claims lint` phải pass.
6. Trung thực: nếu Hit@1 không cải thiện trên holdout thì báo thẳng, không tune đến khi xanh (holdout từng dùng tuning — Corpus warning của advisor).
7. Test: `tests/test_search_bare_name_ranking.py` + `tests/test_sot_graph.py tests/test_vector.py`.

(Một sub-agent đã được dispatch với spec này hôm 2026-09-05 nhưng bị hủy trước khi chạy — working tree sạch, không có thay đổi dở dang.)

### Sau Nhóm 4 (đã xác minh còn mở tại HEAD)

- **Roadmap P1-3**: STRONG four-axes interface (anchor freshness / identity / query relevance / scope completeness như 4 trục riêng; legacy STRONG chỉ compat). Chưa có `query_relevance` gì trong code.
- **Roadmap P1-1 phần còn lại**: ranking multi-signal (vẫn chỉ PageRank), bundle confidence/UNKNOWN (đỡ ZERO_VIOLATIONS), report template schema-driven; exit gates chưa đo của SG-201 (human study, contamination <2%) và SG-202 (task-sufficiency 95%).
- **SG-301**: chờ characterization tests (issue riêng, L).
- **Advisor P1-3 (mixed paths usages)**: không tái hiện trên builtin self-index (36/36 absolute); chỉ audit khi có corpus provider ngoài.
- **SBOM/provenance (SG-303 phần còn lại)**: 3 phương án, cần maintainer chọn.
- **Xác nhận maintainer (nhỏ)**: username CODEOWNERS, email SECURITY.md, dependabot uv vs pip.

## Cách resume

1. Mở lại session, đọc file này.
2. Ra lệnh: "làm tiếp Nhóm 4 theo handoff" — spec đầy đủ ở trên, quy trình: sub-agent thực hiện → main agent review độc lập (diff + tự chạy test + claims lint) → commit conventional kèm `(advisor P1-6)`.
3. Chưa push bất cứ gì; 8 commit local trên `main` chờ review của bạn trước khi push.
