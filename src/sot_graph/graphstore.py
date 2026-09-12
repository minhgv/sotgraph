"""sot_graph.graphstore — CBM-native graph store.

``CbmStore`` subclasses :class:`sot_graph.db.Database` so every surface
that receives a ``db`` gets one object speaking the same contract. The
underlying connection opens the codebase-memory store read-only and
ATTACHes ``.sot/sot.db``; TEMP VIEWs then recreate the sot read schema
(``graph_nodes`` / ``graph_edges`` / ``file_journal`` / ``pending_edges``)
over the CBM tables, unioned with the sot-side rows of files CBM did not
cover (gap fill). No projection, no sync — the CBM db IS the graph.

Semantics preserved by the views:

- **replace-by-path ownership** — each path's rows come from exactly one
  provider: CBM wherever ``nodes.file_path`` covers it, builtin otherwise.
  Notes (``kind='note'``, virtual paths) always fall through to sot rows.
- **resolution honesty** — CBM CALLS edges carry ``strategy`` +
  ``confidence``. LSP/import-typed strategies (>= 0.8) become resolved
  ``graph_edges``; heuristic name-match strategies become ``pending_edges``
  (AMBIGUOUS when ``candidates`` > 1, else UNRESOLVED), so ``usages()``
  keeps reporting PARTIAL + risk lists instead of pretending name-guesses
  are call sites.
- **snapshot binding** — CBM node ids are AUTOINCREMENT and regenerate
  per index; ``snapshot`` exposes ``(db_uid, mutation_gen)`` so receipts
  bind the generation they read instead of trusting bare ids.

Writes: the attached sot.db stays writable (ledger/notes/journal for gap
files); the CBM main schema is read-only. Graph-shape mutations
(``commit_file``, ``delete_path`` …) are refused — CBM owns extraction.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sot_graph.cbm import (
    coverage_gaps, locate_project, schema_probe, snapshot_token,
)
from sot_graph.db import (
    Database, exact_bare_name_flags, fts_query_terms, fts_rank_tier,
)

#: CALLS edges below this confidence are heuristic name matches, not
#: resolved call sites — they surface as pending_edges, not graph_edges.
_RESOLVED_CONFIDENCE = 0.8

_RELATION_MAP = {
    "CALLS": "calls", "CALL_REFERENCE": "calls",
    "USAGE": "uses", "IMPORTS": "imports",
    "INHERITS": "extends", "IMPLEMENTS": "implements",
    "DEFINES": "defines", "DEFINES_METHOD": "defines",
    "CONTAINS_FILE": "defines", "CONTAINS_FOLDER": "defines",
    "TESTS": "tests", "TESTS_FILE": "tests",
    "WRITES": "writes", "HTTP_CALLS": "http_calls",
    "SIMILAR_TO": "similar_to", "SEMANTICALLY_RELATED": "semantic",
    "OVERRIDE": "overrides", "DECORATES": "decorates",
    "RAISES": "raises", "THROWS": "throws",
    "CONFIGURES": "configures", "HANDLES": "handles",
}

#: sot.db tables read paths may touch that must exist for name resolution
#: when sot.db is absent entirely (union partners handled separately).
_STANDIN_TABLES: Dict[str, str] = {
    "provider_evidence": (
        "id INTEGER PRIMARY KEY, run_id INTEGER, provider_name TEXT, "
        "kind TEXT, symbol TEXT, src_symbol TEXT, dst_symbol TEXT, "
        "path TEXT, file_path TEXT, line INTEGER, relation TEXT, "
        "snapshot_hash TEXT, detail TEXT, invalidated_at INTEGER, "
        "invalidation_reason TEXT"
    ),
    "provider_runs": (
        "id INTEGER PRIMARY KEY, provider_name TEXT, provider_version TEXT, "
        "capability TEXT, operation TEXT, status TEXT, detail TEXT, "
        "duration_ms INTEGER, exit_code INTEGER, snapshot_hash TEXT, "
        "started_at INTEGER, finished_at INTEGER"
    ),
    "provider_project_bindings": (
        "id INTEGER PRIMARY KEY, sot_repo_id TEXT, provider_name TEXT, "
        "provider_project_id TEXT, provider_generation INTEGER, "
        "bound_at INTEGER"
    ),
    "graph_communities": (
        "community_id INTEGER, label TEXT, cohesion_score REAL, "
        "node_count INTEGER, nodes_json TEXT, created_at INTEGER"
    ),
}


class CbmContractError(RuntimeError):
    """The CBM store does not satisfy the pinned contract; caller must
    fall back to the builtin extractor and disclose."""


class CbmStore(Database):
    """Database-compatible read store backed by a codebase-memory db."""

    is_cbm = True

    def __init__(
        self,
        cbm_path: str,
        sot_path: str,
        root: str,
        *,
        timeout_ms: int = 5_000,
    ) -> None:
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        self.db_path = os.path.abspath(sot_path)   # logical identity: the sot project
        self.cbm_path = os.path.abspath(cbm_path)
        self.root_dir = os.path.realpath(root)
        self.read_only = True
        self.timeout_ms = int(timeout_ms)
        self.schema_was_reset = False

        uri = "file:" + quote(self.cbm_path, safe="/") + "?mode=ro"
        self._conn = sqlite3.connect(
            uri, uri=True, timeout=self.timeout_ms / 1000.0)
        self._owner_thread = __import__("threading").get_ident()
        self.conn.execute(f"PRAGMA busy_timeout = {self.timeout_ms}")
        # No query_only: TEMP VIEWs are built below, and the ATTACHed
        # sot.db must stay writable for ledger/evidence writes. The CBM
        # main schema is protected by mode=ro on the open URI.

        self.project = locate_project(self.conn, self.root_dir)
        if self.project is None:
            self.conn.close()
            raise CbmContractError(
                f"no CBM project bound to root {self.root_dir} in {cbm_path}")
        missing = schema_probe(self.conn)
        if missing:
            self.conn.close()
            raise CbmContractError(
                "CBM store does not satisfy contract "
                f"(missing: {', '.join(missing)})")
        self.snapshot: Dict[str, Any] = snapshot_token(self.conn)

        self._sot_attached = self._attach_sot()
        self._create_views()

    # ------------------------------------------------------------------
    # schema bridge
    # ------------------------------------------------------------------
    def _attach_sot(self) -> bool:
        """ATTACH .sot/sot.db (ledger + gap-file rows + notes)."""
        if not os.path.isfile(self.db_path):
            return False
        try:
            self.conn.execute(
                "ATTACH DATABASE ? AS sot", (self.db_path,))
        except sqlite3.Error:
            return False
        # The attach must expose the tables the union views rely on; a
        # legacy/foreign file degrades to cbm-only views.
        try:
            names = {
                r[0] for r in self.conn.execute(
                    "SELECT name FROM sot.sqlite_master WHERE type='table'")
            }
        except sqlite3.Error:
            names = set()
        return {"graph_nodes", "graph_edges", "file_journal",
                "pending_edges"} <= names

    def _sot_has(self, table: str) -> bool:
        if not self._sot_attached:
            return False
        try:
            row = self.conn.execute(
                "SELECT 1 FROM sot.sqlite_master WHERE name = ? AND type='table'",
                (table,),
            ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None

    def _create_views(self) -> None:
        """TEMP VIEWs recreating the sot read schema over CBM tables."""
        proj = self.project
        gen = self.snapshot.get("mutation_gen") or "0"
        try:
            gen_int = int(gen)
        except (TypeError, ValueError):
            gen_int = 0

        relation_case = " ".join(
            f"WHEN '{k}' THEN '{v}'" for k, v in _RELATION_MAP.items())
        resolved_cond = (
            "NOT (e.type = 'CALLS' AND COALESCE("
            "CAST(json_extract(e.properties,'$.confidence') AS REAL), 0.0)"
            f" < {_RESOLVED_CONFIDENCE})"
        )
        # Parameter placeholders are not allowed inside CREATE VIEW; the
        # project name comes from our own store so interpolate it safely.
        def _q(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        p = _q(proj)
        rootp = _q(self.root_dir + "/")
        sot = self._sot_attached
        # Path-shape mismatch: sot rows key by ABSOLUTE path, CBM by
        # repo-relative. Normalize the sot side by stripping ``<root>/``
        # before the coverage guards — without this, stale sot rows leak
        # into every union (dup nodes, zombie journal rows flagging
        # 'modified' on files CBM indexed fresh seconds ago).
        rel = f"replace(path, '{self.root_dir}/', '')"
        gap_guard = (
            f"{rel} NOT IN (SELECT file_path FROM nodes "
            f"WHERE project = {p})"
        )
        fh_guard = (
            f"{rel} NOT IN (SELECT rel_path FROM file_hashes "
            f"WHERE project = {p})"
        )

        # Consumers assume ``path`` is absolute (arch prefix filters,
        # diff-impact matching, verifier relpath→abspath): emit
        # ``<root>/`` || rel_path so CBM rows are indistinguishable from
        # sot rows downstream — the relative spelling is engine-internal.
        nodes_base = f"""SELECT 'cbm:' || n.id AS id,
       {rootp} || n.file_path AS path,
       lower(n.label) AS kind,
       n.name AS symbol,
       n.qualified_name AS fqn,
       json_extract(n.properties, '$.signature') AS signature,
       n.label AS label,
       COALESCE(json_extract(n.properties, '$.docstring'), '') AS body,
       COALESCE(json_extract(n.properties, '$.bt'), '') AS keywords,
       n.start_line AS line_start,
       n.end_line AS line_end,
       NULL AS col_start,
       NULL AS col_end,
       CAST(COALESCE(strftime('%s', p.indexed_at), '0') AS INTEGER) AS updated_at
