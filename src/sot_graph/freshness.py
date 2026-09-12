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

import json
import os
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional

_SAMPLE_CAP = 10
_MODES = ("auto", "force", "off")

#: Background-reconcile debounce lock (``jit_mode=async``): a fresh lock
#: held by a live pid means a reconcile is already running — later stale
#: probes serve the current snapshot instead of stacking spawns.
_BG_LOCK_REL = os.path.join(".sot", "reconcile-bg.lock")
_BG_LOG_REL = os.path.join(".sot", "reconcile-bg.log")
_BG_LOCK_TTL_S = 180.0
_BG_LOG_MAX_BYTES = 1_000_000


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
    from sot_graph.graphstore import open_store
    from sot_graph.reconciler import Reconciler

    started = time.perf_counter()
    modified: List[str] = []
    deleted: List[str] = []
    journal_keys = set()
    checked = 0

    # open_store probes the extractor contract: when a bound CBM store is
    # present the journal view includes the engine's file_hashes, so the
    # same probe covers whichever extractor produced the index.
    db = open_store(root, db_path, read_only=True)
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
) -> Dict[str, Any]:
    """Run one reconcile through the normal writer path; raises on failure."""
    from sot_graph.cbm import reconcile_dispatch
    from sot_graph.config import load_config
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler

    # A CbmStore cannot serve as the reconcile writer: graph-shape writes
    # belong to the engine, journal/gap-fill writes to sot.db — always open
    # the plain writer for this path.
    if writer is not None and getattr(writer, "is_cbm", False):
        writer = None
    own = writer is None
    db = Database(db_path) if own else writer
    try:
        cfg = load_config(root)
        return reconcile_dispatch(
            db, Reconciler(db, root), root,
            extractor=cfg.extractor, cbm_mode=cfg.cbm_mode,
            workers=workers,
        )
    finally:
        if own:
            db.close()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        # PermissionError: exists but not ours. Other OSError (e.g.
        # Windows, where sig=0 probing is unsupported): assume alive —
        # the lock TTL bounds the debounce either way.
        return True
    return True


def spawn_background_reconcile(root: str) -> bool:
    """Spawn a detached ``sotgraph reconcile`` behind a pid-lock debounce.

    Returns True when a new process launched; False when a live lock
    holder is already reconciling or the spawn failed. Best-effort — the
    caller serves the current index snapshot either way, so this never
    raises.
    """
    lock_path = os.path.join(root, _BG_LOCK_REL)
    now = time.time()
    try:
        with open(lock_path, "r", encoding="utf-8") as fh:
            holder = json.load(fh)
        pid = int(holder.get("pid") or 0)
        started = float(holder.get("started") or 0)
        if pid > 0 and 0 <= now - started < _BG_LOCK_TTL_S and _pid_alive(pid):
            return False
    except (OSError, ValueError):
        pass

    log_path = os.path.join(root, _BG_LOG_REL)
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        # Bounded log: truncate rather than append once it grows past cap.
        log_mode = "ab" if (
            os.path.exists(log_path)
            and os.path.getsize(log_path) <= _BG_LOG_MAX_BYTES
        ) else "wb"
        log = open(log_path, log_mode)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "sot_graph", "reconcile", "--json"],
                cwd=root, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        tmp = lock_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"pid": proc.pid, "started": now}, fh)
        os.replace(tmp, lock_path)
        return True
    except OSError:
        return False


def ensure_fresh(
    db_path: str,
    root: str,
    mode: Any = "auto",
    *,
    writer: Optional[Any] = None,
    blocking: Optional[bool] = None,
    spawn_fn: Optional[Callable[[str], bool]] = None,
) -> Dict[str, Any]:
    """Staleness-gated JIT reconcile; returns an honest envelope, never raises.

    Modes: ``auto`` (default — probe, reconcile only when stale),
    ``force`` (always reconcile), ``off`` (skip entirely). ``writer``
    lets a caller that already holds a writable Database reuse it for
    the reconcile instead of opening a second connection.

    ``blocking`` selects inline vs background reconcile for ``auto``
    mode (``force`` is always inline — an explicit reconcile request
    must not return before it ran). ``None`` resolves the config's
    ``jit_mode``: ``async`` answers from the current snapshot and spawns
    a detached reconcile behind a pid-lock debounce, disclosing
    ``serving: "stale"``; ``blocking`` keeps the inline behavior.
    ``spawn_fn`` is injectable for tests.
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

    if blocking is None:
        if normalized == "force":
            blocking = True
        else:
            try:
                from sot_graph.config import load_config
                blocking = load_config(root).jit_mode != "async"
            except Exception:  # config error: correctness-first
                blocking = True
    envelope["jit"] = "blocking" if blocking else "async"
    if not blocking:
        spawn = spawn_fn or spawn_background_reconcile
        spawned = False
        try:
            spawned = bool(spawn(root))
        except Exception:  # spawn failure: disclose, still serve stale
            spawned = False
        envelope["reconcile"] = {
            "performed": True,
            "status": "background",
            "spawned": spawned,
            "serving": "stale",
            "stale_total": sum(
                probe[k]["count"]
                for k in ("modified", "deleted", "unindexed")
            ),
        }
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
