# Upstream provenance chain — CBM native engine (2026-09-05, P0 continuation)

Mục đích: đóng blocker G0-B1 (identity) và G0-B2 (source availability) bằng bằng chứng thật, đo được, mọi digest đều re-verify được từ đường dẫn ghi rõ. Ghi theo luật honesty gates: mọi claim có digest hoặc lệnh tái lập; thứ gì không đo được ghi UNKNOWN.

## 0. Quyết định provenance mới (user authorization 2026-09-05)

- External third-party attestation của binary đã cài là **không bắt buộc**. Hai kênh dưới đây đều là trusted evidence hợp lệ theo tài liệu gốc (mục 7: "Pin artifact SHA256 từ manifest phát hành tin cậy"):
  1. **Release-manifest binding:** manifest phát hành chính thức (checksums.txt) có digest xác thực qua API kênh phân phối, kèm sigstore bundle.
  2. **Controlled reproducible build receipt:** build có kiểm soát từ source pin đúng commit, ghi nhận recipe + toolchain + digest kết quả.
- Không khóa plan vào hash binary đã cài; binary đã cài không cần attestation ngoài.

## 1. Kênh phân phối thật (khám phá mới, sửa giả định cũ)

- Source repo (plan dẫn): `https://github.com/minhgv/codebase-memory-mcp` — HEAD/main = `3c7427efb740934bf66653413b484118652ce649` (verified `git ls-remote` 2026-09-05). **Không có release nào ở repo này** (API releases = `[]`).
- **Distribution repo (thật):** `https://github.com/DeusData/codebase-memory-mcp` — main = `fe85a6b2360839eee98fc6316e0ea58d38f15d60`; có tags + releases. Wrapper PyPI tải binary từ repo này (`REPO = "DeusData/codebase-memory-mcp"` — `codebase_memory_mcp/_cli.py:19` trong wheel 0.10.8).
- PyPI `codebase-memory-mcp` 0.10.8 (latest; 11 versions):
  - wheel `a5e39e6886bbdd7836cadaec13cdeb3ee3648c34fdf88359d9395abccc16287c` (14,871 B) — khớp digest PyPI JSON; là downloader-wrapper, KHÔNG chứa native binary.
  - sdist `d8186745440b33e4c11d66c619a425b8270933a0120f2b8ffc9e484c1a523ee0` (35,192 B) — khớp digest PyPI JSON.

## 2. Release v0.10.8 — commit pin chính xác

| Thực thể | Giá trị | Bằng chứng |
| :--- | :--- | :--- |
| Tag | `v0.10.8` → commit `46ae198fc11cda80e817acbc5f5908d7c2de7032` | `git ls-remote` DeusData; tag object fetched vào scratch clone (`refs/tags/deus-v0.10.8`), message "Break-glass merge PR #1719", 2026-08-18 22:39 +0200 |
| Published | 2026-08-19T02:42:10Z, 49 assets | GitHub API `releases?per_page=8` |
| checksums.txt | `9d2e33bdf9c9dc8662079d5b9a1bbf716aa2e62e2ed6cc51cf4ae06d42498787` (2,658 B) | API digest + tải về re-hash khớp; bản copy: `upstream-release/checksums-v0.10.8.txt` |
| Sigstore bundles | mỗi asset có `.bundle` (vd checksums bundle `b92dc7e4...`) | API assets list |
| SBOM (SPDX 2.3) | `23f4deeec3d052ced9174d94b16d322ba4bafa8d3e9fd6a0fcc63f36dcd729c9` — sqlite3 3.51.3, yyjson 0.12.0, mimalloc 3.3.2, xxhash 0.8.3, tre 0.8.0 | copy: `upstream-release/sbom.json` |
| release-selection.tsv | `c73fd277802b0d8b499a71600d1abcf3230b147ae1cbec8a5cbe69c8b04b4fbe` — darwin-arm64: stripped `2412e017...` selected, unstripped `260da338...`, debug `c3eb609f...`, tất cả "clean" qua VirusTotal | copy: `upstream-release/release-selection.tsv` |
| darwin-arm64 tar.gz | `9bd840dfb3ec7eaef4f310382057adaa5b0e904df883104d03ffcf39836afd07` (40,416,962 B) | khớp checksums.txt + API digest; tải về re-hash khớp |
| Inner binary (release) | **`2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf`**, 297,185,328 B, Mach-O arm64, sdk 14.5, adhoc `Identifier=codebase-memory-mcp-555549440039b2c48c7b344698fd00a015760a27` | giải nén từ tar.gz trên, `shasum -a 256` |