FROM nodes n JOIN projects p ON p.name = n.project
WHERE n.project = {p}"""
        if sot:
            nodes_base += f"""
UNION ALL
SELECT id, path, kind, symbol, fqn, signature, label, body, keywords,
       line_start, line_end, col_start, col_end, updated_at
FROM sot.graph_nodes WHERE {gap_guard}"""

        edges_base = f"""SELECT {rootp} || s.file_path AS path,
       'cbm:' || e.source_id AS src,
       'cbm:' || e.target_id AS dst,
       CASE e.type {relation_case} ELSE lower(e.type) END AS relation,
       CAST(json_extract(e.properties, '$.line') AS INTEGER) AS line
FROM edges e JOIN nodes s ON s.id = e.source_id AND s.project = e.project
WHERE e.project = {p} AND {resolved_cond}"""
        if sot:
            edges_base += f"""
UNION ALL
SELECT path, src, dst, relation, line
FROM sot.graph_edges WHERE {gap_guard}"""

        pending_base = f"""SELECT {rootp} || s.file_path AS path,
       'cbm:' || e.source_id AS src,
       json_extract(e.properties, '$.callee') AS dst_symbol,
       'calls' AS relation,
       CAST(json_extract(e.properties, '$.line') AS INTEGER) AS line,
       '' AS language,
       'UNKNOWN' AS call_kind,
       NULL AS receiver,
       NULL AS import_source,
       CASE WHEN COALESCE(CAST(json_extract(e.properties, '$.candidates')
                AS INTEGER), 0) > 1
            THEN 'AMBIGUOUS' ELSE 'UNRESOLVED' END AS resolution_state
