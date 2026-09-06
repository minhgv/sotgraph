"""Token-budgeted repo map ranked by personalized PageRank.

Aider proved that a PageRank-ranked, token-budgeted symbol map gives coding
agents cheap orientation (https://aider.chat/docs/repomap.html). This module
applies the same recipe to the sotgraph database: rank code symbols by
graph centrality, personalize on the caller's focus set when given, then
binary-search the symbol count until the rendered tree fits the budget.

Since SG-201 the map ranks production source by default: symbols are
classified from their root-relative path (see :func:`classify_path`) and
non-production categories (tests, fixtures, vendor, generated, docs,
tooling) only participate when explicitly opted in via
``include_categories``. The applied filter is echoed in the result and in
the rendered footer, because a filtered map must never be mistaken for the
whole index.
"""
from __future__ import annotations
import fnmatch
import os
import posixpath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from sot_graph.analytics.graph import OperationCancelledError
from sot_graph.tokenizer import estimate_tokens

DAMPING = 0.85
ITERATIONS = 24
_RANKED_RELATIONS = ("calls", "extends", "implements", "uses")

# --- Path categories (SG-201) -----------------------------------------------
# Filters are defined over canonical root-relative POSIX paths (same
# convention as normalize_repo_path in assurance/identity.py: backslashes
# become "/", "./" prefixes are stripped, posixpath.normpath; no symlink or
# case resolution). There is deliberately exactly one classification here —
# CLI and MCP both go through build_repo_map and cannot diverge.

CATEGORY_PRODUCTION = "production"
ALL_CATEGORIES = (
    "production", "test", "fixture", "vendor", "generated", "docs", "tooling",
)
DEFAULT_CATEGORIES = (CATEGORY_PRODUCTION,)

# Fixed precedence order: first match wins, so "tests/fixtures/x.py" is a
# fixture (not a test) and "docs/dist/x.js" is generated (not docs).
_SEGMENT_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("fixture", ("fixtures", "fixture", "testdata", "test_data", "evaluation",
                 "evals", "__snapshots__", "__fixtures__")),
    ("test", ("tests", "test", "spec", "specs", "__tests__")),
    ("vendor", ("vendor", "_vendor", "vendored", "third_party", "thirdparty",
                "external", "node_modules")),
    ("generated", ("dist", "build", "out", "generated", "_generated",
                   "coverage", "__pycache__")),
    ("docs", ("docs", "doc", "documentation")),
    ("tooling", ("scripts", "tools", "tooling", "benchmark", "benchmarks",
                 "benches", "ci", ".github", ".circleci", ".gitlab")),
)
_FILENAME_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("test", ("conftest.*", "test_*", "*_test.*")),
    ("vendor", ("*.min.js", "*.min.css")),
    ("generated", ("*_pb2.py", "*_pb2_grpc.py")),
)

_ABSENCE_NOTE = "absence from this map does not imply absence from the index"


def _canon_rel(path: str) -> str:
    """Canonical root-relative form (normalize_repo_path convention)."""
    norm = (path or "").replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return posixpath.normpath(norm) or "."


def classify_path(rel_path: str) -> str:
    """Classify a canonical root-relative POSIX path into its map category.

    Deterministic rule, deliberately narrow:
    - matching is case-sensitive;
    - a segment rule matches when ANY segment of the path exactly equals one
      of the rule's directory names (so ``src/pkg/_vendor/x.py`` is vendor
      even though the vendor segment is not the first);
    - otherwise the basename is fnmatch-tested (``fnmatchcase``, so also
      case-sensitive) against the filename rules — e.g. ``test_helper.py``
      is a test even under ``src/``;
    - categories are tried in the fixed precedence order documented on
      ``_SEGMENT_RULES``; anything unmatched is ``production``.
    """
    segments = _canon_rel(rel_path).split("/")
    for category, names in _SEGMENT_RULES:
        if any(seg in names for seg in segments):
            return category
    base = segments[-1]
    for category, patterns in _FILENAME_RULES:
        if any(fnmatch.fnmatchcase(base, pat) for pat in patterns):
            return category
    return CATEGORY_PRODUCTION


