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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    paths: List[str], repo_root: str = "", repo_root_abs: str = "",
) -> Tuple[str, List[str]]:
    """Build a path IN clause matching repo-relative AND absolute forms.

    ``pending_edges.path`` follows the extractor's storage convention —
    absolute paths written under whatever root string the reconciler
    saw. Matching therefore tries the repo-relative form plus BOTH the
    raw and realpath'd roots: on symlinked checkouts (macOS ``/var`` →
    ``/private/var``) the stored path keeps the raw form while a
    realpath-only match would silently lose the whole sweep.
    Duplicate-safe: IN semantics.
    """
    forms: List[str] = []
    seen = set()
    # NB: roots must keep their leading "/" — _norm_path's lstrip("./")
    # would silently demote an absolute root to a relative one and the
    # IN clause could never match stored absolute paths.
    roots = [str(r).replace("\\", "/") for r in (repo_root, repo_root_abs)]
    for p in paths:
        np = _norm_path(p)
        candidates = [np]
        if not np.startswith("/"):
            candidates.extend(f"{r}/{np}" for r in roots if r)
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                forms.append(candidate)
    if not forms:
        return "", []
    marks = ",".join("?" * len(forms))
    # Candidates are '/'-canonical; Windows stores backslash-native paths,
    # so normalize the stored column too or the IN clause never matches
    # and the whole sweep reads as "no danglers".
    return f"replace(path, char(92), '/') IN ({marks})", forms


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
    caller_files: Sequence[str] = (),
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
    repo_root_raw = _norm_path(repo_root) if repo_root else ""
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
        where, params = _pending_paths_where(
            scope_paths, repo_root_raw, repo_root_abs)
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


# ---------------------------------------------------------------------------
# W6 — semantic_breaks: signature/contract changes with surviving callers.
# ---------------------------------------------------------------------------


def _git_show(repo_root: str, ref: str, path: str) -> Optional[str]:
    """File content at ``ref`` (None when absent — new file / bad ref)."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "show", f"{ref}:{path}"], cwd=repo_root,
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _base_ref_for(target: str, *, staged: bool, working_tree: bool) -> str:
    """Pre-change revision for ``git show`` — mirrors the extractor's ladder."""
    if staged or working_tree:
        return "HEAD"
    t = str(target or "HEAD")
    for sep in ("...", ".."):
        if sep in t:
            return t.split(sep, 1)[0] or "HEAD"
    return t or "HEAD"


def _py_signatures(source: str) -> Dict[str, Dict[str, Any]]:
    """qualname → signature facts via stdlib ast (Python only).

    Signature facts: ordered ``params`` as (name, required, kind) where
    kind is pos|kw|var|varkw, plus ``returns`` annotation text. A param
    is required when it has no default and is not *args/**kwargs.
    """
    import ast

    sigs: Dict[str, Dict[str, Any]] = {}
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return sigs

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = child.args
                params: List[Tuple[str, bool, str]] = []
                pos = list(a.posonlyargs) + list(a.args)
                n_pos_req = len(pos) - len(a.defaults)
                for i, p in enumerate(pos):
                    params.append(
                        (p.arg, i < n_pos_req, "pos"))
                for i, p in enumerate(a.kwonlyargs):
                    params.append(
                        (p.arg, a.kw_defaults[i] is None, "kw"))
                if a.vararg is not None:
                    params.append((a.vararg.arg, False, "var"))
                if a.kwarg is not None:
                    params.append((a.kwarg.arg, False, "varkw"))
                qn = f"{prefix}{child.name}"
                sigs[qn] = {
                    "params": params,
                    "returns": (ast.unparse(child.returns)
                                if child.returns is not None else None),
                }
                visit(child, qn + ".")
            else:
                visit(child, prefix +
                      (f"{child.name}." if isinstance(child, ast.ClassDef)
                       else ""))

    visit(tree, "")
    return sigs


