# P2 Provider-Layer Native Acceptance — measured PASS (2026-09-06)

- Production tip: `8d83f64` (chain `a61a62d` → `8131295` managed publication failure → `8d83f64` ledger concurrency, branch `feat/python-c-monorepo-phased`). Docs HEAD lúc chạy: `8f504ff`. Host: macOS arm64 (1 host, duy nhất).
- Binary: `~/.local/bin/codebase-memory-mcp` `996bad5f…435` (= release v0.10.8 content, engine `46ae198f…032`).
- Harness: `p2-provider-acceptance-harness.py` (cùng thư mục) — **đã được reviewer độc lập review TRƯỚC khi chạy**.
- Receipt sanitized: `p2-provider-acceptance-receipt.json` (file này cùng thư mục; copy từ `/private/tmp/s-iqndnov6/provider-acceptance-receipt.json`, sha256-16 `9cbbaf6623a1285d`; KHÔNG kèm raw log — raw ở run scratch).

## Kết quả đo (exit 0, total 64.18s)

| Mục | Giá trị đo |
|---|---|
| Env preflight | 7-key replacement (HOME/CBM_CACHE_DIR/CBM_RUNTIME_DIR/XDG_CONFIG_HOME/TMPDIR, PATH=/usr/bin:/bin, TERM=dumb) + UI-off pre-seed |
| Provider binding checks | 4/4 true (`managed_is_runtime`, `repo_binding`, `exe_binding`, `exact_context_is_ctx`) |
| `prepare` | ok, READY, 6.133s |
| `index_repository` | ok, 39.699s, **no ledger binding** |
| `search_graph` | ok, freshness **UNBOUND**, `snapshot_bound=false`, 17.915s |
| Query no-mutation | bytes (bao gồm WAL/SHM) unchanged + ledger rows unchanged |
| Native span | 63.758s ≤ budget 120s |
| Tổng | PASS, exit 0, 64.18s |

Ghi chú nhất quán thiết kế [INFERENCE]: `index` không publish ledger binding và `search` UNBOUND/`snapshot_bound=false` khớp semantics "no circular freshness" — managed dispatch không expose native head nên không publish binding, không bao giờ fresh (đã được assert mocked ở `test_native_head_missing_publishes_no_binding_never_fresh`); live run này quan sát đúng hành vi đó, KHÔNG phải failure.

## Phạm vi trung thực (bắt buộc)

- **1 host, 1 lần chạy (n=1).** Không variance, không platform thứ hai, không native CI.
- **Không có independent global process inventory trong run này** (không pgrep inventory độc lập pre/post) — không đụng global được chứng minh bằng env isolation 7-key + UI-off, KHÔNG phải bằng inventory tiến trình.
- **Cancellation KHÔNG đo lại trong run này:** bằng chứng timeout hiện có vẫn là lần đo executor trước — `cancellation_unknown` + QUARANTINED persist (`p2-managed-acceptance.md` mục timebound); vẫn là evidence hiện hành.
- KHÔNG tuyên bố terminal daemon known; KHÔNG tuyên bố G2 pass toàn phase từ run này.

## Ý nghĩa gate G2 (theo literal gate, không bịa)

Literal G2 (`execution-plan.md` §3): query không đổi source/index generation/ledger; không đụng global daemon/config; cancellation confirm HOẶC unknown an toàn; no orphan writer báo success.

- **Đóng gap "live provider acceptance":** binding layer giờ có measured native PASS tại tip `8d83f64` (trước đó chỉ mocked). Query no-mutation đo được (bytes WAL/SHM + ledger rows unchanged).
- **Gap G2 còn lại (1):** isolation/orphan unsafe-success proof — bằng chứng có định nghĩa rằng không orphan writer báo success, gồm global non-interference có inventory (run này chưa có process inventory độc lập). Chỉ gap này chặn G2; mọi hạn chế khác (CLI/installer P4/P5, trust registry, G0-B3, 11/15 tool) là later-stage, không phải điều kiện G2.
- G2 vẫn **KHÔNG promote** cho tới gap còn lại có bằng chứng.
