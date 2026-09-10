"""P7.3 resolution ledger collectors — "what is left unresolved?".

The P7.2 diff receipt answers "what was affected". These three
read-only collectors extend it toward "what is left unresolved":

- :func:`disposition_matrix` — joins a PRE-change scope receipt's
  predicted blast radius (direct callers, candidate tests) against the
  POST-change diff's changed files. ``addressed`` = the predicted file
  was touched by the diff; ``untouched`` = predicted impact the change
  never reached. Advisory: the pre-receipt prediction is heuristic, so
  untouched items are reported in ``remaining_gaps`` but do NOT degrade
  the assurance decision.
- :func:`dangling_references` — ``pending_edges`` rows left
  UNRESOLVED/AMBIGUOUS after the extractor's resolution pass, scoped to
  the change: rows FROM the changed files and their callers, plus rows
  pointing at PRE-change symbols that no longer exist as nodes (the
  rename/delete leftover signal). Decision-grade: the count feeds
  ``AssuranceFacts.unresolved_count`` and blocks closure.
- :func:`debt_markers` — TODO/FIXME/HACK/XXX/type-ignore/noqa/bare-
  except introduced on ADDED lines of the diff. Declared debt:
  informational, never decision-degrading.

Blind spots (disclosed, never hidden): debt markers are scanned from
the unified-diff text only — untracked files (which git diff does not
emit) are not scanned; dangling references outside the changed/caller
files and outside the pre-receipt symbol set are not collected — the
receipt's claim profile stays ``scoped``, never repo-wide absence.

Accounting (SG-107): the two SQL queries here are LIMIT-free — each is
a decision input, not a truncating collection (same precedent as
``pack._recover_identity``). The only cap is the debt-marker REPORT
list (:data:`DEBT_MARKER_REPORT_CAP`), registered as
``DEBT_MARKERS_SOURCE``.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.assurance.accounting import DEBT_MARKER_REPORT_CAP

#: (kind label, pattern) pairs for declared-debt markers. ``bare_except``
#: is anchored to line start because the added-line snippet keeps the
#: original indentation; the rest match anywhere on the line.
_MARKER_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("todo", re.compile(r"\bTODO\b")),
    ("fixme", re.compile(r"\bFIXME\b")),
    ("hack", re.compile(r"\bHACK\b")),
    ("xxx", re.compile(r"\bXXX\b")),
    ("type_ignore", re.compile(r"#\s*type:\s*ignore")),
    ("noqa", re.compile(r"#\s*noqa\b")),
    ("bare_except", re.compile(r"^\s*except\s*:")),
)

_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@"
)

_NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")


def _norm_path(path: Any) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")


def _touched(path: Any, changed_norm: frozenset) -> bool:
    """True when ``path`` (possibly absolute) matches a changed file.

    The engine reports changed files repo-relative while graph rows
    store absolute paths, so the match is exact-or-suffix on the
    normalized form (``/repo/src/app.py`` ends with ``/src/app.py``).
    """
    p = _norm_path(path)
    if not p:
        return False
    if p in changed_norm:
        return True
    return any(p == c or p.endswith("/" + c) for c in changed_norm)


def disposition_matrix(
    pre_receipt: Optional[Dict[str, Any]],
    changed_files: List[str],
) -> Dict[str, Any]:
    """Classify the PRE-change prediction against the POST-change diff.

    Pure function (no I/O). Returns per-family totals plus the
    ``untouched`` lists — the "predicted impact the change never
    reached" debt. With no pre-receipt attached, families are empty and
    ``pre_receipt_attached`` is False so consumers never mistake an
    unmeasured disposition for a clean one.
    """
    callers = list((pre_receipt or {}).get("direct_callers") or [])
    tests = list((pre_receipt or {}).get("candidate_tests") or [])
    changed_norm = frozenset(_norm_path(p) for p in changed_files if p)

    def _classify(items: List[Any], path_key: str = "path") -> Dict[str, Any]:
        entries: List[Dict[str, Any]] = []
        for item in items:
            path = item.get(path_key) if isinstance(item, dict) else item
            entry: Dict[str, Any] = {"path": str(path or "")}
            if isinstance(item, dict):
                for key in ("symbol", "fqn", "relation"):
                    if item.get(key):
                        entry[key] = item[key]
            entry["disposition"] = (
                "addressed" if _touched(path, changed_norm) else "untouched"
            )
            entries.append(entry)
        untouched = [e for e in entries if e["disposition"] == "untouched"]
        return {
            "total": len(entries),
            "addressed": len(entries) - len(untouched),
            "untouched": untouched,
        }

    return {
        "pre_receipt_attached": pre_receipt is not None,
        "direct_callers": _classify(callers),
        "candidate_tests": _classify(tests),
    }


def _pending_paths_where(
    paths: List[str], repo_root: str = "",
) -> Tuple[str, List[str]]:
    """Build a path IN clause matching BOTH repo-relative and absolute.

    ``pending_edges.path`` follows the extractor's storage convention;
    matching both forms keeps the sweep correct regardless of which side
    normalized. Duplicate-safe: IN semantics.
    """
    forms: List[str] = []
    seen = set()
    root = _norm_path(repo_root)
    for p in paths:
        np = _norm_path(p)
        candidates = [np]
        if root and not np.startswith("/"):
            candidates.append(f"{root}/{np}")
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                forms.append(candidate)
    if not forms:
        return "", []
    marks = ",".join("?" * len(forms))
    return f"path IN ({marks})", forms


def _node_symbol_exists(db: Any, symbol: str) -> bool:
    """True when ANY node carries this bare symbol. EXISTS short-circuits
    (no LIMIT token — the SG-107 AST sweep sees none)."""
    try:
        row = db.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM graph_nodes WHERE symbol = ?)",
            (symbol,),
        ).fetchone()
    except Exception:  # noqa: BLE001 - broken graph reads as "gone"
        return False
    return bool(row and row[0])


def dangling_references(
    db: Any,
    changed_files: List[str],
    caller_files: List[str] = (),
    pre_receipt: Optional[Dict[str, Any]] = None,
    repo_root: str = "",
    errors_out: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Collect references the change left unresolved, scoped to the diff.

    Three slices, merged per row with a ``scopes`` list:

    - ``changed_or_caller_files`` — ``pending_edges`` rows left
      UNRESOLVED/AMBIGUOUS whose source file is one of the diff's cited
      files or the callers of changed nodes: NEW unresolved references
      the change itself introduced.
    - ``removed_pre_change_symbols`` — only with a pre-receipt, two nets:

      * pending rows whose ``dst_symbol`` was a known PRE-change
        identity that no longer exists as a node (dotted aliases like
        ``util.help`` match bare ``help``), and
      * PRE-change direct callers of the SELECTED symbol when that
        symbol has VANISHED and the caller's file was NOT touched by
        the diff — the rename/delete leftover. This net is needed
        because reconcile deletes the old graph edge with the removed
        node, so the leftover caller never re-parks as a pending row.

    All queries carry no LIMIT: this is a DECISION collection (the count
    feeds ``unresolved_count``), not a truncating one — a cap here would
    let a cut read as "no danglers left" (SG-107 precedent). DB failures
    degrade to an empty result plus a collection error.
    """
    out: Dict[str, Any] = {
        "changed_or_caller_files": [],
        "removed_pre_change_symbols": [],
        "count": 0,
    }
    merged: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    repo_root_abs = os.path.realpath(repo_root) if repo_root else ""
    changed_norm = frozenset(_norm_path(p) for p in changed_files if p)

    def _absorb(
        path: Any, src: Any, dst: Any, relation: Any, line: Any,
        state: Any, scope: str,
    ) -> None:
        key = (str(path), str(src), str(dst), str(relation))
        entry = merged.get(key)
        if entry is None:
            entry = {
                "path": str(path),
                "src": str(src),
                "dst_symbol": str(dst),
                "relation": str(relation or ""),
                "line": line,
                "state": str(state or ""),
                "scopes": [],
            }
            merged[key] = entry
        if scope not in entry["scopes"]:
            entry["scopes"].append(scope)

    try:
        scope_paths = [
            p for p in (*changed_files, *caller_files) if p
        ]
        where, params = _pending_paths_where(scope_paths, repo_root_abs)
        if where:
            rows = db.conn.execute(
                "SELECT path, src, dst_symbol, relation, line, "
                "resolution_state FROM pending_edges "
                "WHERE resolution_state IN ('UNRESOLVED','AMBIGUOUS') "
                f"AND {where}",
                params,
            ).fetchall()
            for path, src, dst, relation, line, state in rows:
                _absorb(path, src, dst, relation, line, state,
                        "changed_or_caller_file")
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        if errors_out is not None:
            errors_out.append(f"collection_error:pending_edges:{exc}")

    if pre_receipt:
        pre_symbols: List[str] = []
        identity = pre_receipt.get("identity") or {}
        selected = identity.get("selected") or {}
        if selected.get("symbol"):
            pre_symbols.append(str(selected["symbol"]))
        for family in ("direct_callers", "direct_callees"):
            for item in pre_receipt.get(family) or []:
                sym = (item or {}).get("symbol")
                if sym and str(sym) not in pre_symbols:
                    pre_symbols.append(str(sym))
        if pre_symbols:
            try:
                marks = ",".join("?" * len(pre_symbols))
                dotted = ["%." + s for s in pre_symbols]
                dotted_clauses = " OR ".join(
                    "p.dst_symbol LIKE ?" for _ in dotted)
                # No LIMIT — decision collection (see docstring). The NOT
                # EXISTS keeps the slice to symbols that VANISHED; the
                # dotted LIKE catches qualified references (util.help)
                # pointing at a vanished bare symbol (help).
                rows = db.conn.execute(
                    "SELECT p.path, p.src, p.dst_symbol, p.relation, "
                    "p.line, p.resolution_state FROM pending_edges p "
                    "WHERE p.resolution_state IN ('UNRESOLVED','AMBIGUOUS') "
                    f"AND (p.dst_symbol IN ({marks}) "
                    f"OR {dotted_clauses}) "
                    "AND NOT EXISTS (SELECT 1 FROM graph_nodes n "
                    "WHERE n.symbol = p.dst_symbol)",
                    [*pre_symbols, *dotted],
                ).fetchall()
                for path, src, dst, relation, line, state in rows:
                    _absorb(path, src, dst, relation, line, state,
                            "removed_pre_change_symbol")
            except Exception as exc:  # noqa: BLE001 - degrade, never crash
                if errors_out is not None:
                    errors_out.append(
                        f"collection_error:pending_edges_pre_symbols:{exc}")
        # Rename/delete leftover net: PRE-change callers of the selected
        # symbol when the symbol vanished and their files were untouched
        # by the diff (the old graph edge died with the removed node, so
        # no pending row ever materializes for them).
        sel_symbol = str(selected.get("symbol") or "")
        if sel_symbol and not _node_symbol_exists(db, sel_symbol):
            for caller in pre_receipt.get("direct_callers") or []:
                path = (caller or {}).get("path")
                if _touched(path, changed_norm):
                    continue
                _absorb(
                    path, (caller or {}).get("id"),
                    sel_symbol, (caller or {}).get("relation"),
                    (caller or {}).get("line"),
                    "PRE_CHANGE_CALLER_OF_REMOVED_SYMBOL",
                    "removed_pre_change_symbol",
                )

    entries = sorted(
        merged.values(),
        key=lambda e: (e["path"], e["dst_symbol"], str(e["src"])),
    )
    out["changed_or_caller_files"] = [
        e for e in entries if "changed_or_caller_file" in e["scopes"]]
    out["removed_pre_change_symbols"] = [
        e for e in entries if "removed_pre_change_symbol" in e["scopes"]]
    out["count"] = len(entries)
    return out