FROM edges e JOIN nodes s ON s.id = e.source_id AND s.project = e.project
WHERE e.project = {p} AND e.type = 'CALLS' AND NOT {resolved_cond}"""
        if sot:
            pending_base += f"""
UNION ALL
SELECT path, src, dst_symbol, relation, line, language, call_kind,
       receiver, import_source, resolution_state
FROM sot.pending_edges WHERE {gap_guard}"""

        journal_base = f"""SELECT {rootp} || f.rel_path AS path,
       f.sha256 AS sha256,
       f.size AS size,
       CAST(f.mtime_ns / 1000000 AS INTEGER) AS mtime_ms,
       {gen_int} AS generation,
       CAST(COALESCE(strftime('%s', p.indexed_at), '0') AS INTEGER) AS reconciled_at,
       NULL AS parser_outcome,
       NULL AS parser_error
FROM file_hashes f JOIN projects p ON p.name = f.project
WHERE f.project = {p}"""
        if sot:
            journal_base += f"""
UNION ALL
SELECT path, sha256, size, mtime_ms, generation, reconciled_at,
       parser_outcome, parser_error
FROM sot.file_journal WHERE {fh_guard}"""

        for name, select in (
            ("graph_nodes", nodes_base),
            ("graph_edges", edges_base),
            ("pending_edges", pending_base),
            ("file_journal", journal_base),
        ):
            self.conn.execute(f"CREATE TEMP VIEW {name} AS {select}")

        if not sot:
            for table, ddl in _STANDIN_TABLES.items():
                self.conn.execute(
                    f"CREATE TEMP TABLE IF NOT EXISTS {table} ({ddl})")

    # ------------------------------------------------------------------
    # contract additions
    # ------------------------------------------------------------------
    def coverage_gaps(self) -> Dict[str, List[str]]:
        skipped, partial = coverage_gaps(self.conn, self.project)
        return {"skipped": skipped, "parse_partial": partial}

    def providers_present(self) -> List[Dict[str, str]]:
        providers = [{"name": "codebase-memory", "kind": "COMPILER_LSP_INDEX"}]
        if self._sot_attached:
            try:
                row = self.conn.execute(
                    "SELECT 1 FROM sot.graph_nodes "
                    "WHERE replace(path, ?, '') NOT IN "
                    "(SELECT file_path FROM nodes WHERE project = ?) "
                    "LIMIT 1", (self.root_dir + "/", self.project),
                ).fetchone()
            except sqlite3.Error:
                row = None
            if row:
                providers.append(
                    {"name": "tree-sitter-ast",
                     "kind": "AST_HEURISTIC_PARSER"})
        return providers

    # ------------------------------------------------------------------
    # overrides where the sot schema cannot be view-mapped
    # ------------------------------------------------------------------
    def search_fts(
        self, query: str, limit: int = 10, scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """FTS over CBM ``nodes_fts`` (contentless; rowid = nodes.id),
        same ranking contract as the builtin path."""
        tokens, parts_l = fts_query_terms(query)
        if not tokens or limit <= 0:
            return []
        sql = (
            "SELECT 'cbm:' || k.id, ? || k.file_path, lower(k.label), k.name, "
            "k.qualified_name, k.label, "
            "COALESCE(json_extract(k.properties,'$.docstring'), ''), "
            "COALESCE(json_extract(k.properties,'$.bt'), ''), "
            "k.start_line, bm25(nodes_fts) "
            "FROM nodes_fts f JOIN nodes k ON f.rowid = k.id "
            "WHERE nodes_fts MATCH ? AND k.project = ?"
        )
        params: List[Any] = [self.root_dir + "/",
                             " OR ".join(sorted(tokens)), self.project]
        if scope:
            esc = scope.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND (k.file_path LIKE ? ESCAPE '\\')"
            params.append(f"%{esc}%")
        sql += " ORDER BY bm25(nodes_fts) ASC LIMIT ?"
        params.append(limit * 3)
        rows = self.conn.execute(sql, params).fetchall()
        flags = exact_bare_name_flags([r[3] for r in rows], parts_l)

        def _rank(pair):
            r, flag = pair
            score = r[9]
            text = f"{r[3] or ''} {r[5] or ''}".lower()
            tier, file_demote = fts_rank_tier(r[2], text, parts_l)
            return (tier, file_demote, -flag, score)

        rows = [r for r, _ in sorted(zip(rows, flags), key=_rank)]
        return [
            {"id": r[0], "path": r[1], "kind": r[2], "symbol": r[3],
             "fqn": r[4], "label": r[5], "body": r[6], "keywords": r[7],
             "line_start": r[8], "score": abs(r[9])}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # write guards — the CBM schema is engine-owned
    # ------------------------------------------------------------------
    def _readonly_graph(self, *_a, **_kw):
        raise CbmContractError(
            "CbmStore is read-only for graph shape: the codebase-memory "
            "engine owns extraction (run `sotgraph reconcile` to reindex); "
            "journal/ledger writes use a plain Database on .sot/sot.db")

    commit_file = _readonly_graph
    commit_file_batch = _readonly_graph
    delete_path = _readonly_graph
    delete_node_by_id = _readonly_graph
    update_node_path = _readonly_graph
    rehome_file_atomically = _readonly_graph
    resolve_pending_edges = _readonly_graph
    resolve_all_pending_edges = _readonly_graph
    apply_clean = _readonly_graph

    def save_communities(self, communities_data: List[Dict[str, Any]]) -> None:
        """Communities are sot-side metadata, not graph shape — persist to
        the attached sot.db (temp standin when no sot.db exists)."""
        import json as _json
        import time as _time

        target = ("sot.graph_communities" if self._sot_attached
                  else "graph_communities")
        now = int(_time.time())
        with self.conn:
            self.conn.execute(f"DELETE FROM {target}")
            for c in communities_data:
                nodes = c.get("nodes", [])
                nodes_json = (_json.dumps(nodes)
                              if not isinstance(nodes, str) else nodes)
                self.conn.execute(
                    f"INSERT INTO {target} (community_id, label,"
                    " cohesion_score, node_count, nodes_json, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        int(c["community_id"]), str(c["label"]),
                        float(c.get("cohesion_score", 0.0)),
                        int(c.get("node_count", len(nodes))),
                        nodes_json, now,
                    ),
                )


def open_store(
    root: str,
    db_path: str,
    *,
    read_only: bool = False,
    timeout_ms: int = 5_000,
) -> Database:
    """Factory: CbmStore when a bound CBM store satisfies the contract,
    else the builtin Database. Never raises for cbm reasons — absence or
    contract mismatch degrades to builtin silently (callers disclose via
    ``providers_present`` / extractor fields)."""
    from sot_graph.cbm import find_cbm_db

    cbm_path = find_cbm_db(root)
    if cbm_path is not None:
        try:
            return CbmStore(cbm_path, db_path, root, timeout_ms=timeout_ms)
        except (CbmContractError, sqlite3.Error, OSError):
            pass
    return Database(db_path, read_only=read_only, timeout_ms=timeout_ms)
