# W9 — CBM-Native Graph Store (sotgraph reads codebase-memory DB directly)

> **Status: IMPLEMENTED** — verified end-to-end trên repo này:
> `reconcile` → `[codebase-memory:full]` 19.1s (incremental), 35,696 cbm
> nodes / 194,966 edges, 30 gap-filled, 70 parse-partial, 559 ownership
> purged; `search`/`explore`/`usages`/`map`/`pack`/`diff-impact` đều chạy
> qua CbmStore (explore Reconciler: 144 inbound callers discovered —
> builtin trước đó ~16k edges toàn repo). Fallback: `--extractor builtin`
> byte-compat; CBM vắng/lỗi → builtin + `extractor_fallback` disclosed.

**Mục tiêu:** codebase-memory (CBM) làm extractor mặc định; sotgraph đọc
CBM SQLite store trực tiếp (mode=ro + TEMP VIEWs) — query ms-level, zero
spawn per query, không sync/projection layer. tree-sitter builtin là
fallback khi CBM vắng/lỗi và là gap-filler cho file CBM không parse được.

**Non-goals (v1):** không viết lại sotgraph bằng C; không CBM export
sot-format; không fork VIEW patch (TEMP VIEW trong sotgraph thay thế —
contract + version gate tương đương, bỏ C release dependency; fork patch
để optional hardening sau); không semantic-vector search surface (db đã
có sẵn `node_vectors` — mở đường cho wave sau).

## Kiến trúc

```
WRITE  sotgraph reconcile → spawn cbm index_repository (isolated env:
       CBM_RUNTIME_DIR/CBM_CACHE_DIR=.sot/cbm/*, cohort domain riêng —
       không đụng daemon interactive của user) → CBM tự ghi store
READ   surfaces → Database-shaped store (factory open_store)
         ├─ CbmStore: cbm.db mode=ro + ATTACH sot.db + TEMP VIEWs
         │            graph_nodes|graph_edges|file_journal|pending_edges
         │            → mọi raw-SQL + inherited read methods chạy nguyên
         └─ Database (SotStore): builtin fallback + journal/ledger/notes
FRESH  ensure_fresh probe: disk (mtime,size) vs cbm file_hashes → stale
       → extractor dispatch (cbm index | builtin fallback) → disclose
```

### Contract (TEMP VIEWs, version-gated)

- Schema probe trước khi mở store: required tables (`nodes`, `edges`,
  `file_hashes`, `index_coverage`, `store_meta`, `nodes_fts`) + required
  columns → mismatch → fallback builtin + `extractor_fallback` disclosed.
- `store_meta.db_uid` + `mutation_gen` = snapshot token → receipts bind
  (db_uid, mutation_gen): node ids chỉ hợp lệ trong generation đó
  (CBM AUTOINCREMENT ids đổi mỗi index — honest staleness).
- Node id: `cbm:<nodes.id>`; fqn: `qualified_name`.

### Mapping

| sot | cbm |
|---|---|
| graph_nodes.kind | lower(nodes.label): Function→function, Method→method, Class→class, Route→route, File→file, Module→module, Field→field, Variable→variable, Macro→macro, Section→section, EnvVar→envvar |
| graph_nodes.signature | json_extract(properties,'$.signature') |
| graph_nodes.body | coalesce(docstring, label) — properties JSON |
| graph_nodes.keywords | properties.bt (bag-tokens) |
| graph_edges.relation | lower(type): CALLS/CALL_REFERENCE→calls, USAGE→uses, IMPORTS→imports, INHERITS→extends, IMPLEMENTS→implements, DEFINES(_METHOD)→defines, TESTS→tests, WRITES→writes, HTTP_CALLS→http_calls, SIMILAR_TO→similar_to, SEMANTICALLY_RELATED→semantic, CROSS_*→lower passthrough |
| file_journal | file_hashes: path=rel_path, sha256, size, mtime_ms=mtime_ns/1e6, generation=mutation_gen |
| pending_edges | CBM CALLS heuristic (confidence < 0.8: unique_name/suffix_match/...) → UNRESOLVED/AMBIGUOUS ∪ sot.db pending_edges (fallback files) — name-guess không giả làm call site |

### FTS exception

`graph_fts MATCH` chỉ 2 call site (`db.search_fts`, `mcp_service` ranker).
CbmStore override `search_fts` → `nodes_fts MATCH` (bm25); mcp ranker
detect `nodes_fts` trên conn và đổi FROM/JOIN (`k.id = 'cbm:'||f.rowid`),
vẫn đi qua `graph_nodes` TEMP VIEW cho mọi cột output.

### Fallback tiers

1. CBM binary vắng / spawn fail / schema probe fail / version mismatch →
   full builtin reconcile (behavior hiện tại) + stderr disclose.