def _classify_signature_diff(
    old: Dict[str, Any], new: Dict[str, Any],
) -> str:
    """breaking | compatible between two parsed signatures.

    Breaking: a required param removed/renamed/reordered, a NEW required
    param added, or *args/**kwargs dropped. Compatible: optional params
    added, defaults changed, return-annotation changes (Python does not
    enforce them — disclosed in known_blind_spots).
    """
    old_req = [(p[0], p[2]) for p in old["params"] if p[1]]
    new_req = [(p[0], p[2]) for p in new["params"] if p[1]]
    # Required set must be preserved exactly (same names, same order).
    if old_req != new_req:
        return "breaking"
    # A removed/renamed named param is breaking for keyword callers even
    # when it carried a default (f(a=1) → f(c=1) breaks f(a=...) calls).
    old_named = {p[0] for p in old["params"] if p[2] in ("pos", "kw")}
    new_named = {p[0] for p in new["params"] if p[2] in ("pos", "kw")}
    if old_named - new_named:
        return "breaking"
    old_kinds = {p[2] for p in old["params"]}
    new_kinds = {p[2] for p in new["params"]}
    if "var" in old_kinds - new_kinds or "varkw" in old_kinds - new_kinds:
        return "breaking"
    return "compatible"


def _public_symbol(qualname: str) -> bool:
    """Public = every dotted component lacks the underscore prefix."""
    return all(not part.startswith("_") for part in qualname.split("."))