def parse_include_categories(
    value: Optional[Union[str, Sequence[str]]] = None,
) -> Tuple[str, ...]:
    """Normalize an ``include_categories`` argument to canonical categories.

    ``None`` or empty means the default (production only); ``"all"`` (alone
    or in the list) means every category; otherwise a comma-separated string
    or a sequence of category names. Names are case-sensitive and validated
    (ValueError on unknown names); the result is deduplicated and returned
    in canonical :data:`ALL_CATEGORIES` order.
    """
    if value is None:
        return DEFAULT_CATEGORIES
    if isinstance(value, str):
        names = [part.strip() for part in value.split(",")]
    else:
        names = [str(part).strip() for part in value]
    names = [name for name in names if name]
    if not names:
        return DEFAULT_CATEGORIES
    if "all" in names:
        return ALL_CATEGORIES
    unknown = [name for name in names if name not in ALL_CATEGORIES]
    if unknown:
        raise ValueError(
            f"unknown category {unknown[0]!r} — valid categories: "
            f"{', '.join(ALL_CATEGORIES)}, all")
    chosen = set(names)
    return tuple(cat for cat in ALL_CATEGORIES if cat in chosen)


def _escapes_root(display_path: str) -> bool:
    """True when a root-relative display path points outside the root."""
    return (os.path.isabs(display_path) or display_path == ".."
            or display_path.startswith("../"))


def _display_path(path: str, root: Optional[str]) -> str:
    """Absolute journal paths are normalized so the budget is spent on code.

    Both sides go through ``os.path.realpath`` first (project convention, cf.
    ``_repo_rel`` in providers/identity_join.py): symlinked roots — e.g. the
    macOS ``/var`` -> ``/private/var`` alias behind ``McpService.project_root``
    — must compare equal to the paths stored in the journal. Paths that still
    escape the root keep their ``../`` form and are dropped by
    ``_load_symbols`` (cross-root isolation).
    """
    if root and os.path.isabs(path):
        try:
            return os.path.relpath(
                os.path.realpath(path), os.path.realpath(root)
            ).replace(os.sep, "/")
        except ValueError:
            return path
    return path


def _load_symbols(conn, root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, symbol, kind, path, line_start, signature FROM graph_nodes "
        "WHERE kind != 'file' AND kind != 'note' AND path != '' "
        "AND kind != 'markdown'"
    ).fetchall()
    if not rows:
        return {}
    if root is None:
        abs_paths = [os.path.realpath(r[3]) for r in rows if os.path.isabs(r[3])]
        if abs_paths:
            try:
                root = os.path.commonpath(abs_paths)
            except ValueError:
                root = None
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        display = _display_path(row[3], root)
        # Cross-root isolation: when the caller pins a root, symbols living
        # under another root (relpath escapes via "../", or the path cannot
        # be made relative at all) must never enter the map.
        if root is not None and _escapes_root(display):
            continue
        out[row[0]] = {"id": row[0], "symbol": row[1], "kind": row[2],
                       "path": display, "line": row[4], "signature": row[5]}
    return out


def _load_edges(conn, symbol_ids) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for src, dst, relation in conn.execute(
        f"SELECT src, dst, relation FROM graph_edges "
        f"WHERE relation IN ({','.join('?' * len(_RANKED_RELATIONS))})",
        _RANKED_RELATIONS,
    ):
        if src in symbol_ids and dst in symbol_ids and src != dst:
            out.setdefault(src, []).append(dst)
    # Adjacency lists are sorted so PageRank's float summation order does not
    # depend on SQLite row order (determinism requirement, SG-201).
    return {src: sorted(dsts) for src, dsts in out.items()}