- Version pin đúng của release v0.10.8 là **`46ae198f`**, KHÔNG phải `010569f` như golden `_meta.json` claim. `010569fa6ce1bc5d6430f858129243ea1a2e3fd5` là merge trên main sau release (2026-08-21, 41 commit sau tag), và `pyproject.toml` tại 010569f vẫn ghi `version = "0.8.1"` (sửa thành 0.10.8 muộn hơn ở `5821078e` 2026-08-29 "correct stale packaging versions"). Kết luận: golden pin `0.10.8@010569f` là **mis-attribution của commit-time, không phải build-commit**; binary payload thì đúng là 0.10.8 (bằng chứng mục 3).

## 3. Binary đã cài ↔ release binding (WP0.2 closure evidence)

Installed: `~/.local/bin/codebase-memory-mcp` — 295,457,616 B, sha256 `996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435`, mtime 2026-08-25 14:06.

So sánh byte-wise với release binary `2412e017...` (python3 memcmp, 2,208 diff regions, tổng 573,774 byte khác):

| Vùng | Offset | Nội dung khác |
| :--- | :--- | :--- |
| Header load-commands | 1633–1634, 1648–1650, 2132–2134 (7 byte) | trường size trong load commands (`__LINKEDIT` nhỏ hơn) |
| Signature block | 294,863,413 → hết file (594KB diff) + 1,727,712 byte đuôi chỉ có ở release | ad-hoc CodeDirectory: installed 17,998 page-hashes (576,149 B) vs release 71,989 (2,303,861 B) |
| **Toàn bộ vùng giữa (≈294.8 MB: `__TEXT` 262,029,312 B, `__DATA_CONST`, `__DATA`, đầu `__LINKEDIT`)** | 2135 → 294,863,412 | **BYTE-IDENTICAL** |

- Cùng string set: 123,812 unique strings, diff = 0; cùng marker `0.10.8`; cùng LC_BUILD_VERSION (platform 1, minos 14.0, sdk 14.5); cùng code-sign Identifier.
- `size -m`: `__text` 20,745,352 B identical cả hai.
- **Verdict:** installed binary = nội dung thực thi + dữ liệu của release darwin-arm64 v0.10.8 chính thức, ad-hoc re-sign với coverage page-hash reduced. Version `0.10.8` CONFIRMED ở mức nội dung; build fingerprint trùng release stripped build. Digest file khác (`996bad5f…` ≠ `2412e017…`) do signature — ghi rõ để không ai dùng file-digest để phủ nhận identity.
- Không chạy binary trong bước này (static-only).

## 4. Source availability + license (WP0.4 closure evidence)

- Source full-history clone (scratch `/tmp/sot-p0-scratch/codebase-memory-mcp`): minh bạch — `.git` 193M, 2,120 file ở `3c7427e`; tag v0.10.8 fetch được.
- LICENSE: **MIT** (Copyright (c) 2025 DeusData). THIRD_PARTY_NOTICES.md (563,278 B) ship cùng binary trong release tar.gz — aggregates THIRD_PARTY.md + grammar provenance + verbatim texts (MIT/BSD/Apache-2.0). ⇒ binary redistribution notice requirements có sẵn từ upstream.
- Build recipe production: `make -f Makefile.cbm cbm` → `$(BUILD_DIR)/codebase-memory-mcp`; `CFLAGS_PROD = -O2 -DCBM_BIND_TS_ALLOCATOR=1 ... $(CFLAGS_EXTRA)`; version inject qua `-DCBM_VERSION` (Makefile.cbm:74, main.c:97 `#ifndef CBM_VERSION "dev"`); test seams opt-in `CBM_ENABLE_TEST_SEAMS` (không có trong prod build).

## 5. State-namespace facts cho scratch isolation (WP0.3 protocol — đọc từ source tag `46ae198f`)