def semantic_breaks(
    db: Any,
    repo_root: str,
    target: str,
    *,
    staged: bool = False,
    working_tree: bool = False,
    changed_files: Sequence[str] = (),
    errors_out: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Contract-break sweep over changed Python files (W6).

    For every changed ``.py`` file: old content via ``git show
    <base>:<path>``, new content from the index (staged) or worktree.
    A stdlib-``ast`` signature diff classifies each changed symbol
    breaking|compatible; breaking symbols with surviving indexed callers
    outside the diff's own files are ``callers_at_risk`` and feed
    ``safe_commit`` as BLOCK; public symbols that vanished without any
    indexed caller warn (external consumers are invisible to the graph).

    Scope honesty: Python only — non-Python changed files are counted in
    ``skipped_unsupported``; call sites built through dynamic dispatch,
    ``*args`` unpacking, re-export aliases, or decorators are disclosed
    blind spots, never claimed absent.
    """
    base = _base_ref_for(target, staged=staged, working_tree=working_tree)
    result: Dict[str, Any] = {
        "signature_changes": [],
        "public_symbols_removed": [],
        "counts": {"breaking": 0, "compatible": 0,
                   "removed_public": 0},
        "skipped_unsupported": 0,
        "known_blind_spots": [
            "python-only: non-python changed files are not analyzed",
            "dynamic dispatch / getattr / *args call sites not visible",
            "re-export aliases are not attributed to the origin module",
            "return-annotation and default-value changes are classified "
            "compatible (not enforced at runtime)",
        ],
    }
    changed_set = {str(f) for f in changed_files}
    for path in sorted(changed_set):
        if not path.endswith(".py"):
            result["skipped_unsupported"] += 1
            continue
        old_src = _git_show(repo_root, base, path)
        if old_src is None:
            continue  # new file — nothing pre-change to break
        if staged:
            # Index blob: `git show :path` (empty ref = stage-0 entry).
            new_src = _git_show(repo_root, "", path)
            if new_src is None:
                new_src = None
                try:
                    with open(os.path.join(repo_root, path),
                              encoding="utf-8", errors="replace") as fh:
                        new_src = fh.read()
                except OSError:
                    new_src = ""
        else:
            try:
                with open(os.path.join(repo_root, path),
                          encoding="utf-8", errors="replace") as fh:
                    new_src = fh.read()
            except OSError:
                new_src = ""
        old_sigs = _py_signatures(old_src)
        new_sigs = _py_signatures(new_src)
        for qn in sorted(set(old_sigs) | set(new_sigs)):
            if qn not in old_sigs:
                continue  # added symbol — nothing to break
            if qn not in new_sigs:
                if _public_symbol(qn):
                    result["public_symbols_removed"].append(
                        {"symbol": qn, "file": path})
                continue
            cls = _classify_signature_diff(old_sigs[qn], new_sigs[qn])
            if cls == "compatible":
                result["counts"]["compatible"] += 1
                continue
            # Breaking — find surviving callers outside the diff.
            callers: List[str] = []
            bare = qn.rsplit(".", 1)[-1]
            try:
                rows = db.conn.execute(
                    "SELECT DISTINCT src.path FROM graph_edges e "
                    "JOIN graph_nodes d ON e.dst = d.id "
                    "JOIN graph_nodes src ON e.src = src.id "
                    "WHERE d.symbol = ? AND e.relation = 'calls'",
                    (bare,),
                ).fetchall()
                changed_abs = {
                    os.path.realpath(os.path.join(repo_root, f))
                    for f in changed_set}
                callers = sorted({
                    os.path.relpath(str(r[0]), repo_root)
                    for r in rows
                    if os.path.realpath(str(r[0])) not in changed_abs})
            except Exception as exc:  # noqa: BLE001
                if errors_out is not None:
                    errors_out.append(
                        f"collection_error:semantic_breaks:{exc}")
            result["signature_changes"].append({
                "symbol": qn,
                "file": path,
                "classification": "breaking",
                "callers_at_risk": callers,
            })
            result["counts"]["breaking"] += 1
    result["counts"]["removed_public"] = len(
        result["public_symbols_removed"])
    return result


#: The three strict-gate verdicts, weakest → strongest.
SAFE_COMMIT_VERDICTS: Tuple[str, ...] = ("pass", "warn", "block")

#: Assurance statuses where the gate cannot honestly say "safe":
#: ABSTAINED/UNVERIFIABLE = not enough evidence to decide at all;
#: CONFLICTED = live contradictions; STALE = evidence predates the
#: current worktree (reconcile + re-run restores verifiability).
_SAFE_COMMIT_BLOCK_STATUSES: Tuple[str, ...] = (
    "ABSTAINED", "UNVERIFIABLE", "CONFLICTED", "STALE",
)


#: Caller-supplied test outcomes may only ever carry these keys. Anything
#: else — command lines, snapshot hashes, runner banners — is caller
#: METADATA and can never upgrade the block's provenance to verified
#: execution, so it makes the whole report invalid instead.
TEST_RESULTS_ALLOWED_KEYS: Tuple[str, ...] = ("ran", "failed", "failures")

TEST_RESULTS_CALLER_REPORTED = "caller_reported"


def validate_test_results(test_results: Any) -> Dict[str, Any]:
    """Structurally validate caller-supplied test outcomes (pure).

    Provenance is ALWAYS ``caller_reported``: this harness never executed
    these tests, so nothing in the block can constitute verified
    execution — a success count records a CLAIM, never a run, and
    ``ran == 0`` (or an absent count) must never be read as a passed
    run.

    Returns an evidence block:

    - ``validation == "valid"`` — counts (when present) are non-negative
      plain ints, ``failed <= ran``, ``failures`` is a list. Claimed
      failures block via ``effective_failed =
      max(failed or 0, len(failures))``; when that floor exceeds the
      claimed ``failed`` the block records ``healed_failed`` — healing
      only ever moves TOWARD more failures, never toward reassurance.
    - ``validation == "invalid"`` — bool/float/string counts, negative
      counts, a caller-claimed ``failed`` exceeding ``ran`` (exempt when
      the failed count equals ``len(failures)`` — label-explained counts
      are the harness's own healing, not a contradictory claim), unknown
      keys (command/hash strings), or a non-object report. NOTHING from
      an invalid report is trusted in either direction; consumers must
      warn and must never let it produce a ``pass``.

    Idempotent: an already-validated block (``provenance`` +
    ``validation`` present) passes through unchanged.
    """
    if isinstance(test_results, dict) and (
        test_results.get("provenance") == TEST_RESULTS_CALLER_REPORTED
        and test_results.get("validation") in ("valid", "invalid")
    ):
        return dict(test_results)

    def _invalid(errors: List[str]) -> Dict[str, Any]:
        return {
            "provenance": TEST_RESULTS_CALLER_REPORTED,
            "validation": "invalid",
            "ran": None,
            "failed": None,
            "failures": [],
            "effective_failed": None,
            "healed_failed": False,
            "errors": errors,
        }

    if not isinstance(test_results, dict):
        return _invalid([
            "test report must be a JSON object, got "
            f"{type(test_results).__name__}",
        ])
    errors: List[str] = []
    unknown = sorted(
        {str(k) for k in test_results} - set(TEST_RESULTS_ALLOWED_KEYS))
    if unknown:
        errors.append(
            "unknown key(s) " + ", ".join(repr(k) for k in unknown)
            + ": caller-supplied metadata (command/hash strings) cannot "
              "upgrade provenance")
    counts: Dict[str, Any] = {}
    for key in ("ran", "failed"):
        if key not in test_results:
            counts[key] = None
            continue
        value = test_results[key]
        # bool is an int subclass in Python — reject it explicitly or
        # ``{"failed": True}`` would masquerade as a real count.
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(
                f"{key} must be an int, got {value!r} "
                "(bool/float/str counts are rejected)")
        elif value < 0:
            errors.append(f"{key} must be >= 0, got {value}")
        else:
            counts[key] = value
    failures = test_results.get("failures")
    if failures is None:
        failures = []
    if not isinstance(failures, list):
        errors.append(
            f"failures must be a list, got {type(failures).__name__}")
        failures = []
    labels = [str(f) for f in failures]
    # ``failed > ran`` is a contradictory claim only when the FAILED
    # COUNT is the caller's own assertion. When the count equals the
    # number of labels it is fully explained by those labels — including
    # the canonicalized echo of a failures-only report (``{"ran": 0,
    # "failed": N}``), which re-enters this validator downstream via
    # ``safe_commit_verdict``. Exempting label-explained counts keeps
    # valid failure claims BLOCKING after canonicalization; healing only
    # ever moves toward more failures, never toward reassurance.
    if (counts.get("ran") is not None and counts.get("failed") is not None
            and counts["failed"] > counts["ran"]
            and counts["failed"] != len(labels)):
        errors.append(
            f"failed ({counts['failed']}) exceeds ran ({counts['ran']}): "
            "contradictory claim")
    if errors:
        return _invalid(errors)
    failed_claimed = counts.get("failed") or 0
    effective = max(failed_claimed, len(labels))
    return {
        "provenance": TEST_RESULTS_CALLER_REPORTED,
        "validation": "valid",
        "ran": counts.get("ran"),
        "failed": counts.get("failed"),
        "failures": labels,
        "effective_failed": effective,
        "healed_failed": effective > failed_claimed,
    }


def _json_safe(value: Any) -> Any:
    """JSON-clean leaves only: NaN/Inf floats become strings.

    Receipts are digested as canonical JSON; bare ``NaN``/``Infinity``
    would be non-standard bytes. Structure and labels are preserved —
    only the three non-JSON float leaves are stringified.
    """
    if isinstance(value, float) and (
        value != value or value in (float("inf"), -float("inf"))
    ):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def canonical_test_results(
    test_results: Any, evidence: Dict[str, Any]
) -> Dict[str, Any]:
    """Request-shape echo of a caller test report (legacy-compatible).

    valid → the established ``{'ran': int, 'failed': int,
    'failures': [str]}`` where ``failed`` is ``effective_failed``
    (failure claims heal UP only, and the healed count stays a
    caller-reported claim — never verified execution). The valid echo is
    revalidation-stable: fed back through
    :func:`validate_test_results` — as every strict CLI/MCP consumer
    does — it stays ``valid`` with the same ``effective_failed``, so a
    failures-only or zero-count-with-labels report keeps BLOCKING after
    canonicalization instead of degrading to warn. invalid → the
    caller's original object, NaN/Inf-safe, so the receipt stays clean
    JSON; the audit lives in the separate validation evidence block,
    never nested inside this echo (no self-growth).
    """
    if evidence.get("validation") == "valid":
        return {
            "ran": evidence.get("ran") or 0,
            "failed": evidence.get("effective_failed") or 0,
            "failures": list(evidence.get("failures") or []),
        }
    if isinstance(test_results, dict):
        return _json_safe(test_results)
    return {"report": _json_safe(test_results)}


def pre_receipt_binding(
    pre_receipt: Any,
    repo_root: str = "",
    head_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Compatibility/binding audit for an attached PRE-change receipt.

    Pure. The POST receipt must never mistake an arbitrary dict for the
    PRE-change prediction set it was minted against, and must never let
    a stale, foreign, or tampered payload pass as clean evidence:

    - ``missing`` — nothing attached (ordinary post-change receipt).
    - ``bound`` — scope/pre_change payload whose content digest
      recomputes against its own fields AND whose snapshot carries the
      producer-minted repository identity; predictions may be used.
    - ``unverified`` — compatible shape but no verifiable digest
      (hand-assembled payload or missing digest), no kind/proof_scope
      markers, or no snapshot repository identity (the foreign-repo
      guard cannot run); predictions usable but disclosed as advisory.
    - ``incompatible`` — wrong ``kind``/``proof_scope``, a different
      repository, non-object payload, or digest mismatch. Callers MUST
      NOT feed it to dispositions or the dangling pre-symbol nets: a
      foreign payload's "predictions" would otherwise be invented
      evidence (or, worse, its cleanliness would read as "no predicted
      impact").

    ``head_moved`` (when both HEADs are known) flags that the worktree
    moved since minting; it degrades nothing by itself but is surfaced
    so operators know the predictions predate this diff's base.
    """
    if pre_receipt is None:
        return {"status": "missing", "reasons": [],
                "head_moved": None, "digest_verified": None}
    if not isinstance(pre_receipt, dict):
        return {"status": "incompatible",
                "reasons": ["PRE receipt is not a JSON object"],
                "head_moved": None, "digest_verified": None}
    reasons: List[str] = []
    incompatible = False
    kind = pre_receipt.get("kind")
    proof_scope = pre_receipt.get("proof_scope")
    structured = kind is not None or proof_scope is not None
    if kind is not None and kind != "scope":
        incompatible = True
        reasons.append(
            f"PRE receipt kind {kind!r} is not 'scope': not a PRE-change "
            "scope prediction")
    if proof_scope is not None and proof_scope != "pre_change_only":
        incompatible = True
        reasons.append(
            f"PRE receipt proof_scope {proof_scope!r} is not "
            "'pre_change_only': POST or audit proof must never feed "
            "PRE dispositions")
    pre_root = (pre_receipt.get("snapshot") or {}).get("repo_root")
    if repo_root and pre_root:
        if os.path.realpath(str(pre_root)) != os.path.realpath(repo_root):
            incompatible = True
            reasons.append(
                "PRE receipt was minted against a different repository "
                f"({pre_root!r})")
    digest_verified: Optional[bool] = None
    if "digest" in pre_receipt:
        from sot_graph.assurance.receipts import receipt_digest
        recomputed = receipt_digest(
            {k: v for k, v in pre_receipt.items() if k != "digest"})
        digest_verified = recomputed == pre_receipt.get("digest")
        if not digest_verified:
            incompatible = True
            reasons.append(
                "PRE receipt content digest mismatch: payload was "
                "modified after minting or belongs to another receipt")
    head_moved: Optional[bool] = None
    pre_head = (pre_receipt.get("snapshot") or {}).get("commit_sha")
    if head_sha and pre_head:
        head_moved = str(pre_head) != str(head_sha)
        if head_moved:
            reasons.append(
                "worktree HEAD moved since the PRE receipt was minted; "
                "its predictions predate this diff's base revision")
    if not structured:
        reasons.append(
            "PRE payload carries no kind/proof_scope markers: treated as "
            "a caller-assembled prediction set (unverified)")
    # Repository identity: a matching ``snapshot.repo_root`` (minted by
    # :class:`sot_graph.snapshot.WorktreeSnapshot.as_dict`) is what makes
    # the foreign-repo guard decidable. A receipt whose snapshot carries
    # NO repository identity (legacy pre-binding receipts, or a payload
    # stripped of the field) can never be confirmed same-repository, so
    # it stays advisory (unverified) instead of silently bound — a
    # caller-supplied payload omitting the field is not trust.
    repo_identity_present = bool(pre_root)
    if not repo_identity_present and not incompatible:
        reasons.append(
            "PRE snapshot carries no repository identity: foreign-repo "
            "guard not run; provenance cannot be confirmed (unverified)")
    status = ("incompatible" if incompatible
              else "unverified" if (digest_verified is not True
                                    or not structured
                                    or not repo_identity_present)
              else "bound")
    return {"status": status, "reasons": reasons,
            "head_moved": head_moved, "digest_verified": digest_verified}


def safe_commit_verdict(
    *,
    assurance_status: str,
    dangling_count: int,
    debt_introduced: int,
    dispositions: Dict[str, Any],
    test_results: Optional[Dict[str, Any]] = None,
    semantic_breaks: Optional[Dict[str, Any]] = None,
    pre_receipt_binding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Composite "is it safe to commit?" verdict for the post-change gate (W2).

    Pure reducer over data the diff receipt already collected — never
    queries the DB. Escalation is one-directional: pass → warn → block.

    BLOCK (would leave a defect or cannot verify):
      * ``dangling_count`` > 0 — references the change left unresolved
        (the renamed/deleted symbol callers still cite);
      * assurance status in ``_SAFE_COMMIT_BLOCK_STATUSES`` — the gate
        itself lacks trustworthy evidence;
      * caller-provided ``test_results`` claim failures — validated via
        :func:`validate_test_results`; provenance stays
        ``caller_reported`` (the harness never executed them), yet an
        explicit failure claim is honored as blocking.

    WARN (advisory — the change may be fine, but evidence is advisory):
      * assurance status PARTIAL;
      * pre-receipt dispositions still untouched (predicted callers /
        tests the diff never reached — heuristic prediction, kept
        advisory by the same contract as ``disposition_matrix``);
      * debt markers introduced on added lines;
      * a STRUCTURALLY INVALID caller test report (bool/float/str or
        negative counts, ``failed > ran``, unknown keys) — recorded,
        trusted in neither direction, and never allowed to produce a
        ``pass``;
      * an attached PRE receipt whose binding audit came back
        ``incompatible`` (its predictions were excluded downstream).

    ``dispositions`` is the ``resolution_ledger["dispositions"]``
    payload; when no pre-receipt was attached the untouched nets are
    absent and the verdict discloses ``pre_receipt_attached: False`` so
    operators know the rename/delete leftover sweep did not run. An
    attached-but-incompatible PRE receipt is disclosed via
    ``pre_receipt_binding`` and never reads as a clean disposition.

    ``pre_receipt_binding`` is the ``resolution_ledger
    ["pre_receipt_binding"]`` audit block (:func:`pre_receipt_binding`).

    The returned ``tests`` block states the test evidence truthfully:
    ``provenance`` is ``caller_reported`` (or ``absent``),
    ``validation`` records the structural audit, and
    ``tests_verified_execution`` is always ``False`` — a passing caller
    count never proves a runner executed or that this snapshot was
    tested. Graph assurance (and legacy graph-only closure) stays
    independent of caller test claims: a valid report with no claimed
    failures neither blocks nor reassures.
    """
    block_reasons: List[str] = []
    warn_reasons: List[str] = []

    if int(dangling_count) > 0:
        block_reasons.append(
            f"{int(dangling_count)} dangling reference(s): code cites "
            "symbols the graph can no longer resolve")
    status = str(assurance_status or "")
    if status in _SAFE_COMMIT_BLOCK_STATUSES:
        block_reasons.append(
            f"assurance status {status}: evidence insufficient, "
            "contradictory, or stale — the gate cannot verify safety")
    elif status == "PARTIAL":
        warn_reasons.append(
            "assurance PARTIAL: part of the evidence set is incomplete")

    # W2 trust boundary: caller test claims are validated, recorded with
    # their provenance, and only ever trusted in the blocking direction.
    # An invalid report can never reassure; claimed failures still block;
    # a valid no-failure report (including ran=0) neither blocks nor
    # upgrades the graph-only closure.
    tests = (validate_test_results(test_results)
             if test_results is not None else None)
    if tests is not None:
        if tests["validation"] == "invalid":
            warn_reasons.append(
                "caller test report invalid — recorded, trusted in "
                "neither direction: " + "; ".join(tests["errors"]))
        elif tests["effective_failed"]:
            block_reasons.append(
                f"{tests['effective_failed']} provided test(s) failed")

    attached = bool(dispositions.get("pre_receipt_attached"))
    untouched_callers = 0
    untouched_tests = 0
    if attached:
        untouched_callers = len(
            (dispositions.get("direct_callers") or {}).get("untouched")
            or [])
        untouched_tests = len(
            (dispositions.get("candidate_tests") or {}).get("untouched")
            or [])
        if untouched_callers:
            warn_reasons.append(
                f"{untouched_callers} predicted caller(s) untouched by "
                "the diff")
        if untouched_tests:
            warn_reasons.append(
                f"{untouched_tests} predicted test file(s) untouched by "
                "the diff")
    if int(debt_introduced) > 0:
        warn_reasons.append(
            f"{int(debt_introduced)} debt marker(s) introduced on added "
            "lines")

    breaking_with_callers = 0
    breaking_no_callers = 0
    removed_public = 0
    if semantic_breaks:
        for ch in semantic_breaks.get("signature_changes") or []:
            if ch.get("classification") != "breaking":
                continue
            if ch.get("callers_at_risk"):
                breaking_with_callers += 1
            else:
                breaking_no_callers += 1
        removed_public = len(
            semantic_breaks.get("public_symbols_removed") or [])
        if breaking_with_callers:
            block_reasons.append(
                f"{breaking_with_callers} breaking signature change(s) "
                "with surviving callers outside this diff")
        if breaking_no_callers:
            warn_reasons.append(
                f"{breaking_no_callers} breaking signature change(s) "
                "with no indexed callers")
        if removed_public:
            warn_reasons.append(
                f"{removed_public} public symbol(s) removed — external "
                "consumers are invisible to the graph")

    binding_status = str((pre_receipt_binding or {}).get("status") or "missing")
    if binding_status == "incompatible":
        warn_reasons.append(
            "attached PRE receipt is incompatible and was excluded from "
            "dispositions and dangling sweeps: "
            + "; ".join((pre_receipt_binding or {}).get("reasons") or []))

    verdict = ("block" if block_reasons
               else "warn" if warn_reasons else "pass")
    tests_evidence = tests if tests is not None else {
        "provenance": "absent",
        "validation": "absent",
        "note": "no caller-supplied test results attached; this verdict "
                "never implies tests were executed",
    }
    return {
        "verdict": verdict,
        "block_reasons": block_reasons,
        "warn_reasons": warn_reasons,
        # Truthful test-evidence record: caller_reported vs absent,
        # structural validation status, and the invariant that nothing
        # here proves a runner executed against this snapshot.
        "tests": tests_evidence,
        "inputs": {
            "assurance_status": status,
            "dangling_count": int(dangling_count),
            "debt_introduced": int(debt_introduced),
            "untouched_callers": untouched_callers,
            "untouched_tests": untouched_tests,
            "tests_failed": (tests or {}).get("effective_failed") or 0,
            "tests_ran": (tests or {}).get("ran"),
            "tests_provenance": (tests or {}).get("provenance") or "absent",
            "tests_validation": (tests or {}).get("validation") or "absent",
            "tests_verified_execution": False,
            "test_results_attached": test_results is not None,
            "pre_receipt_attached": attached,
            "pre_receipt_binding": binding_status,
            "breaking_signature_changes_with_callers": breaking_with_callers,
            "breaking_signature_changes_no_callers": breaking_no_callers,
            "public_symbols_removed": removed_public,
        },
    }
