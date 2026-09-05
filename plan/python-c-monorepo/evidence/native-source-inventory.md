# Native source inventory — CBM engine (P4 measurement, 2026-09-06)

Mục đích: đo đạc thực tế (không suy đoán) kích thước nguồn upstream CBM để chọn ngân sách subtree ingestion cho P4. Mọi số liệu đều tái lập được bằng script + lệnh ghi rõ. Đọc-thôi; chưa build, chưa chạy binary.

## 1. Scope & fingerprint

- Repo: `/tmp/sot-p0-scratch/codebase-memory-mcp`, worktree **clean**, HEAD = `3c7427efb740934bf66653413b484118652ce649` (candidate main; `deus-main` = `fe85a6b`), 2,120 tracked files. **Lưu ý: candidate HEAD `3c7427e` ≠ release tag `v0.10.8` = `46ae198f`** — toàn bộ đo đạc dưới đây là của candidate tree, không phải release tree (hai tree khác nhau, xem §6).
- Tree fingerprint: `git archive HEAD | shasum -a 256` = `728dd980205f77f05acb572db6322495b2f8fa4815130136fe8724f9a1dc2569`.
- Tái lập: script đã lưu bản chính thức trong evidence — `native_inventory_walk.py` (chỉ đọc; gọi git qua `subprocess` argv, không shell; byte = tổng file-size, không phải du-block). Chạy: `python3 native_inventory_walk.py <repo-root>`. Receipt `native-inventory-walk.json` (cùng thư mục) là **composite được curate tường minh — KHÔNG phải raw stdout của script**: chỉ các field `commit, n_files_incl_git, worktree_total_bytes, git_dir_bytes, git_objects_bytes, categories, top10_worktree, tree_archive_sha256` do script sinh ra; các field bổ sung (grammar stats, handwritten breakdown, common-12 sum…) là supplemental đo thủ công bằng lệnh một-lần ghi trong chính receipt, và không có đảm bảo script xuất cùng một object.
- **Fix delta (review round 2):** script đổi `os.popen` (shell-interpolated) → `subprocess.check_output` argv không shell (2 chỗ: rev-parse, archive+hash qua hashlib); bỏ no-op `dirnames[:] = …`; đếm git objects theo prefix nghiêm `.git/objects/` (trước là substring `/objects/` bất kỳ). Test: chạy qua symlink có space trong đường dẫn (`"/tmp/sot-p0-scratch/space dir test/repo link"` → repo) — exit 0, mọi field tương đương baseline; `TREE_ARCHIVE_SHA256` `728dd980…` không đổi.

## 2. Aggregate bytes theo category

| Category | Bytes | Files | % worktree |
| :--- | ---: | ---: | ---: |
| **Worktree tổng (không .git)** | **1,373,533,436** | 2,120 | 100% |
| Generated tree-sitter grammar artifacts (parser.c/parser.h/node-types.json/grammar.json) | 1,291,016,001 | 345 | 94.0% |
| Vendored third-party source (không tính generated; `vendored/` + `internal/cbm/vendored/` trừ grammars) | 53,490,549 | 754 | 3.9% |
| Handwritten C (.c/.h ngoài vendored, không generated) | 23,686,134 | 658 | 1.72% |
| other_misc | 2,533,614 | 162 | 0.18% |
| docs_text | 1,374,179 | 41 | 0.10% |
| config_build_meta | 524,098 | 54 | 0.04% |
| python_source (wrapper) | 496,233 | 35 | 0.04% |
| ui_web_source | 412,628 | 70 | 0.03% |
| **Build outputs** | **0** | 0 | 0% |
| **`.git/`** (riêng, chưa tính ở trên) | **201,621,707** (objects 201,348,274) | — | — |

Handwritten C breakdown: `internal/cbm` first-party 6,401,592 B / 247 files; `src/` 6,564,126 B; `tests/` 10,653,714 B; `tools/tree-sitter-*` clones 66,702 B. Worktree clean ⇒ zero build outputs; `BUILD_DIR = build/c` (Makefile.cbm:737) chỉ xuất hiện khi build.

## 3. Top-10 file lớn nhất (worktree, exact bytes)

