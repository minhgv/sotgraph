"""sot_graph.assurance.engine - shared query-assurance engine (P2, P0).

CLI and MCP both call :func:`assured_query_context` before returning
graph-derived answers, so snapshot capture and stale-evidence detection can
never drift between surfaces.
"""

from __future__ import annotations

import sys
from typing import Iterable, Optional, Tuple

__all__ = [
    "resolve_symbol",
    "resolve_symbol_identity",
    "assured_query_context",
    "stale_files_warning",
]


def resolve_symbol(db, query: str):
    """Resolve a query to one node row: ``(id, label, kind, path, line, symbol)``.

    Prefers exact symbol matches over file/doc nodes whose labels merely
    mention the query text.
    """
    row = db.conn.execute(
        "SELECT id, label, kind, path, line_start, symbol FROM graph_nodes "
        "WHERE symbol = ? LIMIT 1", (query,)
    ).fetchone()
    if not row:
        row = db.conn.execute(
            "SELECT id, label, kind, path, line_start, symbol FROM graph_nodes "
            "WHERE kind != 'file' AND (label LIKE ? OR fqn LIKE ?) "
            "ORDER BY kind LIMIT 1", (f"%{query}%", f"%{query}%")
        ).fetchone()
    return row


def _scoped_identity_candidates(db, query: str) -> Optional[Tuple[list, str]]:
    """Decision candidates for an explicit ``path::name`` scoped target.

    Returns ``None`` when the query is not a scoped locator (callers fall
    through to the literal exact-match ladder). Scoped targets resolve by
    exact-match decision semantics — no LIKE on the name, no ``LIMIT 1``:

    1. path-scoped exact: ``symbol = name OR fqn = name`` within the path;
    2. path-scoped FQN suffix for class-qualified names
       (``path::Cls.method``): stored method symbols are unqualified while
       the class lives in the dotted FQN tail, so a path-narrowed literal
       ends-with ``.<name>`` comparison is the exact structural match.
       Like the exact steps it is case-sensitive (``substr``); the name is
       taken literally — no wildcard, no casefold.

    A node whose stored name merely EQUALS the locator text (e.g. a data
    key in a JSON fixture) is never consulted: for scoped queries the
    scope interpretation is the whole contract.
    """
    if "::" not in query:
        return None
    # Lazy: pack is a heavy leaf module; importing here keeps the
    # assurance package importable without it (same pattern as receipts).
    from sot_graph.pack import _parse_target, _path_scope_sql

    parsed = _parse_target(query)
    if not (parsed.rewritten and parsed.path and parsed.symbol):
        return None
    scope_sql, scope_params = _path_scope_sql(parsed.path)
    name = parsed.symbol
    base = (
        "SELECT id, label, kind, path, line_start, symbol, fqn "
        "FROM graph_nodes WHERE kind != 'file'"
    )
    # Fail-closed contract: the method label is decided BEFORE the first
    # query, so a broken graph (first execute throws) still returns a
    # meaningful empty decision instead of an UnboundLocalError.
    method = "path_scoped_exact"
    try:
        rows = db.conn.execute(
            base + " AND (symbol = ? OR fqn = ?)" + scope_sql,
            (name, name, *scope_params),
        ).fetchall()
        if not rows and "." in name:
            # Class-qualified suffix: literal ends-with `.<name>`, compared
            # case-sensitively like the exact steps — a sole differently
            # cased sibling ('Cls.run_Tests' for '::Cls.run_tests') is
            # never selected, and the name carries no wildcard meaning.
            tail = f".{name}"
            rows = db.conn.execute(
                base + " AND length(fqn) > ? AND substr(fqn, ?) = ?"
                + scope_sql,
                (len(tail), -len(tail), tail, *scope_params),
            ).fetchall()
            method = "path_scoped_suffix"
    except Exception:  # noqa: BLE001 - a broken graph resolves to NOT_FOUND
        return ([], method)
    return rows, method


