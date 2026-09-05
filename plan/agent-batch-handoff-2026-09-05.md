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

## Nhóm 4 (advisor P1-6) — ĐÃ XONG, commit `c745b47`

Root cause thật: tokenizer FTS dùng `tokenchars '_-.:$@'` khiến `Class.method` là MỘT token — query bare-name không bao giờ match nổi. Đã sửa:

- Tokenizer `unicode61` (split identifier thành component); DB cũ self-migrate khi writer mở (`_ensure_fts_tokenizer`, read-only bỏ qua, fail degrade — không cần reconcile lại).
- Query builder gom về helper chung `fts_query_terms` / `fts_rank_tier` / `exact_bare_name_flags` trong db.py; MCP bỏ logic duplicate, CLI không đổi.
- Exact-bare-name là **flag thứ hạng có giới hạn** (grade 2/1/0), không cộng điểm; trên `EXACT_BARE_NAME_CAP = 8` candidate cùng tên thì rút toàn bộ flag (chống push symbol cùng tên lên trên match qualified thật sự).
- Kết quả đo: holdout **Hit@1 0.7879 → 0.8818**, Hit@5 0.9515 → 0.9636, MRR 0.8548 → 0.9167 (jsonschema tụt nhẹ 0.833 → 0.800, báo cáo trung thực); synthetic semantic 75% → 100%, overall 93.8% → 100%, exact không đổi; 14 adversarial probes.
- Registry/docs sync 3 entries (commit cite `9127367`); full suite **1386 passed, 2 skipped**; claims lint clean; cả hai benchmark gates PASS.

## Chưa làm — thứ tự ưu tiên

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