1. `internal/cbm/vendored/grammars/lean/parser.c` — 104,437,134
2. `internal/cbm/vendored/grammars/systemverilog/parser.c` — 62,155,935
3. `internal/cbm/vendored/grammars/verilog/parser.c` — 46,042,887
4. `internal/cbm/vendored/grammars/crystal/parser.c` — 45,156,077
5. `internal/cbm/vendored/grammars/sql/parser.c` — 41,602,005
6. `internal/cbm/vendored/grammars/objectscript_udl/parser.c` — 38,605,206
7. `internal/cbm/vendored/grammars/objectscript_routine/parser.c` — 37,982,320
8. `internal/cbm/vendored/grammars/tlaplus/parser.c` — 37,038,679
9. `internal/cbm/vendored/grammars/fortran/parser.c` — 36,355,864
10. `internal/cbm/vendored/grammars/ocaml/parser.c` — 36,101,908

Cả 10 đều là generated parser.c. Grammar stats: **162 grammars**, thư mục grammars tổng 1,285,192,368 B / 927 files; 6 nhỏ nhất (exact names + bytes): chialisp 14,057; csv 24,861; ini 25,148; json 27,667; dotenv 30,990; bibtex 51,237 — tổng 6 = 173,960 B. Set 12 ngôn ngữ phổ thông (json+toml+yaml+go+markdown+java+javascript+python+c+rust+typescript+bash) = 43,390,072 B parser.c; +cpp = 69,247,280 B.

**[FINDING]** `grammar.js` (nguồn grammar) = **0 file** trong `internal/cbm/vendored/grammars/` — grammars được vendored dạng generated-only (parser.c+scanner). `grammars/MANIFEST.md` ghi provenance: 143 vendored-from-upstream (đã pin upstream commit), 14 first-party, 5 registry-disagreement ⇒ generated parser.c KHÔNG tái sinh được từ trong repo; nếu cần grammar khác phải fetch upstream hoặc dùng như-is.

## 4. License / third-party categories

- Root `LICENSE`: **MIT** (Copyright (c) 2025 DeusData).
- `THIRD_PARTY.md` (180 dòng, 6 mục): Tree-sitter Runtime; Tree-sitter Grammars; Vendored C/C++ Libraries; Embedded Model Data; Hybrid LSP — Reference Language Servers; Embedded Graph UI. 176 file LICENSE/COPYING rải trong các vendored tree.
- Vendored C/C++ libs (bảng trong THIRD_PARTY.md): SQLite3 (Public Domain), mimalloc (MIT), yyjson (MIT), xxHash (BSD-2), TRE (BSD-2), LZ4 (BSD-2), zstd (BSD-3; chọn BSD trong dual BSD/GPLv2), simplecpp (0BSD), Verstable (MIT), wyhash (Unlicense). Token license trong THIRD_PARTY.md: MIT×17, Apache-2.0×6, BSD-3×3, BSD-2×3, ISC×2, Zlib×1, Unlicense×1; GPL chỉ xuất hiện như nhánh dual của zstd (đã chọn BSD) ⇒ toàn permissive, chỉ cần giữ notice.
- Release tarball đã ship `THIRD_PARTY_NOTICES.md` (563,278 B) aggregates đầy đủ (xem `provenance-upstream.md` §4) — **notices present**; đây chỉ là quan sát inventory, **chưa phải xác nhận pháp lý**: per-license compliance audit (điều khoản từng license, scope sử dụng, attribution format) **chưa làm — pending**.
- Embedded Model Data = `vendored/nomic/` (31.4 MB) — tách được khỏi "minimal host" nếu host chưa cần embed.

## 5. Build recipe + hook audit (chỉ đọc, chưa invoke)