def resolve_symbol_identity(db, query: str) -> dict:
    """Resolve a query to a DECISION identity (P0 Contract 3).

    Exact match only: ``symbol == query`` OR ``fqn == query``. No LIKE,
    no ``LIMIT 1`` - ambiguity is surfaced, never buried.

    Explicit ``path::name`` / ``path::Class.method`` scoped targets are
    decided by :func:`_scoped_identity_candidates` FIRST — the path half
    constrains selection, and the literal whole-string exact match is not
    consulted at all (a symbol elsewhere that merely equals the locator
    text is not the requested target). Scoped ambiguity fails closed with
    candidates.

    Returns ``{"status": "UNIQUE"|"AMBIGUOUS"|"NOT_FOUND",
    "candidates": [row-dict...], "selected": row-dict|None}``. Receipt
    decision paths use this; navigation callers keep :func:`resolve_symbol`.
    """
    columns = ("id", "label", "kind", "path", "line_start", "symbol", "fqn")
    scoped = _scoped_identity_candidates(db, query)
    if scoped is not None:
        rows, scoped_method = scoped
        candidates = [dict(zip(columns, r)) for r in rows]
        disclosure = {"query": query, "method": scoped_method}
        if not candidates:
            return {
                "status": "NOT_FOUND",
                "candidates": [],
                "selected": None,
                "scoped_resolution": disclosure,
            }
        if len(candidates) > 1:
            return {
                "status": "AMBIGUOUS",
                "candidates": candidates,
                "selected": None,
                "scoped_resolution": disclosure,
            }
        return {
            "status": "UNIQUE",
            "candidates": candidates,
            "selected": candidates[0],
            "scoped_resolution": disclosure,
        }
    try:
        rows = db.conn.execute(
            "SELECT id, label, kind, path, line_start, symbol, fqn "
            "FROM graph_nodes WHERE symbol = ? OR fqn = ?",
            (query, query),
        ).fetchall()
    except Exception:  # noqa: BLE001 - a broken graph resolves to NOT_FOUND
        rows = []
    candidates = [dict(zip(columns, r)) for r in rows]
    if not candidates:
        return {"status": "NOT_FOUND", "candidates": [], "selected": None}
    if len(candidates) > 1:
        return {
            "status": "AMBIGUOUS",
            "candidates": candidates,
            "selected": None,
        }
    return {
        "status": "UNIQUE",
        "candidates": candidates,
        "selected": candidates[0],
    }


def assured_query_context(
    db, root: str, cited_paths: Iterable[str] = (), *,
    mark_ledger: bool = True,
) -> Tuple[dict, list]:
    """P1.b/P1.c/P1.e shared pre-query assurance for builtin read paths.

    Captures the common worktree snapshot descriptor (HEAD sha, tri-state
    dirty flag, dirty fingerprint — read-only, no ledger write on a read
    path) and validates every cited file against the file journal. Stale
    files are MARKED in the evidence ledger (never deleted) so the ledger
    can distinguish pre-change from post-change evidence.

    ``cited_paths`` also feed the P0 content binding (Contract 2): each
    path is hashed into the snapshot's ``scope_digest`` so a receipt can
    prove WHICH file content it was captured against.

    ``mark_ledger=False`` is for read-only connections (MCP ``mode=ro``):
    staleness is still detected and reported, the ledger is not written.
    """
    from sot_graph.snapshot import capture_worktree_snapshot

    unique = sorted({str(p) for p in cited_paths if p})
    snapshot = capture_worktree_snapshot(root, cited_paths=unique or None)
    stale = db.stale_journal_files(unique, root=root) if unique else []
    if stale and mark_ledger:
        try:
            marked = db.mark_evidence_stale(
                stale, reason="journal mismatch: file changed since last reconcile"
            )
            if marked:
                print(
                    f"  ⚠ Marked {marked} evidence row(s) stale "
                    f"({len(stale)} file(s) changed since last reconcile)",
                    file=sys.stderr,
                )
        except Exception as exc:  # pragma: no cover - ledger marking is best-effort
            print(f"  ⚠ Evidence invalidation failed: {exc}", file=sys.stderr)
    return snapshot.as_dict(), stale


def stale_files_warning(stale: list) -> Optional[str]:
    if not stale:
        return None
    shown = ", ".join(stale[:5]) + ("…" if len(stale) > 5 else "")
    return (
        f"{len(stale)} cited file(s) changed since last reconcile ({shown}); "
        "run 'sotgraph reconcile' — evidence for these paths is UNVERIFIABLE until then"
    )