| Nhà nước | Đường dẫn mặc định (macOS) | Override kiểm soát |
| :--- | :--- | :--- |
| Cache/index/config-store | `$HOME/.cache/codebase-memory-mcp` | `CBM_CACHE_DIR` trực tiếp (`platform.c:517`); config store là `_config.db` BÊN TRONG cache dir (`cli.h:397-401`) |
| Home resolution | `HOME` env trước, `USERPROFILE` sau | `HOME=<scratch>` đủ (`platform.c:440-449`) |
| Daemon rendezvous | `/private/tmp/cbm-daemon-<euid>/cbm-<key>.sock` (key = **hằng số** FNV-1a của `"codebase-memory-mcp:coordination-daemon"` — `service.c:144-162`) | **`CBM_RUNTIME_DIR`** (`bootstrap.c:227-232`) — bắt buộc set vì namespace là account-wide chung mọi project; binary production có `CBM_TEST_DAEMON_RUNTIME_PARENT` compile-out (`main.c:1265-1275`) |
| Global config dir | `XDG_CONFIG_HOME` else `~/.config` (`platform.c:462-482`) — dùng cho harness registration paths (CLAUDE_CONFIG_DIR/CODEX_HOME...) | set cả `XDG_CONFIG_HOME=<scratch>` |
| Watcher | `auto_watch` default **true** (`cli.c:6755`, `application.c:446`); tắt bằng `config set auto_watch false` (ghi vào `_config.db` trong scratch cache) | `CBM_WATCHER_PRUNE_GRACE_S` tuning (`watcher.c:119`) |
| Auto-index | default **false** (`application.c:1936`) | `auto_index` key |
| Build identity | daemon tự tính `build_fingerprint` = sha256 executable bytes (`service.h:60-61`) + `cache_fingerprint` = sha256 canonical cache path (`main.c:1241-1244`) + `protocol_abi` | version-cohort admission: build khác bị từ chối share daemon |
| Process role của `--version`/`--help` | `CBM_DAEMON_PROCESS_STATELESS` (`bootstrap.c:206-209`) | version probe an toàn: không đụng rendezvous |

**Isolation protocol (WP0.3) — mọi live spike phải set cho subprocess:**
`HOME=<scratch>/home`, `CBM_CACHE_DIR=<scratch>/home/.cache/codebase-memory-mcp`, `CBM_RUNTIME_DIR=<scratch>/runtime`, `XDG_CONFIG_HOME=<scratch>/home/.config`, `TMPDIR=<scratch>/tmp`; pre/post assert: (a) không file mới ngoài scratch (snapshot `~/Library/Caches/codebase-memory-mcp`, `~/.config`, `/private/tmp/cbm-daemon-*` trước/sau); (b) không process daemon sống sót ngoài namespace scratch (check `pgrep -f` binary-path trong scratch); (c) user's real daemon (`/private/tmp/cbm-daemon-<uid>/`) không bị chạm — chỉ đọc lstat, không connect.

## 6. Điều chỉnh evidence cũ

- `binary-identity.md` (đợt trước) kết luận "identity stays UNKNOWN, cần build attestation" — **superseded** bởi file này: kênh release manifest + byte-identity comparison là bằng chứng mạnh hơn attestation chung chung. File cũ giữ nguyên như lịch sử bất biến.
- "Candidate `3c7427e`": là main hiện tại của source repo minhgv (fork/line khác distribution repo). Việc nhập subtree (P4) sẽ dùng **tag `v0.10.8` = `46ae198f`** làm upstream-base trùng với binary đã verify, trừ khi P2/P3 đòi hỏi fix mới ở nhánh mới hơn.

## 7. Lệnh tái lập (từ trạng thái sạch)

```
git ls-remote https://github.com/DeusData/codebase-memory-mcp | grep refs/tags/v0.10.8
# → 46ae198fc11cda80e817acbc5f5908d7c2de7032  refs/tags/v0.10.8
curl -sS -L -O https://github.com/DeusData/codebase-memory-mcp/releases/download/v0.10.8/checksums.txt
shasum -a 256 checksums.txt   # = 9d2e33bd… (khớp API digest)
curl -sS -L -O https://github.com/DeusData/codebase-memory-mcp/releases/download/v0.10.8/codebase-memory-mcp-darwin-arm64.tar.gz
shasum -a 256 codebase-memory-mcp-darwin-arm64.tar.gz   # = 9bd840df… (khớp checksums.txt dòng darwin-arm64)
tar -xzf codebase-memory-mcp-darwin-arm64.tar.gz && shasum -a 256 codebase-memory-mcp   # = 2412e017…
# so với installed:
shasum -a 256 ~/.local/bin/codebase-memory-mcp   # = 996bad5f… (file-level KHÁC do signature)
# byte-region diff: python3 memcmp script (đã chạy 2026-09-05): 2208 regions, tất cả nằm ở header(7B) + signature block; thân code/data identical
```