- Build production: `make -f Makefile.cbm cbm` → `build/c/codebase-memory-mcp`; `CFLAGS_PROD = $(CFLAGS_COMMON) -O2 -DCBM_BIND_TS_ALLOCATOR=1 … $(CFLAGS_EXTRA)` (Makefile.cbm:78); version inject `-DCBM_VERSION` qua CFLAGS_EXTRA (:74); target `cbm-with-ui`/`embed` nhúng frontend. Không có target `install:`, không ghi `$HOME`/`/usr/local`; mọi output gom trong `build/*` trong repo. Test targets (test, test-tsan, test-lsan, test-daemon-smoke) tách riêng, không chạy trong bước này.
- `install.sh` (403 dòng): tải `checksums.txt` (guard ≤1 MiB, validate digest 64-hex + conflict-detect) rồi sha256-verify archive; HTTPS-only redirect; giải nén vào `INSTALL_DIR`; tự-update chỉ thay `install.sh` trong INSTALL_DIR. **Không có** hook launchctl/cron/profile/PATH persistence. Không được thực thi trong bước này (đọc static).
- Release workflow TẠI TAG `46ae198f` (đã `git show tag:…release.yml`, 643 dòng): sign job `id-token: write`, `sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6` # v4.1.2, `cosign sign-blob --yes --bundle "${f}.bundle" "$f"` cho `*.tar.gz *.zip *.mcpb` + 3 tsv + `checksums.txt` (:229–240); attest `actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373` # v4.1.1 + `attest-sbom@c604332985a26aa8cf1bdc465b92731239ec6b9e` # v4.1.0; tag release = **đúng `$GITHUB_SHA` được dispatch** (nêu rõ trong comment workflow). Lưu ý pin khác HEAD (HEAD đã lên attest-build-provenance v4.2.2) ⇒ mọi claim signing phải đọc tại tag, không tại main.

## 6. Budget recommendation (segregated — evidence vs proposal)

**[EVIDENCE — đã đo, không tranh luận]:**
1. 94.0% worktree bytes (candidate HEAD `3c7427e`) là generated parser.c; `.git` thêm 201.6 MB ⇒ full-subtree ≈ 1.58 GB, git history sẽ phình thêm do grammar churn.
2. Engine thực sự cần để build: first-party C ≈ 13.0 MB (internal/cbm 6.4 + src 6.6) + vendored non-generated ≈ 53.5 MB (22.1 MB nếu bỏ nomic embed) + grammar subset.
3. Grammar generated không regenerable trong repo (0 `grammar.js`); mỗi grammar dùng được độc lập: 12 ngôn ngữ phổ thông ≈ 43.4 MB parser.c (+cpp ≈ 69.2 MB); 6 nhỏ nhất = 174 KB ⇒ chi phí tuyến tính theo nhu cầu.
4. Tham chiếu sản phẩm — **cẩn thận đọc đúng**: binary ~297 MB (darwin-arm64 stripped) là **binary của RELEASE v0.10.8 (tag `46ae198f`)**, KHÔNG phải build của candidate HEAD `3c7427e` đang đo ở đây (hai tree khác nhau). Con số này chỉ minh hoạ hệ quả kích thước của hướng "all-grammar", không phải dự đoán build candidate.

**[PROPOSAL — topology/upstream patch proposal, CHƯA phải approval]:** "minimal initial native host" là đề xuất hình thái subtree (engine + libs cần thiết + một grammar subset được chọn tường minh) để trình bày/patch upstream — **không phải quyết định approve, và không ngầm prune/bỏ nguồn nào khỏi upstream clone**; mọi gramwar/vendored không đưa vào subtree ban đầu vẫn nằm nguyên trong clone nguồn và có thể thêm theo demand. Budget đề xuất ban đầu: **≈ 80–110 MB** (giảm ~93% so với 1.58 GB), mở rộng tuyến tính. Quyết định cuối thuộc P4 review.

## 7. Lệnh tái lập chính

```
cd /tmp/sot-p0-scratch/codebase-memory-mcp && git rev-parse HEAD   # 3c7427e…
git archive HEAD | shasum -a 256                                    # 728dd980…
python3 native_inventory_walk.py /tmp/sot-p0-scratch/codebase-memory-mcp   # bảng mục 2, 3 (script cùng thư mục file này)
for f in internal/cbm/vendored/grammars/*/parser.c; do stat -f%z "$f"; done
git show 46ae198fc11cda80e817acbc5f5908d7c2de7032:.github/workflows/release.yml
```
