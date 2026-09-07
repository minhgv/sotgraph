# Hợp đồng triển khai nhiều giai đoạn — Arch HTML Renderer (`sotgraph arch`)

Ngày chốt: 2026-09-07 · Phương án: A điều chỉnh (đề xuất trong phiên làm việc cùng ngày) · Trạng thái: **hoàn tất 2026-09-07 (GĐ1–GĐ4) — GĐ5 tùy chọn chưa duyệt**

## 1. Mục tiêu

Render kiến trúc repo và luồng hoạt động của module/chức năng ra **một file HTML tự chứa, đẹp theo tinh thần archify nhưng tinh gọn**, xây trên dữ liệu đã verified của sotgraph (knowledge graph + analytics + trace/explore/be-flow).

- `sotgraph arch [-o architecture.html] [--scope <dir>]` — sơ đồ kiến trúc tổng thể, layout phân tầng theo vai trò module.
- `sotgraph arch --flow "<module|symbol|feature>" [--depth N] [--max-nodes M] [--lanes module] [-o flow.html]` — sơ đồ luồng hoạt động, layout top-down có số bước, nhánh quyết định, tuỳ chọn swimlane theo module.

## 2. Phi mục tiêu (không làm trong hợp đồng này)

- Video/WebM export, share card 1200×630, guided stories, presentation stage (archify có, bỏ).
- Sequence/data-flow/lifecycle diagram types độc lập (flow mode phủ nhu cầu luồng).
- Delta/compare view trước–sau (để dành v2 sau, dữ liệu snapshot head_sha đã có sẵn).
- Thay thế hay sửa đổi `sotgraph viz` hiện có (d3 force giữ nguyên nguyên vẹn).

## 3. Bất biến kỹ thuật (vi phạm = trả công đoạn đó)

| # | Bất biến | Cách kiểm chứng |
|---|---|---|
| I1 | **Zero dependency mới**: không thêm package runtime nào, `uv.lock` không đổi nhóm deps | `git diff uv.lock` trống sau mỗi giai đoạn |
| I2 | **Single-file tự chứa**: output HTML không trỏ tài nguyên ngoài (không CDN, không fetch mạng, không font tải về) | `grep -E "https?://|\bfetch\(" output.html` chỉ chấp nhận URL evidence `path:line` dạng text |
| I3 | **Deterministic byte-stable**: cùng DB state → 2 lần render ra file sha256 giống hệt nhau (không timestamp, không random) | chạy 2 lần + `shasum -a 256` so sánh |
| I4 | **Offline**: mở file không cần mạng, JS tương tác chạy hoàn toàn local | mở `file://` thủ công |
| I5 | **Honesty**: target không đủ dữ liệu trong graph → badge `INSUFFICIENT_SAMPLING`, không bịa node/edge | test unit ép subgraph rỗng |
| I6 | **Trust verdict hiển thị**: node mang màu vòng theo verdict ([STRONG]/[WEAK]/[REBUILT]/[REMOVED]) khi dữ liệu có | test unit + soi HTML |
| I7 | **Không sửa file provenance đã pin** (repodle exceptions, RELEASE_NOTES_v0.3.2.md…) | `python3 scripts/check_repository_identity.py` sạch sau mỗi giai đoạn |
| I8 | **Fail-closed validation**: render từ chối ghi file nếu validator fail (node ngoài viewport, edge trỏ node không tồn tại, flow >1 entry hiển thị, số bước đứt) | test unit các ca lỗi |
| I9 | **Tiêu chuẩn P9 áp dụng**: ruff + pyright sạch trên code mới; bandit không finding mới | chạy gate-scoped commands |

## 4. Kiến trúc & thiết kế

### 4.1. File mới / file sửa

- MỚI `src/sot_graph/export/arch_html.py` — IR builders + renderer + validators (tim cốt lõi).
- MỚI `src/sot_graph/export/arch_layout.py` — 2 layout deterministic (tiered + flow), chia riêng để test.
- SỬA `src/sot_graph/cli.py` — subcommand `arch` (thêm ~40 dòng wiring).
- MỚI `tests/test_arch_html.py` (+ tách `tests/test_arch_layout.py` nếu dài) — determinism, validation, budget, honesty.
- SỬA `README.md` + `docs/RELEASE.md` — mục lệnh mới (Giai đoạn 4).

### 4.2. IR (internal, typed dataclass / dict)