def pagerank(
    nodes: List[str],
    out_edges: Dict[str, List[str]],
    personalization: Optional[Dict[str, float]] = None,
    damping: float = DAMPING,
    iterations: int = ITERATIONS,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, float]:
    """Power iteration with uniform restart mass (dangling nodes included)."""
    if cancel_check and cancel_check():
        raise OperationCancelledError("Analytics operation cancelled by client")
    n = len(nodes)
    if n == 0:
        return {}
    base = personalization or {u: 1.0 / n for u in nodes}
    total = sum(base.values()) or 1.0
    base = {u: base.get(u, 0.0) / total for u in nodes}
    rank = dict(base)
    out_count = {u: len(out_edges.get(u, [])) for u in nodes}
    for _ in range(iterations):
        if cancel_check and cancel_check():
            raise OperationCancelledError("Analytics operation cancelled by client")
        nxt = {u: (1.0 - damping) * base.get(u, 0.0) for u in nodes}
        dangling = damping * sum(rank[u] for u in nodes if out_count[u] == 0) / n
        for u in nodes:
            nxt[u] += dangling
        for u in nodes:
            if out_count[u]:
                share = damping * rank[u] / out_count[u]
                for v in out_edges[u]:
                    nxt[v] += share
        rank = nxt
    return rank


def _resolve_focus(conn, focus: List[str], symbol_ids) -> List[str]:
    resolved: List[str] = []
    for name in focus:
        name = name.strip()
        if not name:
            continue
        row = conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = ? LIMIT 1", (name,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM graph_nodes WHERE kind != 'file' AND (label LIKE ? OR fqn LIKE ?) "
                "ORDER BY kind LIMIT 1", (f"%{name}%", f"%{name}%")
            ).fetchone()
        if row and row[0] in symbol_ids:
            resolved.append(row[0])
    return resolved


def _render(symbols: List[Dict[str, Any]]) -> str:
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for sym in symbols:
        by_path.setdefault(sym["path"], []).append(sym)
    lines: List[str] = []
    for path in sorted(by_path):
        lines.append(f"{path}:")
        for sym in sorted(by_path[path], key=lambda s: (s["line"] or 0, s["symbol"])):
            stub = sym["signature"] or sym["symbol"]
            lines.append(f"  {stub}")
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    # Same estimator as build_repo_map, kept for direct callers; the old
    # body divided by an undefined `_CHARS_PER_TOKEN` constant (NameError).
    return estimate_tokens(text)


def _scope_text(categories_included: Tuple[str, ...],
                categories_excluded: Tuple[str, ...],
                indexed: int, shown: int) -> str:
    if categories_excluded:
        return (f"map scope: {','.join(categories_included)} only — "
                f"hid {indexed - shown} of {indexed} indexed symbols "
                f"({','.join(categories_excluded)} excluded)")
    return "map scope: all categories — no category filter"


