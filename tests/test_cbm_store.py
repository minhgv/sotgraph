"""CbmStore + CBM-first reconcile dispatch tests.

Fixture: a minimal codebase-memory engine store built to the pinned
contract (``sot_graph.cbm.REQUIRED_TABLES`` / ``REQUIRED_COLUMNS``) inside
the isolated ``<root>/.sot/cbm/cache`` directory, next to a real sot.db
holding builtin rows for files CBM does not cover plus user notes.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from sot_graph.cbm import (
    covered_paths, coverage_gaps, find_cbm_db, locate_project,
    reconcile_dispatch, schema_probe,
)
from sot_graph.db import Database
from sot_graph.graphstore import CbmContractError, CbmStore, open_store
from sot_graph.reconciler import Reconciler

PROJECT = "proj-test"


def _build_cbm_db(path: str, root: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE projects (
            name TEXT PRIMARY KEY,
            indexed_at TEXT NOT NULL,
            root_path TEXT NOT NULL
        );
        CREATE TABLE nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            label TEXT NOT NULL,
            name TEXT,
            qualified_name TEXT,
            file_path TEXT NOT NULL,
            start_line INTEGER,
            end_line INTEGER,
            properties TEXT
        );
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            source_id INTEGER,
            target_id INTEGER,
            type TEXT NOT NULL,
            properties TEXT
        );
        CREATE TABLE file_hashes (
            project TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            sha256 TEXT,
            mtime_ns INTEGER,
            size INTEGER
        );
        CREATE TABLE index_coverage (
            project TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT DEFAULT '',
            PRIMARY KEY (project, rel_path, kind)
        );
        CREATE TABLE store_meta (k TEXT PRIMARY KEY, v TEXT);
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE nodes_fts USING fts5("
        "name, qualified_name, label, file_path, content='', "
        "tokenize='unicode61 remove_diacritics 2')")
    conn.execute(
        "INSERT INTO projects VALUES (?, '2026-01-01T00:00:00', ?)",
        (PROJECT, root))
    conn.executemany(
        "INSERT INTO store_meta (k, v) VALUES (?, ?)",
        [("db_uid", "testuid123"), ("mutation_gen", "7")])

    def node(label, name, fqn, path, props="{}"):
        cur = conn.execute(
            "INSERT INTO nodes (project, label, name, qualified_name,"
            " file_path, start_line, end_line, properties)"
            " VALUES (?,?,?,?,?,1,10,?)",
            (PROJECT, label, name, fqn, path, props))
        conn.execute(
            "INSERT INTO nodes_fts (rowid, name, qualified_name, label,"
            " file_path) VALUES (?,?,?,?,?)",
            (cur.lastrowid, name, fqn, label, path))
        return cur.lastrowid

    # src/covered.py — fully CBM-indexed file.
    a = node("Function", "alpha", "covered.alpha", "src/covered.py")
    b = node("Function", "beta", "covered.beta", "src/covered.py")
    # Resolved call (lsp_direct, confidence 0.95).
    conn.execute(
        "INSERT INTO edges (project, source_id, target_id, type, properties)"
        " VALUES (?,?,?,?,?)",
        (PROJECT, a, b, "CALLS",
         '{"line": 5, "confidence": 0.95, "strategy": "lsp_direct"}'))
    # Heuristic call (unique_name, confidence 0.67) → pending, not resolved.
    conn.execute(
        "INSERT INTO edges (project, source_id, target_id, type, properties)"
        " VALUES (?,?,?,?,?)",
        (PROJECT, b, a, "CALLS",
         '{"line": 8, "confidence": 0.67, "strategy": "unique_name",'
         ' "callee": "alpha", "candidates": 1}'))
    # Heuristic call with multiple candidates → AMBIGUOUS.
    conn.execute(
        "INSERT INTO edges (project, source_id, target_id, type, properties)"
        " VALUES (?,?,?,?,?)",
        (PROJECT, a, b, "CALLS",
         '{"line": 9, "confidence": 0.3, "strategy": "suffix_match",'
         ' "callee": "beta", "candidates": 3}'))
    # Non-CALLS relation always resolved.
    conn.execute(
        "INSERT INTO edges (project, source_id, target_id, type, properties)"
        " VALUES (?,?,?,?,?)",
        (PROJECT, a, b, "USAGE", '{"line": 6}'))

    conn.execute(
        "INSERT INTO file_hashes VALUES (?,?,?,?,?)",
        (PROJECT, "src/covered.py", "abc123", 1_700_000_000_000_000_000, 100))
    conn.execute(
        "INSERT INTO index_coverage VALUES (?,?,?,?)",
        (PROJECT, "src/partial.py", "parse_partial", ""))
    conn.execute(
        "INSERT INTO index_coverage VALUES (?,?,?,?)",
        (PROJECT, "src/skipme.py", "not_indexed_file", ""))
    conn.commit()
    conn.close()


@pytest.fixture()
def repo(tmp_path):
    """Root with one CBM-covered file, one gap file, a note, and a
    sot-side journal row for a file CBM now owns (stale leftover)."""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    for name in ("covered.py", "gap.py"):
        with open(os.path.join(root, "src", name), "w") as fh:
            fh.write("x = 1\n")

    cache = os.path.join(root, ".sot", "cbm", "cache")
    os.makedirs(cache, exist_ok=True)
    cbm_path = os.path.join(cache, f"{PROJECT}.db")
    _build_cbm_db(cbm_path, root)

    os.makedirs(os.path.join(root, ".sot"), exist_ok=True)
    sot_path = os.path.join(root, ".sot", "sot.db")
    db = Database(sot_path)
    # Builtin-owned rows: the gap file (CBM absent) and the covered file
    # (stale leftover from a builtin-era index — must be shadowed).
    rec = Reconciler(db, root)
    rec.reconcile_path(os.path.join(root, "src", "gap.py"))
    rec.reconcile_path(os.path.join(root, "src", "covered.py"))
    db.conn.execute(
        "INSERT INTO graph_nodes (id, path, kind, symbol, label, body,"
        " keywords, line_start, updated_at)"
        " VALUES ('note:t1', '', 'note', NULL, 'keep-me', 'body', 'kw', 1, 0)")
    db.conn.commit()
    db.close()
    return {"root": root, "cbm": cbm_path, "sot": sot_path}


def _store(repo):
    return CbmStore(repo["cbm"], repo["sot"], repo["root"])


def test_find_db_and_project(repo):
    assert find_cbm_db(repo["root"]) == repo["cbm"]
    conn = sqlite3.connect(repo["cbm"])
    try:
        assert locate_project(conn, repo["root"]) == PROJECT
        assert schema_probe(conn) == []
    finally:
        conn.close()


def test_find_db_missing(tmp_path):
    assert find_cbm_db(str(tmp_path)) is None


def test_views_union_and_ownership(repo):
    store = _store(repo)
    try:
        rows = store.conn.execute(
            "SELECT id, path, kind, symbol, fqn FROM graph_nodes"
        ).fetchall()
        by_path = {}
        for r in rows:
            by_path.setdefault(r[1], []).append(r)

        covered = by_path.get(
            os.path.join(repo["root"], "src", "covered.py"), [])
        # Only CBM rows for the covered path — the stale sot-side rows for
        # the same file must be shadowed by the coverage guard.
        assert covered and all(r[0].startswith("cbm:") for r in covered)
        assert {r[3] for r in covered} == {"alpha", "beta"}
        assert all(r[2] == "function" for r in covered)  # label lowered

        # Gap file stays builtin-owned (sot journal uses absolute paths).
        gap = [r for r in rows if r[1].endswith("gap.py")]
        assert gap and not any(r[0].startswith("cbm:") for r in gap)

        # Notes always fall through to the sot side.
        notes = [r for r in rows if r[2] == "note"]
        assert notes and not any(r[0].startswith("cbm:") for r in notes)
    finally:
        store.close()


def test_edges_resolution_honesty(repo):
    store = _store(repo)
    try:
        resolved = store.conn.execute(
            "SELECT relation, line FROM graph_edges ORDER BY line"
        ).fetchall()
        # lsp_direct CALLS + USAGE resolved; heuristic CALLS excluded.
        rels = sorted(r[0] for r in resolved)
        assert rels == ["calls", "uses"]
        pending = store.conn.execute(
            "SELECT dst_symbol, resolution_state FROM pending_edges"
            " ORDER BY line"
        ).fetchall()
        assert pending == [("alpha", "UNRESOLVED"), ("beta", "AMBIGUOUS")]
    finally:
        store.close()


def test_file_journal_union(repo):
    store = _store(repo)
    try:
        paths = {
            r[0] for r in store.conn.execute("SELECT path FROM file_journal")
        }
        covered_abs = os.path.join(repo["root"], "src", "covered.py")
        assert covered_abs in paths                      # cbm file_hashes row
        assert any(p.endswith("gap.py") for p in paths)  # sot gap row
    finally:
        store.close()


def test_snapshot_and_gaps(repo):
    store = _store(repo)
    try:
        assert store.snapshot["db_uid"] == "testuid123"
        assert store.snapshot["mutation_gen"] == "7"
        gaps = store.coverage_gaps()
        assert gaps["skipped"] == ["src/skipme.py"]
        assert gaps["parse_partial"] == ["src/partial.py"]
        names = {p["name"] for p in store.providers_present()}
        assert names == {"codebase-memory", "tree-sitter-ast"}
    finally:
        store.close()


def test_search_fts_cbm(repo):
    store = _store(repo)
    try:
        hits = store.search_fts("alpha")
        assert hits and hits[0]["id"].startswith("cbm:")
        assert hits[0]["path"] == os.path.join(
            repo["root"], "src", "covered.py")
    finally:
        store.close()


def test_write_guards_refuse(repo):
    store = _store(repo)
    try:
        with pytest.raises(CbmContractError):
            store.commit_file("/x.py", "h", 1, 1, [], [], [])
        with pytest.raises(CbmContractError):
            store.delete_path("src/covered.py")
    finally:
        store.close()


def test_open_store_fallbacks(repo, tmp_path):
    # Bound project present → CbmStore.
    store = open_store(repo["root"], repo["sot"])
    try:
        assert isinstance(store, CbmStore)
    finally:
        store.close()
    # No cbm db → plain Database.
    other = str(tmp_path / "elsewhere")
    os.makedirs(other, exist_ok=True)
    sot2 = os.path.join(other, ".sot", "sot.db")
    os.makedirs(os.path.dirname(sot2), exist_ok=True)
    Database(sot2).close()
    store = open_store(other, sot2)
    try:
        assert not isinstance(store, CbmStore)
        assert isinstance(store, Database)
    finally:
        store.close()


def test_contract_mismatch_falls_back(repo, tmp_path):
    # A db file exists but lacks the contract tables → open_store must
    # degrade to Database rather than raise.
    bad = os.path.join(os.path.dirname(repo["cbm"]), "rogue.db")
    conn = sqlite3.connect(bad)
    conn.execute("CREATE TABLE whatever (x TEXT)")
    conn.commit()
    conn.close()
    store = open_store(repo["root"], repo["sot"])
    try:
        # The valid db is still found first (sorted order may pick rogue;
        # either way the result must be a working store).
        assert isinstance(store, Database)
        store.conn.execute("SELECT 1 FROM graph_nodes LIMIT 1")
    finally:
        store.close()


def test_coverage_helpers(repo):
    conn = sqlite3.connect(repo["cbm"])
    try:
        assert covered_paths(conn, PROJECT) == {"src/covered.py"}
        skipped, partial = coverage_gaps(conn, PROJECT)
        assert skipped == ["src/skipme.py"]
        assert partial == ["src/partial.py"]
    finally:
        conn.close()


def test_dispatch_builtin_mode(repo):
    db = Database(repo["sot"])
    try:
        rec = Reconciler(db, repo["root"])
        out = reconcile_dispatch(db, rec, repo["root"], extractor="builtin")
        assert out["extractor"] == "tree-sitter-ast"
        assert "extractor_fallback" not in out
    finally:
        db.close()


def test_dispatch_cbm_disabled_falls_back(repo):
    # Provider disabled in .sot/config.toml → builtin with honest reason.
    with open(os.path.join(repo["root"], ".sot", "config.toml"), "w") as fh:
        fh.write('[providers.codebase-memory]\nenabled = false\n')
    db = Database(repo["sot"])
    try:
        rec = Reconciler(db, repo["root"])
        out = reconcile_dispatch(db, rec, repo["root"], extractor="auto")
        assert out["extractor"] == "tree-sitter-ast"
        assert out.get("extractor_fallback") == "cbm_disabled"
    finally:
        db.close()


def test_dispatch_cbm_index_failure_falls_back(repo, monkeypatch):
    # Engine spawn/index failure degrades to builtin, never raises.
    from sot_graph import cbm as cbm_mod

    class _Fail:
        status = "error"
        project = None
        nodes = edges = not_indexed = duration_ms = 0
        skipped: list = []
        parse_partial: list = []

    monkeypatch.setattr(cbm_mod, "run_index", lambda *a, **k: _Fail())
    db = Database(repo["sot"])
    try:
        rec = Reconciler(db, repo["root"])
        out = reconcile_dispatch(
            db, rec, repo["root"], extractor="auto",
            cbm_command=["fake-cbm-binary"])
        assert out["extractor"] == "tree-sitter-ast"
        assert out.get("extractor_fallback") == "cbm_index_failed:error"
    finally:
        db.close()
