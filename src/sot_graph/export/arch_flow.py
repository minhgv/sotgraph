"""Flow-mode ``ArchView`` extraction (stage 2) — reuses existing call-path
extractors only, no new code analysis.

The operating flow of a target symbol is the outward call subgraph behind
``sotgraph explore``: :func:`sot_graph.assurance.engine.resolve_symbol`
resolves the target and :meth:`sot_graph.db.Database.explore_node` walks the
k-hop neighbourhood. A node's ``step`` is its BFS distance from the entry
recomputed over outward edges only, so it is the true outward call distance
(nodes discovered only via inbound expansion fall back to ``max_step + 1``).
Decision branches (ui-tree/trace) are deliberately omitted in stage 2 — the
wiring from UI components to arbitrary symbol targets would be a new
heuristic, which the contract forbids.

Deterministic: every emitted structure is sorted before use; no random, no
wall-clock. Same DB state yields a byte-identical render.
"""
from __future__ import annotations

from collections import Counter, deque
from typing import Any, Dict, List, Tuple

from sot_graph.assurance.engine import resolve_symbol
from sot_graph.export.arch_html import _edge_kind, render_html, validate
from sot_graph.export.arch_layout import layout_flow

__all__ = [
    "DEFAULT_DEPTH",
    "DEFAULT_MAX_NODES",
    "UnresolvedFlowTarget",
    "build_flow_view",
    "generate_flow_html",
    "resolve_flow_target",
]

DEFAULT_DEPTH = 3
DEFAULT_MAX_NODES = 60


class UnresolvedFlowTarget(LookupError):
    """Raised when the flow target matches no graph node (contract I5)."""


def _evidence_text(path: str, line: Any) -> str:
    if not path:
        return ""
    return f"{path}:{int(line)}" if line else path