def build_repo_map(
    conn,
    *,
    focus: Optional[List[str]] = None,
    max_tokens: int = 1024,
    max_symbols: int = 400,
    root: Optional[str] = None,
    include_categories: Optional[Union[str, Sequence[str]]] = None,
) -> Dict[str, Any]:
    """Rank symbols by personalized PageRank and fit them to a token budget.

    Category filter (SG-201): every symbol is classified from its canonical
    root-relative POSIX path (:func:`classify_path`) and only categories
    named in ``include_categories`` participate in ranking — by default
    production source only. Pass ``"all"`` or a comma-separated category
    list to opt in. Focus only personalizes symbols that pass the filter.
    Symbols under a different root than ``root`` are never included,
    regardless of filter settings.

    The applied filter is echoed back in ``result["filters"]`` and as two
    footer lines appended to ``result["rendered"]`` (scope + absence
    anti-inference note). The footer is part of the returned text, so the
    token budget covers tree + footer together; a budget too small for even
    one symbol yields an empty tree with the footer still present.
    """
    max_tokens = max(16, min(int(max_tokens), 32_768))
    categories = parse_include_categories(include_categories)
    excluded_categories = tuple(c for c in ALL_CATEGORIES if c not in categories)
    allowed = frozenset(categories)

    indexed_symbols = _load_symbols(conn, root)
    indexed_count = len(indexed_symbols)
    symbols = {nid: meta for nid, meta in indexed_symbols.items()
               if classify_path(meta["path"]) in allowed}
    scope_text = _scope_text(categories, excluded_categories,
                             indexed_count, len(symbols))
    footer = f"({scope_text})\n({_ABSENCE_NOTE})"
    filters = {
        "categories_included": list(categories),
        "categories_excluded": list(excluded_categories),
        "excluded_symbols": indexed_count - len(symbols),
        "description": scope_text,
        "absence_note": _ABSENCE_NOTE,
    }

    if not symbols:
        # An empty index keeps rendered empty (callers prompt for `sotgraph
        # reconcile`); a filter that hides everything still echoes its scope.
        rendered = footer if indexed_count else ""
        return {"files": [], "rendered": rendered,
                "tokens_estimate": estimate_tokens(rendered), "symbols": 0,
                "focus": [], "truncated": False,
                "ranking_method": "pagerank", "language_breakdown": {},
                "filters": filters}

    # Deterministic base order: ranking tie-breaks and float summation order
    # must not depend on SQLite row order.
    ids = sorted(symbols, key=lambda u: (symbols[u]["path"], symbols[u]["symbol"],
                                         symbols[u]["kind"], u))
    out_edges = _load_edges(conn, symbols)
    personalization = None
    focus_ids: List[str] = []
    if focus:
        focus_ids = _resolve_focus(conn, [f for f in focus], symbols)
        if focus_ids:
            personalization = {fid: 1.0 for fid in focus_ids}
    ranks = pagerank(ids, out_edges, personalization)
    ordered = sorted(ids, key=lambda u: (-ranks[u], symbols[u]["path"],
                                         symbols[u]["symbol"], symbols[u]["kind"], u))
    # Focus symbols are guaranteed to appear in the map (front of the
    # budgeted prefix) even when pure centrality would rank them lower.
    if focus_ids:
        focus_set = set(focus_ids)
        ordered = [u for u in focus_ids if u in focus_set] + \
                  [u for u in ordered if u not in focus_set]
    ordered = ordered[:max_symbols]

    # Binary search the largest prefix whose rendered tree plus the scope
    # footer fits the budget.
    footer_tokens = estimate_tokens(footer)
    lo, hi, best = 1, len(ordered), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        text = _render([symbols[u] for u in ordered[:mid]])
        if estimate_tokens(text) + footer_tokens <= max_tokens:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    chosen = ordered[:best]
    tree = _render([symbols[u] for u in chosen])
    rendered = f"{tree}\n{footer}" if chosen else footer
    files: List[Dict[str, Any]] = []
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    lang_counts: Dict[str, int] = {}

    for u in chosen:
        sym_path = symbols[u]["path"]
        ext = os.path.splitext(sym_path)[1].lstrip(".") or "other"
        lang_counts[ext] = lang_counts.get(ext, 0) + 1

        by_path.setdefault(sym_path, []).append(
            {"symbol": symbols[u]["symbol"], "kind": symbols[u]["kind"],
             "line": symbols[u]["line"], "signature": symbols[u]["signature"],
             "rank": round(ranks[u], 8)})
    for path in sorted(by_path):
        files.append({"path": path,
                      "symbols": sorted(by_path[path], key=lambda s: (s["line"] or 0, s["symbol"]))})

    total_syms = len(chosen)
    lang_breakdown = {
        lang: round((count / total_syms) * 100.0, 1)
        for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])
    } if total_syms > 0 else {}

    return {
        "files": files,
        "rendered": rendered,
        "tokens_estimate": estimate_tokens(rendered),
        "symbols": len(chosen),
        "focus": focus_ids,
        "ranking_method": "personalized_pagerank" if focus_ids else "pagerank",
        "language_breakdown": lang_breakdown,
        "truncated": best < len(ordered),
        "filters": filters,
    }
