# P2 Provider Acceptance + Process Inventory — measured PASS, G2 closed scoped (2026-09-06)

- Production tip: `b08f0de` (chain … `8131295` → `8d83f64` → `8f504ff` → `721fa3d` → `b08f0de`, branch `feat/python-c-monorepo-phased`). Host: macOS arm64 (1 host, duy nhất).
- Binary: `~/.local/bin/codebase-memory-mcp` `996bad5f…435` (= release v0.10.8 content, engine `46ae198f…032`).
- Harness: `p2-provider-acceptance-harness.py` — **reviewed ở dạng hiện hành SAU fix `--cbm-daemon-internal`** (working tree, chưa commit — ngoài phạm vi phiên này).
- Receipt sanitized: `p2-provider-inventory-receipt.json` (cùng thư mục; copy từ `/private/tmp/s-0tu3gw6w/provider-acceptance-receipt.json`, sha256 `1e264bc2a411b0d908bba06076366aa4d8576699ecdb10e6eb852653d22e291d`).
- Bằng chứng trước (`p2-provider-acceptance.md` + `-receipt.json`) giữ nguyên READ-ONLY: nguồn cho invariance source/index/WAL/SHM/ledger; receipt hiện tại cũng xác nhận lại (mục dưới).

## Kết quả đo (exit 0, wall 63.39s)

| Mục | Giá trị đo |
|---|---|
| Env preflight | 7-key + UI-off pre-seed, pre-native |
| Provider binding | 4/4 true (`managed_is_runtime`, `repo_binding`, `exe_binding`, `exact_context_is_ctx`) |
| Registry ops | đúng 6 (`config_get/set_auto_watch`, `index_repository`, `index_status`, `list_projects`, `search_graph`) |
| `prepare` | ok READY 5.974s |
| `index` | ok 38.251s, `ledger_binding_row=false` |
| `search` | ok UNBOUND `snapshot_bound=false` 17.529s |
| Query no-mutation | bytes incl WAL/SHM unchanged + ledger rows unchanged (khớp bằng chứng trước) |
| Native span | 61.763s ≤ budget 120s (reserves 62/60/32); process poll 1.126s |
| **Process inventory** | baseline **6** pre-existing matched — **giữ nguyên toàn bộ (pid+start)**; **no new matching remain** (post-poll snapshot rỗng) |
| Method inventory | passive ps; **pid+start+role only**; KHÔNG signal, KHÔNG adoption |
| Receipt flags | `no_native_run_at_authoring=true`; `sot_head=5de4d6f6…` (projection head, không phải git ref) |

## Giới hạn trung thực (bắt buộc)

- **KHÔNG chứng minh causal termination:** post-poll rỗng = "không còn process mới nào khớp"; KHÔNG claim nguyên nhân kết thúc hay linkage nhân-quả.
- Cancellation vẫn là **unknown-safe**, không phải confirmed: bằng chứng native-cancel thật vẫn KHÔNG có.

## Bằng chứng bổ trợ (không thay thế native cancel)

- `tests/test_managed_orphan_writer.py` @ `b08f0de` (simulated live-worker timeout): **2 passed, lặp 5 lần main-run, 0.25–0.26s mỗi lần** — worker thật vẫn sống, timeout mocked → **KHÔNG phải bằng chứng native cancellation thật**; chỉ chứng minh SOT-side refuse unsafe-success.

## Verdict gate G2 — PASS scope hẹp (2026-09-06)

Literal G2 (`execution-plan.md` §3): query không đổi source/index/ledger; không đụng global; cancellation confirm HOẶC unknown an toàn; no orphan writer báo success.

- **Đủ theo literal gate:** query no-mutation đo được (run này + run trước); isolation global có **process inventory độc lập** (baseline 6 preserved pid+start, no new matching remain); cancellation = `cancellation_unknown` + QUARANTINED persist — gate cho phép unknown an toàn; orphan writer báo success bị refuse (executor + tests `b08f0de`).
- **G2 = PASS SCOPED.** Giới hạn tường minh: 1 host macOS arm64; programmatic-only; n nhỏ (mỗi scenario n=1). **KHÔNG** là: product release, CLI/installer (P4/P5), platform nào khác, native CI.
- **G3 KHÔNG promote:** full boundary fault matrix (`execution-plan.md` §4) chưa hoàn tất — không claim phần thiếu. Provider-ledger rollback đã commit sẵn `8131295`.
- Phiên ghi evidence này: docs-only — không chạy native, không chạy test, không commit.