def _module_of(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    dirs = parts[:-1]
    return dirs[-1] if dirs else "(root)"


def resolve_flow_target(db: Any, target: str) -> Dict[str, Any]:
    """Resolve a flow target via the ``explore`` resolver; raise if absent."""
    row = resolve_symbol(db, target.strip())
    if not row:
        raise UnresolvedFlowTarget(
            f"no symbol or node matching '{target.strip()}' found in graph"
        )
    node_id, label, kind, path, line, _symbol = row
    return {
        "id": str(node_id),
        "label": str(label or node_id),
        "kind": str(kind or "symbol"),
        "path": str(path or ""),
        "line": int(line) if line else None,
    }


def _subgraph(
    entry: Dict[str, Any],
    relations: List[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Merge outward relation rows into a node map + deduped raw edge list."""
    nodes: Dict[str, Dict[str, Any]] = {
        entry["id"]: {
            "id": entry["id"],
            "label": entry["label"],
            "role": entry["kind"],
            "path": entry["path"],
            "evidence": _evidence_text(entry["path"], entry["line"]),
            "entry": True,
        }
    }
    raw: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in relations:
        src = str(r.get("via_id") or entry["id"])
        dst = str(r.get("target_id"))
        if src == dst:
            continue
        if src not in nodes:
            # Parent reached via inward expansion (no outward path from the
            # entry): keep the node (real graph neighbour, real call edge)
            # and let the step layering park it at the fallback layer.
            via_path = str(r.get("via_path") or "")
            nodes[src] = {
                "id": src,
                "label": str(r.get("via_label") or src),
                "role": "symbol",
                "path": via_path,
                "evidence": _evidence_text(via_path, None),
                "entry": False,
            }
        key = (src, dst)
        if key in raw:
            raw[key]["weight"] += 1
            continue
        raw[key] = {
            "src": src,
            "dst": dst,
            "relation": str(r.get("relation") or "calls"),
            "weight": 1,
        }
        if dst not in nodes:
            nodes[dst] = {
                "id": dst,
                "label": str(r.get("label") or dst),
                "role": str(r.get("kind") or "symbol"),
                "path": str(r.get("path") or ""),
                "evidence": _evidence_text(str(r.get("path") or ""), r.get("line")),
                "entry": False,
            }
    return nodes, list(raw.values())


def _step_layers(
    entry_id: str, edges: List[Dict[str, Any]], node_count: int
) -> Dict[str, int]:
    """BFS layers over outward edges (visited set terminates on cycles)."""
    adj: Dict[str, List[str]] = {}
    for e in edges:
        adj.setdefault(e["src"], []).append(e["dst"])
    for nbrs in adj.values():
        nbrs.sort()
    step: Dict[str, int] = {entry_id: 1}
    queue: deque = deque([entry_id])
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, []):
            if nxt not in step:
                step[nxt] = step[cur] + 1
                queue.append(nxt)
    if len(step) < node_count:
        fallback = (max(step.values()) if step else 0) + 1
        for nid in sorted(set(adj) | {d for nbrs in adj.values() for d in nbrs}):
            step.setdefault(nid, fallback)
    return step


def _apply_budget(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    entry_id: str,
    steps: Dict[str, int],
    max_nodes: int,
    depth: int,
) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, Any]]:
    """Hard node budget (pack philosophy): keep the entry plus top-N by
    relevance (out-degree hub score, then BFS closeness, then id); edges
    touching dropped nodes are dropped together with them."""
    total = len(nodes)
    truncation = {
        "capped": False,
        "shown": total,
        "total": total,
        "hint_depth": int(depth),
    }
    if total <= max_nodes:
        return sorted(nodes), edges, truncation
    outdeg: Counter = Counter(e["src"] for e in edges)
    ranked = sorted(
        nodes,
        key=lambda nid: (
            nid != entry_id,
            -outdeg.get(nid, 0),
            steps.get(nid, 1 << 30),
            nid,
        ),
    )
    kept = set(ranked[: max(1, int(max_nodes))])
    kept_nodes = sorted(nid for nid in nodes if nid in kept)
    kept_edges = [e for e in edges if e["src"] in kept and e["dst"] in kept]
    truncation.update(capped=True, shown=len(kept_nodes))
    return kept_nodes, kept_edges, truncation


def _module_lanes(node_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[str]] = {}
    for n in node_dicts:
        groups.setdefault(_module_of(str(n.get("path") or "")), []).append(n["id"])
    return [
        {"id": f"lane:{m}", "label": m, "nodes": sorted(ids)}
        for m, ids in sorted(groups.items())
    ]


def build_flow_view(
    db: Any,
    target: str,
    project: str,
    depth: int = DEFAULT_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    lanes: str = "none",
) -> Dict[str, Any]:
    """Build the flow ``ArchView`` IR (layout=flow) from the live graph DB."""
    depth = max(1, int(depth))
    max_nodes = max(1, int(max_nodes))
    entry = resolve_flow_target(db, target)
    relations = [
        r for r in db.explore_node(entry["id"], depth=depth)
        if r.get("direction") == "outward"
    ]
    node_map, raw_edges = _subgraph(entry, relations)
    steps = _step_layers(entry["id"], raw_edges, len(node_map))
    kept_ids, kept_raw, truncation = _apply_budget(
        node_map, raw_edges, entry["id"], steps, max_nodes, depth
    )
    fallback_step = (max(steps.values()) if steps else 0) + 1
    # Budget may drop an entire layer; renumber the kept layers compactly so
    # step numbers stay contiguous 1..k (validator I8) while preserving the
    # original BFS ordering.
    kept_steps = sorted({steps.get(nid, fallback_step) for nid in kept_ids})
    remap = {old: i + 1 for i, old in enumerate(kept_steps)}
    nodes: List[Dict[str, Any]] = []
    for nid in kept_ids:
        data = node_map[nid]
        node: Dict[str, Any] = {
            "id": nid,
            "label": data["label"],
            "step": remap[steps.get(nid, fallback_step)],
            "role": data["role"],
            "path": data["path"],
        }
        if data.get("entry"):
            node["entry"] = True
        if data.get("evidence"):
            node["evidence"] = data["evidence"]
        nodes.append(node)

    edges = [
        {
            "src": e["src"],
            "dst": e["dst"],
            "kind": _edge_kind(e["relation"]),
            "weight": int(e["weight"]),
        }
        for e in sorted(kept_raw, key=lambda x: (x["src"], x["dst"], x["relation"]))
    ]

    view: Dict[str, Any] = {
        "layout": "flow",
        "title": f"Flow: {target.strip()}",
        "project": project,
        "generated_from": target.strip(),
        "nodes": nodes,
        "edges": edges,
    }
    if lanes == "module":
        view["lanes"] = _module_lanes(nodes)
    positions = layout_flow(
        nodes, edges, entry["id"], lanes=view.get("lanes"), width=1440
    )
    canvas = positions.pop("canvas")
    view["positions"] = {k: list(v) for k, v in sorted(positions.items())}
    view["canvas"] = list(canvas)
    view["truncation"] = truncation
    return view


def generate_flow_html(
    db: Any,
    target: str,
    project: str,
    depth: int = DEFAULT_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    lanes: str = "none",
) -> str:
    """Build + validate (fail-closed, I8); raise ValueError on any violation."""
    view = build_flow_view(db, target, project, depth=depth, max_nodes=max_nodes, lanes=lanes)
    violations = validate(view)
    if violations:
        raise ValueError("arch flow view validation failed: " + "; ".join(violations))
    return render_html(view)