def scan_added_lines_for_markers(diff_text: str) -> List[Dict[str, Any]]:
    """Pure scan of unified-diff text for debt markers on ADDED lines.

    Tracks the new-file line number via hunk headers; only ``+`` lines
    are scanned (``+++`` headers excluded). Deleted lines carrying
    markers are NOT debt introduced by this change.
    """
    hits: List[Dict[str, Any]] = []
    current_file = ""
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            match = _NEW_FILE_RE.match(raw)
            current_file = match.group(1) if match else raw[4:]
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("@@"):
            match = _HUNK_HEADER_RE.match(raw)
            new_line = int(match.group(1)) if match else new_line
            continue
        if not raw.startswith("+"):
            if raw.startswith("-"):
                continue
            new_line += 1
            continue
        line_body = raw[1:]
        kinds = [
            kind for kind, pattern in _MARKER_PATTERNS
            if pattern.search(line_body)
        ]
        if kinds:
            hits.append({
                "path": current_file,
                "line": new_line,
                "kinds": kinds,
                "snippet": line_body.strip()[:120],
            })
        new_line += 1
    return hits


def debt_markers(
    repo_root: str,
    target: str,
    *,
    staged: bool = False,
    working_tree: bool = False,
    errors_out: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Debt markers introduced on ADDED lines of the diff (P7.3).

    Reuses :class:`GitDeltaExtractor` so the target-argument ladder
    (ranges, single-rev, staged, working-tree, root-commit fallbacks)
    stays owned by ONE site; reads ``last_diff_text`` instead of a
    second parse. The enumeration is exact; only the REPORT list is
    capped (:data:`DEBT_MARKER_REPORT_CAP`) and the cut is disclosed
    via ``truncated`` + ``total`` so the receipt's SG-107 gate can name
    ``DEBT_MARKERS_SOURCE``.
    """
    from sot_graph.diff_impact import GitDeltaExtractor

    result: Dict[str, Any] = {
        "introduced": [],
        "total": 0,
        "truncated": False,
        "note": "scans unified-diff added lines only; untracked files "
        "are not scanned (git diff does not emit them)",
    }
    try:
        extractor = GitDeltaExtractor(repo_root)
        extractor.extract_diff(
            target, staged=staged, working_tree=working_tree)
        hits = scan_added_lines_for_markers(extractor.last_diff_text)
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        if errors_out is not None:
            errors_out.append(f"collection_error:debt_markers:{exc}")
        return result
    result["total"] = len(hits)
    result["truncated"] = len(hits) > DEBT_MARKER_REPORT_CAP
    result["introduced"] = hits[:DEBT_MARKER_REPORT_CAP]
    return result
