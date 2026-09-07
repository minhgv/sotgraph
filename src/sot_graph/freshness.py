"""Staleness-gated JIT reconcile for query surfaces (MCP tools + CLI).

Before a query runs, cheaply detect whether the graph index is stale
against the filesystem; when it is, reconcile through the normal writer
path first, then let the query proceed. Design rules mirror the assurance
philosophy:

- the gate NEVER raises: a failed reconcile degrades to answering from
  the stale graph with honest disclosure instead of blocking the query;
- the probe is stat-based (size + mtime_ms vs ``file_journal``) plus one
  reconciler-semantics walk for never-indexed files, so the fresh common
  case costs no hashing;
- sample lists are capped; full counts always ride along.

Known detection limits (deliberate trade-offs):

- content changed while size AND mtime were restored (mtime-preserving
  tools, `git checkout` of same-size content) is invisible to the probe
  until the next explicit reconcile — the hash-based assurance layer
  still catches cited-path staleness after the query;
- files unsupported by the reconciler (EXT_DISPATCH / TEXT_EXTENSIONS)
  are never indexed, hence never "stale";
- a file changed between probe and query (TOCTOU) is disclosed by the
  post-query assurance snapshot, not prevented here.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

_SAMPLE_CAP = 10
_MODES = ("auto", "force", "off")


def normalize_mode(value: Any, default: str = "auto") -> str:
    """Map tri-state input (True/False/"auto"/"force"/"off") to a mode."""
    if value is True:
        return "force"
    if value is False:
        return "off"
    if isinstance(value, str) and value.strip().lower() in _MODES:
        return value.strip().lower()
    return default


def _cap(items: List[str]) -> Dict[str, Any]:
    return {"count": len(items), "sample": items[:_SAMPLE_CAP]}


def staleness_probe(db_path: str, root: str) -> Dict[str, Any]:
    """Cheap stat-based staleness check of the index against the disk.

    Returns counts + capped samples for ``modified`` (journal row
    disagrees on size/mtime), ``deleted`` (journal row, file gone), and
    ``unindexed`` (supported file on disk with no journal row — invisible
    to journal-only checks). ``stale`` is the OR of the three counts.
    """
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler

    started = time.perf_counter()
    modified: List[str] = []
    deleted: List[str] = []
    journal_keys = set()
    checked = 0

    db = Database(db_path, read_only=True)
    try:
        reconciler = Reconciler(db, root)
        # The scan set defines what reconcile CAN re-examine. Journal rows
        # outside it (file now ignored or unsupported) are lifecycle debt
        # for `sotgraph clean`, not query-time staleness: flagging them
        # here would make every query reconcile with nothing to heal.
        scan = reconciler.scan()
        scan_set = {os.path.realpath(p) for p in scan}

        def _display(path: str) -> str:
            try:
                return os.path.relpath(path, root).replace(os.sep, "/")
            except ValueError:
                return path

        for path, row in db.get_all_file_journals().items():
            checked += 1
            raw = str(path)
            rel = raw.replace("\\", "/").strip("/")
            journal_keys.add(rel)
            if os.path.isabs(raw):
                try:
                    journal_keys.add(
                        os.path.relpath(raw, root).replace(os.sep, "/"))
                except ValueError:
                    pass
            full = raw if os.path.isabs(raw) else os.path.join(root, rel)
            try:
                real = os.path.realpath(full)
            except OSError:
                real = full
            if real not in scan_set:
                # Outside reconcile's reach now (ignored/unsupported): a
                # still-existing file is lifecycle debt for `sotgraph
                # clean`, not query-time staleness. A vanished file that
                # is NOT ignored is a deletion reconcile should purge.
                if (not os.path.exists(full)
                        and not reconciler.ignore_matcher.is_ignored(full, is_dir=False)):
                    deleted.append(_display(full))
                continue
            try:
                stat = os.stat(full)
            except OSError:
                deleted.append(_display(full))
                continue
            # NOT NULL columns; `or` defaults would turn size 0 into -1.
            if (int(stat.st_size) != int(row["size"])
                    or int(stat.st_mtime * 1000) != int(row["mtime_ms"])):
                modified.append(_display(full))
    finally:
        db.close()

    unindexed: List[str] = []
    for full in scan:
        rel = _display(full)
        if rel not in journal_keys:
            unindexed.append(rel)

    return {
        "modified": _cap(modified),
        "deleted": _cap(deleted),
        "unindexed": _cap(unindexed),
        "checked": checked,
        "stale": bool(modified or deleted or unindexed),
        "probe_ms": int((time.perf_counter() - started) * 1000),
    }


def reconcile_now(
    db_path: str, root: str, *, writer: Optional[Any] = None,
    workers: Optional[int] = None,
) -> Dict[str, int]:
    """Run one reconcile through the normal writer path; raises on failure."""
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler

    own = writer is None
    db = Database(db_path) if own else writer
    try:
        if workers is None:
            return Reconciler(db, root).reconcile().as_dict()
        return Reconciler(db, root).reconcile(workers=workers).as_dict()
    finally:
        if own:
            db.close()


def ensure_fresh(
    db_path: str,
    root: str,
    mode: Any = "auto",
    *,
    writer: Optional[Any] = None,
) -> Dict[str, Any]:
    """Staleness-gated JIT reconcile; returns an honest envelope, never raises.

    Modes: ``auto`` (default — probe, reconcile only when stale),
    ``force`` (always reconcile), ``off`` (skip entirely). ``writer``
    lets a caller that already holds a writable Database reuse it for
    the reconcile instead of opening a second connection.
    """
    normalized = normalize_mode(mode)
    envelope: Dict[str, Any] = {"mode": normalized}
    if normalized == "off":
        envelope["reconcile"] = {"performed": False, "status": "off"}
        return envelope
    try:
        probe = staleness_probe(db_path, root)
    except Exception as exc:  # probe failure: disclose, never block
        envelope["probe"] = {"status": "failed", "error": str(exc)[:200]}
        envelope["reconcile"] = {"performed": False, "status": "probe_failed"}
        return envelope
    envelope["probe"] = probe
    if normalized == "auto" and not probe["stale"]:
        envelope["reconcile"] = {"performed": False, "status": "skipped_fresh"}
        return envelope

    started = time.perf_counter()
    try:
        # Small deltas (the JIT norm: 1-5 files) parse faster single-threaded
        # and avoid multiprocessing spawn overhead/edge cases; only a large
        # backlog pays for workers.
        stale_total = sum(probe[k]["count"] for k in ("modified", "deleted", "unindexed"))
        summary = reconcile_now(
            db_path, root, writer=writer,
            workers=1 if stale_total <= 16 else None,
        )
        status = (
            "failed" if summary.get("failed")
            else "conflicts" if summary.get("conflicts")
            else "success"
        )
        envelope["reconcile"] = {
            "performed": True,
            "status": status,
            "duration_ms": summary.get("duration_ms"),
            "updated": summary.get("updated"),
            "deleted": summary.get("deleted"),
            "failed": summary.get("failed"),
            "conflicts": summary.get("conflicts"),
        }
    except Exception as exc:  # reconcile failure: answer stale, disclose
        envelope["reconcile"] = {
            "performed": False,
            "status": "failed",
            "error": str(exc)[:200],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    return envelope
