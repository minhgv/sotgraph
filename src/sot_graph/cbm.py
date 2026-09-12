"""sot_graph.cbm — codebase-memory (CBM) engine integration helpers.

Owns the pieces that let CBM act as sotgraph's DEFAULT extraction layer:

- ``cbm_env`` — isolated coordination domain (``CBM_RUNTIME_DIR`` /
  ``CBM_CACHE_DIR`` under ``.sot/cbm/``) so a sotgraph-spawned engine never
  collides with an interactive CBM daemon the user already runs (version
  cohort refuses mixed generations — observed: an interactive daemon from
  another build blocks ``cli`` startup entirely).
- ``find_cbm_db`` / ``locate_project`` — discover the engine's own SQLite
  store and the project row bound to this repo root.
- ``schema_probe`` — pin the contract this build was verified against
  (same posture as the managed ``_config.db`` pin): required tables +
  columns, else callers must fall back to the builtin extractor.
- ``run_index`` — explicit ``index_repository`` spawn (write path only;
  never invoked from a read path).

Read-side access to the store lives in ``graphstore.CbmStore``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sot_graph.proc import run_command

#: Contract revision this adapter was verified against. Bump when the
#: required schema below changes; mismatches must fall back, never guess.
CONTRACT_VERSION = "cbm-store-1"

#: Tables the read path (graphstore TEMP VIEWs + freshness probe) depends on.
REQUIRED_TABLES: Tuple[str, ...] = (
    "nodes", "edges", "file_hashes", "index_coverage",
    "store_meta", "nodes_fts", "projects",
)

REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "nodes": ("id", "project", "label", "name", "qualified_name",
              "file_path", "start_line", "end_line", "properties"),
    "edges": ("id", "project", "source_id", "target_id", "type", "properties"),
    "file_hashes": ("project", "rel_path", "sha256", "mtime_ns", "size"),
    "index_coverage": ("project", "rel_path", "kind"),
    "store_meta": ("k", "v"),
    "projects": ("name", "indexed_at", "root_path"),
}

_DEFAULT_INDEX_TIMEOUT_S = 600
_DEFAULT_QUERY_TIMEOUT_S = 30


def cbm_dir(root: str) -> str:
    """Repo-local CBM home: ``<root>/.sot/cbm``."""
    return os.path.join(root, ".sot", "cbm")


def cbm_env(root: str) -> Dict[str, str]:
    """Isolated coordination domain for a sotgraph-spawned engine.

    Separate ``CBM_RUNTIME_DIR``/``CBM_CACHE_DIR`` gives this engine its own
    version-cohort locks and project store — no interaction with whatever
    daemon another tool (editor MCP, manual cli) already runs.
    """
    base = cbm_dir(root)
    runtime = os.path.join(base, "runtime")
    cache = os.path.join(base, "cache")
    for path in (runtime, cache):
        os.makedirs(path, mode=0o700, exist_ok=True)
    return {"CBM_RUNTIME_DIR": runtime, "CBM_CACHE_DIR": cache}


def cbm_cache_dir(root: str) -> str:
    return os.path.join(cbm_dir(root), "cache")


def _iter_store_dbs(root: str) -> List[str]:
    cache = cbm_cache_dir(root)
    if not os.path.isdir(cache):
        return []
    return [
        os.path.join(cache, name)
        for name in sorted(os.listdir(cache))
        if name.endswith(".db") and name != "_config.db"
        and not name.endswith(("-wal", "-shm"))
    ]


def _open_ro(db_path: str) -> sqlite3.Connection:
    from urllib.parse import quote

    uri = "file:" + quote(os.path.abspath(db_path), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA busy_timeout = 3000")
    return conn


def find_cbm_db(root: str) -> Optional[str]:
    """Locate the engine store bound to ``root`` inside the isolated cache.

    Discovery is by ``projects.root_path`` equality, never by filename
    guessing — the engine's name-derivation rules are its own.
    """
    canonical = os.path.realpath(root)
    for db_path in _iter_store_dbs(root):
        try:
            conn = _open_ro(db_path)
            try:
                rows = conn.execute(
                    "SELECT root_path FROM projects WHERE root_path != ''"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            continue
        if any(os.path.realpath(r[0]) == canonical for r in rows if r[0]):
            return db_path
    return None


def locate_project(conn: sqlite3.Connection, root: str) -> Optional[str]:
    """Project name in the engine store bound to this repo root."""
    canonical = os.path.realpath(root)
    try:
        rows = conn.execute(
            "SELECT name, root_path FROM projects WHERE root_path != ''"
        ).fetchall()
    except sqlite3.Error:
        return None
    for name, root_path in rows:
        if root_path and os.path.realpath(root_path) == canonical:
            return name
    return None


def schema_probe(conn: sqlite3.Connection) -> List[str]:
    """Missing contract pieces; empty list = contract satisfied."""
    missing: List[str] = []
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
    except sqlite3.Error as exc:
        return [f"schema unreadable: {exc}"]
    for table in REQUIRED_TABLES:
        if table not in tables:
            missing.append(f"table:{table}")
    for table, columns in REQUIRED_COLUMNS.items():
        if table not in tables:
            continue
        try:
            present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            present = set()
        for col in columns:
            if col not in present:
                missing.append(f"column:{table}.{col}")
    return missing


def snapshot_token(conn: sqlite3.Connection) -> Dict[str, Any]:
    """(db_uid, mutation_gen) — generation token for receipt binding.

    CBM node ids are AUTOINCREMENT and regenerate every index run, so an
    id is only meaningful inside its generation; consumers must bind this
    pair instead of trusting bare ids across runs.
    """
    out: Dict[str, Any] = {"db_uid": None, "mutation_gen": None}
    try:
        for key, value in conn.execute(
            "SELECT k, v FROM store_meta WHERE k IN ('db_uid','mutation_gen')"
        ):
            if key in out:
                out[key] = value
    except sqlite3.Error:
        pass
    return out


@dataclass(frozen=True)
class CbmIndexResult:
    status: str                     # "indexed" | "spawn_failed" | "error" | "timeout"
    project: Optional[str]
    nodes: int
    edges: int
    skipped: List[str]
    parse_partial: List[str]
    not_indexed: int
    detail: str
    duration_ms: int


def run_index(
    command: Sequence[str],
    root: str,
    *,
    mode: str = "full",
    timeout_s: Optional[float] = None,
) -> CbmIndexResult:
    """Spawn ``<command> cli --json index_repository`` in the isolated env.

    Write path only. Parses the single MCP envelope on stdout; native
    stderr is never propagated (same redaction posture as the provider
    adapter) — failures report a generic detail + stderr tail classification.
    """
    import time

    timeout = timeout_s if timeout_s is not None else _DEFAULT_INDEX_TIMEOUT_S
    args = {"repo_path": os.path.realpath(root), "mode": mode}
    started = time.monotonic()
    args_file: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="sot-cbm-index-",
            delete=False, encoding="utf-8",
        ) as handle:
            json.dump(args, handle)
            args_file = handle.name
        argv = [*command, "cli", "--json", "index_repository",
                "--args-file", args_file]
        result = run_command(
            list(argv), cwd=os.path.realpath(root),
            timeout_seconds=timeout,
            env_extra=cbm_env(root),
        )
    except OSError as exc:
        return CbmIndexResult("spawn_failed", None, 0, 0, [], [], 0,
                              str(exc), int((time.monotonic() - started) * 1000))
    finally:
        if args_file and os.path.exists(args_file):
            try:
                os.unlink(args_file)
            except OSError:
                pass
    duration_ms = int((time.monotonic() - started) * 1000)

    envelope: Optional[Dict[str, Any]] = None
    try:
        envelope = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError, AttributeError):
        pass
    structured = (envelope or {}).get("structuredContent") or {}
    status = structured.get("status")
    if result.returncode != 0 or not status:
        timed_out = getattr(result, "timed_out", False)
        return CbmIndexResult(
            "timeout" if timed_out else "error",
            structured.get("project"),
            int(structured.get("nodes") or 0), int(structured.get("edges") or 0),
            [], [], 0,
            ("index_repository timed out" if timed_out
             else "index_repository failed; native diagnostic withheld"),
            duration_ms,
        )
    coverage = structured.get("parse_partial") or {}
    partial_files = [
        f.get("path") for f in (coverage.get("files") or []) if f.get("path")
    ]
    skipped = structured.get("skipped") or {}
    skipped_files = [
        f.get("path") for f in (skipped.get("files") or []) if f.get("path")
    ]
    return CbmIndexResult(
        "indexed", structured.get("project"),
        int(structured.get("nodes") or 0), int(structured.get("edges") or 0),
        skipped_files, partial_files,
        int(structured.get("not_indexed_files_count") or 0),
        status, duration_ms,
    )


def coverage_gaps(conn: sqlite3.Connection, project: str) -> Tuple[List[str], List[str]]:
    """(skipped, parse_partial) rel_paths the engine did not fully index.

    File-level kinds only: ``skipped``/``not_indexed_file`` mean the engine
    saw the file but did not index it; ``not_indexed_dir`` rows are
    directory-level and their member files are already absent from
    ``file_hashes`` (the gap-fill diff catches them without expansion).
    """
    try:
        rows = conn.execute(
            "SELECT rel_path, kind FROM index_coverage WHERE project = ?",
            (project,),
        ).fetchall()
    except sqlite3.Error:
        return [], []
    skipped = [p for p, k in rows if k in ("skipped", "not_indexed_file")]
    partial = [p for p, k in rows if k == "parse_partial"]
    return skipped, partial


def covered_paths(conn: sqlite3.Connection, project: str) -> set:
    """Rel-paths the engine indexes for ``project`` (file_hashes set)."""
    try:
        return {
            r[0] for r in conn.execute(
                "SELECT rel_path FROM file_hashes WHERE project = ?",
                (project,),
            )
        }
    except sqlite3.Error:
        return set()


def reconcile_dispatch(
    db: Any,
    reconciler: Any,
    root: str,
    *,
    extractor: str = "auto",
    cbm_mode: str = "full",
    cbm_command: Optional[Sequence[str]] = None,
    workers: Optional[int] = None,
    batch_size: int = 64,
    force: bool = False,
    timeout_s: Optional[float] = None,
) -> Dict[str, Any]:
    """One funnel for every reconcile path: CBM-primary, builtin fallback.

    CBM branch: ``index_repository`` re-indexes the repo (self-incremental
    via its own file_hashes); then the builtin reconciler fills every
    scan-set path the engine does NOT cover and purges sot-side rows whose
    path is now CBM-covered or vanished (ownership transfer — a path's
    rows come from exactly one provider). Any failure degrades to the
    plain builtin reconcile with an honest ``extractor_fallback`` reason —
    never a silent pretend-CBM run.
    """
    import time as _time

    def _builtin(reason: Optional[str]) -> Dict[str, Any]:
        summary = reconciler.reconcile(
            workers=workers, batch_size=batch_size, force=force)
        out = summary.as_dict()
        out["extractor"] = "tree-sitter-ast"
        if reason:
            out["extractor_fallback"] = reason
        return out

    if extractor == "builtin":
        return _builtin(None)

    from sot_graph.config import load_config

    cfg = load_config(root)
    pcfg = cfg.providers.get("codebase-memory")
    command = list(cbm_command or (pcfg.command if pcfg else []) or [])
    if pcfg is not None and pcfg.enabled is False:
        return _builtin("cbm_disabled")
    if not command:
        return _builtin("cbm_unavailable")

    started = _time.monotonic()
    result = run_index(command, root, mode=cbm_mode, timeout_s=timeout_s)
    if result.status != "indexed":
        return _builtin(f"cbm_index_failed:{result.status}")

    # Ownership transfer + gap fill, keyed off the engine's own coverage.
    gap_published = 0
    deferred = 0
    purged = 0
    partial_count = 0
    cbm_db_path = find_cbm_db(root)
    covered: set = set()
    if cbm_db_path:
        conn = _open_ro(cbm_db_path)
        try:
            project = locate_project(conn, root) or result.project or ""
            covered = covered_paths(conn, project)
            skipped, partial = coverage_gaps(conn, project)
            partial_count = len(partial)
        finally:
            conn.close()
    covered_abs = {
        os.path.realpath(os.path.join(root, rel)) for rel in covered
    }

    scan = reconciler.scan()
    gap_paths = [
        p for p in scan
        if os.path.realpath(p) not in covered_abs
    ]
    if gap_paths:
        published, deferred_set = reconciler.reconcile_paths(gap_paths)
        gap_published = published
        deferred = len(deferred_set)

    # Purge sot-owned rows whose path is now CBM-covered or vanished:
    # prevents zombie nodes/journal resurfacing through the union views.
    for sot_path in list(db.all_journal_paths()):
        real = sot_path
        if not os.path.isabs(real):
            real = os.path.join(root, real)
        real = os.path.realpath(real)
        if real in covered_abs or not os.path.exists(real):
            try:
                db.delete_path(sot_path)
                purged += 1
            except Exception:
                pass

    return {
        "extractor": "codebase-memory",
        "cbm_mode": cbm_mode,
        "cbm_nodes": result.nodes,
        "cbm_edges": result.edges,
        "cbm_duration_ms": result.duration_ms,
        "gap_fill_published": gap_published,
        "gap_fill_deferred": deferred,
        "ownership_purged": purged,
        "parse_partial_files": partial_count,
        "scanned": len(scan),
        "updated": gap_published,
        "unchanged": len(scan) - len(gap_paths),
        "deleted": purged,
        "failed": deferred,
        "conflicts": 0,
        "duration_ms": int((_time.monotonic() - started) * 1000),
    }