```
ArchView {
  layout: "tiered" | "flow"
  title, project, generated_from(scope|target)
  nodes: [ { id, label, tier|step, role, loc, symbols, verdict?, evidence: "path:line" } ]
  edges: [ { src, dst, kind: calls|imports|adapter|api, label?, weight } ]
  lanes?: [ { id, label, nodes: [...] } ]        # flow mode, theo module
  branches?: [ { at_node, condition, to_node } ] # flow mode, từ ui-tree/trace
  truncation?: { capped: bool, shown, total, hint_depth }
}
```

- Tiered mode: data từ `AnalyticsGraph.from_database` (như viz) + heuristic vai trò theo path (`cli/commands`, `adapters`, `providers`, `assurance/core`, `db/storage`, `export`).
- Flow mode: data tái dùng extractor sẵn có — đường thực thi từ trace/explore, nhánh quyết định từ ui-tree, micro-steps từ be-flow. **Không viết bộ phân tích mới.**

### 4.3. Thuật toán layout (không thư viện)

- Tiered: xếp node vào tầng vai trò, trong tầng giảm giao cắt bằng barycenter 2-3 sweep; toạ độ pixel nguyên.
- Flow: xếp tầng theo BFS-depth từ entry node, barycenter dùng chung, node đánh số bước 1..N, nhánh vẽ diamond; swimlane = nhóm cột theo module.
- Budget: `--max-nodes` (mặc định 60) — vượt thì giữ top-N theo trọng số relevance + badge truncation (triết lý pack hard-budget).

### 4.4. Design tokens (mượn archify, ghi cứng trong template)

- Nền slate: canvas `#020617`, surface `#0F172A`, border `#1E293B`, ink `#FFFFFF`, muted `#94A3B8`.
- Ngữ nghĩa: cyan `#22D3EE` (CLI/entry), green `#34D399` (core/verified), violet `#A78BFA` (storage/db), amber `#FBBF24` (external/adapter), rose `#FB7185` (violation), orange `#FB923C` (flow branch).
- Trust ring: STRONG green · WEAK amber · REBUILT orange · REMOVED rose (dim).
- Typography: một phông mono (system stack: `ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace`); hierarchy chỉ bằng weight/scale/case, label uppercase + letter-spacing.
- Chuyển động: hover/focus 150ms, tôn trọng `prefers-reduced-motion`; glow chỉ khi focus.
- Light theme: đổi chất liệu bằng CSS variables, không đổi màu ngữ nghĩa.

### 4.5. Tương tác JS (inline, ~150 dòng, vanilla)

- Ô search: dim node không khớp (phím `/` focus).
- Click node → panel "passport": in/out refs, verdict, evidence `path:line` (text click-chọn).
- Toggle sáng/tối; legend; header metrics.

## 5. Giai đoạn & tiêu chí nghiệm thu

### Giai đoạn 1 — Nền tảng: IR + tiered layout + HTML tĩnh + CLI
**Sản phẩm**: `arch_html.py` + `arch_layout.py` (tiered) + subcommand `arch`; render architecture page có node card, edge SVG, header metrics, legend, dark/light toggle; chưa có JS tương tác phức tạp.
**Nghiệm thu**:
- [x] `uv run sotgraph arch -o /tmp/a1.html` trên repo này chạy sạch, file tồn tại, mở offline được.
- [x] Determinism: chạy 2 lần → `shasum -a 256` trùng nhau (I3).
- [x] `uv run python -m pytest tests/test_arch_html.py tests/test_arch_layout.py -q` — 0 failed.
- [x] I1/I2/I7/I9 pass (grep, git diff uv.lock, identity, ruff+pyright scoped).

### Giai đoạn 2 — Flow mode: trích luồng + layout bậc thang
**Sản phẩm**: flow IR builder từ trace/explore/be-flow; layout flow (BFS-depth + barycenter + số bước + branch diamond + swimlane); flags `--flow/--depth/--max-nodes/--lanes`; badge truncation + `INSUFFICIENT_SAMPLING`.
**Nghiệm thu**:
- [x] `uv run sotgraph arch --flow "cmd_search" --depth 3 -o /tmp/f1.html` — vẽ đúng đường gọi của một lệnh thật; soi HTML thấy số bước + nhãn cạnh.
- [x] Budget: `--max-nodes 5` với target rộng → badge truncation đúng số shown/total.
- [x] Target không tồn tại trong index → exit khác 0 kèm thông báo honest (I5), hoặc render với badge INSUFFICIENT_SAMPLING theo thiết kế — chốt: **exit 2 + message**, không sinh file.
- [x] Determinism cho flow (I3); pytest thêm ca: >1 entry bị validator chặn (I8).