2. CBM index OK nhưng `index_coverage` có `skipped`/`parse_partial` →
   `Reconciler.reconcile_paths(gap_files)` fill vào sot.db; surfaces union
   CbmStore ∪ SotStore-gap per path (ownership: mỗi path đúng 1 provider).

### Config

`.sot/config.toml`: `extractor = "auto"|"cbm"|"builtin"` (default auto),
`cbm_mode = "full"|"moderate"|"fast"` (default full). Env:
`SOT_EXTRACTOR`, `SOT_CBM_MODE`.

### CLI

- `sotgraph reconcile` — extractor dispatch (cbm primary khi auto).
- `sotgraph reconcile --mode fast|moderate|full` → cbm_mode override per-run.
- `sotgraph reconcile --extractor builtin` → skip CBM (đường fast cũ).
- Alias `reconcile-fast`/`reconcile-full` = reconcile --mode fast/full;
  ẩn khỏi `--help` (SUPPRESS) — một lệnh duy nhất cần nhớ là `reconcile`.
- Không xung đột: cùng WriteLock + replace-by-path ownership.

### Caveats (disclosed)

- cbm.db `journal_mode=delete` → writer exclusive trong index run
  (15s-2min): query lúc đó → SQLITE_BUSY → busy_timeout + receipt
  `indexing_in_progress` (cùng class LockBusy). Fork-side publish-snapshot
  (atomic rename) = hardening sau.
- CBM edges không đảm bảo per-edge line → relation line NULL cho phần
  không có.
- `explore`/`usages` completeness: pending_edges chứa cả heuristic edges
  của CBM lẫn gap-file pending → status PARTIAL khi có heuristic
  name-match, COMPLETE khi mọi edge resolved — honest, không inflate.
- `watch` daemon vẫn ghi builtin per-file: với path CBM-covered, sot rows
  bị coverage-guard che (vô hình, purge ở reconcile sau); với gap file
  vẫn hữu ích. JIT probe phát hiện drift qua file_hashes → reconcile
  dispatch re-index CBM đúng semantics.
- `insert`/notes: path='' → coverage-guard tự rơi về sot — notes luôn
  sot-owned, CbmStore chỉ đọc.

### Command coverage audit (post-implementation)

Routed qua `open_store` (CbmStore khi bound): search, explore, usages,
implementations, map, pack, trace, diff-impact, scope-receipt, report,
bundle, viz, arch, export, ui-tree, be-flow, solution, log, commits,
commit-verdict, calibrate, cluster (save_communities → sot attach),
rename (read-only), verify (union journal audit), embed (vec tables
schema-qualified `sot.` — unqualified CREATE sẽ nhắm main=cbm ro và fail).

Sot-side by design: insert (ghi note), reconcile/batch-reconcile
(dispatch), clean (purge sot slice + disclose engine untouched),
vacuum (sot.db file), import-scip (ghi sot — warn shadowed khi cbm bound),
watch (builtin per-file; shadowed rows purge ở reconcile sau),
doctor (sot stats + engine-store disclosure line), setup/providers/engine/
receipt/claims (admin, không phụ thuộc graph rows).

MCP: `_connection` → open_store + legacy raw-connect fallback (bare
fixture dbs); ranker detect `nodes_fts`; `_reconcile_before_analysis` →
reconcile_now → dispatch.

## Wave DAG & file ownership

| Wave | Files | Nội dung |
|---|---|---|
| W9.1 store | `graphstore.py` (mới), `cbm.py` (mới) | CbmStore subclass, TEMP VIEWs, schema probe, snapshot token, discovery |
| W9.2 reconcile | `reconciler.py`, `cli.py` (cmd_reconcile), `config.py`, `freshness.py` | extractor dispatch, isolated-env spawn, gap-fill, modes + aliases |
| W9.3 wiring | `cli.py` (main), `mcp_service.py` | open_store factory trên read paths, FTS call-site fix, providers envelope |
| W9.4 tests | `tests/test_cbm_store.py` | fake cbm db fixture, view union/ownership, edge-honesty, fallback, dispatch modes |

## Acceptance

- `sotgraph reconcile` trên repo này (cbm present): extractor=cbm trong
  summary; `search "Reconciler"` trả kết quả từ cbm.db; `explore` BFS qua
  cbm edges; receipt snapshot binds (db_uid, mutation_gen).
- CBM binary renamed → cùng command fallback builtin + disclose.
- `reconcile --extractor builtin` === reconcile cũ (byte-compat summary).
- Query p50 không regression vs SotStore trên search/explore/usages.
- tests mới green + suite hiện hữu không đổi (fallback path mặc định khi
  cbm vắng — fixtures chạy không cần cbm binary).
