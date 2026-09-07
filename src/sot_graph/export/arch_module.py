"""Module-level rollup for architecture views.

Aggregates the symbol-level :class:`AnalyticsGraph` into module cards — one
card per package directory or root source file under the source prefix — so
the tiered renderer draws a system-level layered architecture instead of every
single symbol. Pure and deterministic: sorted iteration only, no I/O, no
wall-clock, identical inputs produce identical output.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.export.arch_html import build_arch_view, render_html, validate

_INIT_FILES = frozenset({"__init__.py", "__init__.pyi", "__main__.py"})


def module_key(path: str, prefix: str) -> Optional[str]:
    """Map a symbol path to its module key, or ``None`` when outside ``prefix``.

    A module is the first path segment under ``prefix``: a package directory
    (``pkg/...`` → ``pkg``) or a root file (``db.py`` → ``db``). Package
    markers such as ``__init__.py`` do not form modules of their own.
    """
    norm = path.replace("\\", "/")
    pre = prefix.replace("\\", "/").rstrip("/") + "/"
    if not norm.startswith(pre):
        return None
    rel = norm[len(pre):]
    if not rel:
        return None
    first = rel.split("/", 1)[0]
    if "/" not in rel:
        if first in _INIT_FILES:
            return None
        if first.endswith(".py") or first.endswith(".pyi"):
            return first[: -len(".py")] if first.endswith(".py") else first[: -len(".pyi")]
        return first
    return first or None


def rollup_modules(graph: AnalyticsGraph, prefix: str) -> AnalyticsGraph:
    """Fold ``graph`` into one node per module under ``prefix``.

    Node payloads carry ``symbol_count``/``class_count`` aggregates; edges are
    summed into module-to-module weights with the most frequent relation
    (ties broken by relation name for determinism). Self-loops are dropped.
    """
    out = AnalyticsGraph()
    counts: Dict[str, int] = {}
    classes: Dict[str, int] = {}
    paths: Dict[str, List[str]] = {}
    node_module: Dict[str, str] = {}
    for nid in sorted(graph.nodes):
        data = graph.nodes[nid]
        key = module_key(str(data.get("path") or ""), prefix)
        if key is None:
            continue
        node_module[nid] = key
        counts[key] = counts.get(key, 0) + 1
        if str(data.get("kind")) == "class":
            classes[key] = classes.get(key, 0) + 1
        paths.setdefault(key, []).append(str(data.get("path") or ""))

    for key in sorted(counts):
        rep = min(paths[key])  # lexicographically smallest path is stable
        out.add_node(
            node_id=f"module/{key}",
            label=key,
            kind="module",
            path=rep,
            symbol_count=counts[key],
            class_count=classes.get(key, 0),
        )

    weights: Counter[Tuple[str, str]] = Counter()
    relations: Dict[Tuple[str, str], Counter] = {}
    for e in graph.edges:
        src = node_module.get(str(e.get("src")))
        dst = node_module.get(str(e.get("dst")))
        if not src or not dst or src == dst:
            continue
        pair = (src, dst)
        weights[pair] += 1
        rel = str(e.get("relation") or "relates")
        relations.setdefault(pair, Counter())[rel] += 1

    for pair in sorted(weights):
        rel = sorted(relations[pair].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out.add_edge(f"module/{pair[0]}", f"module/{pair[1]}", relation=rel, weight=weights[pair])
    return out


def generate_module_html(
    graph: AnalyticsGraph,
    title: str,
    project: str,
    prefix: str,
    scope: Optional[str] = None,
) -> str:
    """Rollup + build + validate (fail-closed); raise ``ValueError`` on any violation."""
    module_graph = rollup_modules(graph, prefix)
    view = build_arch_view(module_graph, title=title, project=project, scope=scope)
    violations = validate(view)
    if violations:
        raise ValueError("module view validation failed: " + "; ".join(violations))
    return render_html(view)