### Giai đoạn 3 — Tương tác & polish
**Sản phẩm**: search dim, passport panel (in/out refs + verdict + evidence), hover nhãn cạnh, focus ring, print stylesheet, prefers-reduced-motion.
**Nghiệm thu**:
- [x] Mở file: `/` focus search, gõ "cli" dim node khác; click node → panel đúng in/out counts khớp DB (`sotgraph usages` đối chiếu 1 node bất kỳ).
- [x] Không network call (I2/I4); determinism vẫn giữ (I3).

### Giai đoạn 4 — Validation gate hoàn chỉnh + tests + docs + CI
**Sản phẩm**: validators đủ điều khoản I8; bộ pytest đầy đủ (determinism, validator fail-closed, budget, honesty, tier heuristic); README mục mới + RELEASE.md; toàn bộ CI xanh trên commit cuối.
**Nghiệm thu**:
- [x] Full suite local: ≥ số test hiện tại + các test mới, 0 failed.
- [x] Push main → CI & Release xanh (không cần tag).
- [x] Docs nêu đúng cú pháp 2 chế độ; identity audit sạch.

### Giai đoạn 5 — (tùy chọn, chỉ làm khi user duyệt riêng) MCP `sot_arch` + delta view
Mở rộng MCP surface để agent gọi trực tiếp; delta view dùng snapshot head_sha. Ngoài phạm vi hợp đồng này.

## 6. Quy ước làm việc

- Sub-agent (cavecrew-builder) thực hiện từng giai đoạn; chủ phiên nghiệm thu độc lập bằng lệnh trong mục 5 trước khi commit.
- Mỗi giai đoạn = 1 commit `feat(arch): stage N — <mô tả>`; không trộn giai đoạn.
- Kế hoạch thực thi: Giai đoạn 1–2 trong phiên hiện tại nếu êm; 3–4 ngay sau.
- Mọi thay đổi phải giữ CI xanh theo chuẩn hiện có (15 job test × 3 OS, Q9 gates).

## 7. Chữ nghiệm thu cuối (Definition of Done toàn hợp đồng)

```bash
uv run sotgraph arch -o /tmp/arch.html && uv run sotgraph arch --flow "cmd_search" --depth 3 -o /tmp/flow.html
uv run sotgraph arch -o /tmp/arch2.html && shasum -a 256 /tmp/arch.html /tmp/arch2.html   # trùng nhau
uv run python -m pytest tests/ -q        # 0 failed
python3 scripts/check_repository_identity.py
uvx bandit -q -c bandit.yaml -r src/sot_graph && uv run --locked pyright src/sot_graph/export/arch_html.py src/sot_graph/export/arch_layout.py
git diff uv.lock                          # trống
```
— tất cả pass, CI xanh trên main.

## 8. Ghi chú nguồn cảm hứng

tt-a1i/archify (MIT): JSON IR → deterministic single-file HTML/SVG, zero-dep, design tokens slate + semantic palette, mono typography, evidence capsule, atomic validation. Chỉ học phương thức trình bày; không sao chép code.

## 9. Bằng chứng nghiệm thu thực thi (2026-09-07)

| Giai đoạn | Commit | CI GitHub | Ghi chú |
| :--- | :--- | :--- | :--- |
| Hợp đồng | `23a90ed` | — | file .md, paths-ignore |
| GĐ1 IR + tiered | `82dbd1e` | run `34109165664` success | 20/20 job xanh |
| GĐ2 flow + budget | `47c3e78` | run `34111334495` cancelled | bị cancel do concurrency khi GĐ3 push đè, không phải fail |
| GĐ3 tương tác | `151a8ec` | run `34112385904` **success** | 20 job success + 2 publish skip (không tag) — commit mang code cuối cùng |
| GĐ4 docs | `7c28215` | không trigger — chủ động | commit chỉ chứa `.md` (README, RELEASE.md, plan/) → rơi đúng `paths-ignore: ["**.md", "plan/**"]` của ci.yml; code test trong CI 151a8ec giống hệt tree 7c28215 |

DoD cục bộ chạy trên tree `7c28215` (không chỉ 151a8ec): RENDER_BOTH_OK; determinism 2 lần render trùng sha; 0 external refs; pytest `2281 passed, 5 skipped, 0 failed`; identity audit OK; bandit 0; pyright 0 lỗi; `uv.lock` không đổi. Lệnh tái kiểm: mục 7 (chữ DoD) — chạy nguyên văn được bất cứ lúc nào.
