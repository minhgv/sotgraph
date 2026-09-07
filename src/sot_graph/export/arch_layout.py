"""Deterministic tiered layout for architecture views, zero-dep and pure (no I/O).

Heuristic is v1 and purely path-based: a node's architectural tier is guessed
from its module path (see :data:`TIERS` / :func:`tier_assign`). It is a lexical
hint for presentation only — never a compiler-resolved fact. Node positions are
integer pixels; identical inputs always produce identical output (no random,
no wall-clock, stable dict iteration over sorted structures).
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Tuple

# Display order, top row -> bottom row.
TIERS: Tuple[str, ...] = ("cli", "adapters", "providers", "core", "storage", "export")

TIER_LABELS: Dict[str, str] = {
    "cli": "CLI / ENTRY",
    "adapters": "ADAPTERS",
    "providers": "PROVIDERS",
    "core": "CORE",
    "storage": "STORAGE",
    "export": "EXPORT",
}

# Card geometry (px).
CARD_W = 200
CARD_H = 64
GUTTER_X = 16
GUTTER_Y = 44
LABEL_W = 150  # left gutter reserved for tier labels
PAD_X = 24
PAD_Y = 24

_SWEEP_COUNT = 3


def _match_text(node: Dict[str, Any]) -> str:
    """Lowercased path (preferred) with node id as fallback for matching."""
    path = str(node.get("path") or "").replace("\\", "/").lower()
    if path:
        return path
    return str(node.get("id") or "").replace("\\", "/").lower()


def tier_assign(node: Dict[str, Any]) -> str:
    """Assign an architectural tier from the module path (v1 path heuristic).

    Ordered rules, first match wins:
      cli      — path ends with ``cli.py`` or contains a ``commands`` segment
      adapters — path contains ``adapters/``
      providers— path contains ``providers/``
      storage  — base file is ``db.py``/``snapshot.py``/``store*.py``/``sqlite*``
                 or path contains ``storage/``/``store/``
      export   — path contains ``export/``
      core     — everything else (fallback)
    """
    text = _match_text(node)
    base = text.rsplit("/", 1)[-1]
    if base == "cli.py" or "/commands" in text or base.startswith("cli"):
        return "cli"
    if "/adapters/" in text or base.startswith("adapter"):
        return "adapters"
    if "/providers/" in text or base.startswith("provider"):
        return "providers"
    if (
        "/storage/" in text
        or "/store/" in text
        or base in ("db.py", "snapshot.py")
        or base.startswith("store")
        or base.startswith("sqlite")
    ):
        return "storage"
    if "/export/" in text or base.startswith("export"):
        return "export"
    return "core"


def _initial_order(tier_nodes: List[str]) -> List[str]:
    return sorted(tier_nodes)


def _barycenter(
    nid: str,
    order: List[str],
    neighbors: Dict[str, List[str]],
) -> float:
    """Mean position of cross-tier neighbors; unchanged position if isolated."""
    pos = {n: i for i, n in enumerate(order)}
    vals = [pos[n] for n in neighbors.get(nid, []) if n in pos]
    if not vals:
        # Isolated within the reference set: ties resolved stably by id.
        return float(pos.get(nid, 0))
    return sum(vals) / len(vals)


def layout_tiered(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    width: int = 1440,
) -> Dict[str, Any]:
    """Place nodes in tier rows; in-tier order minimizes crossings.

    Deterministic barycenter method: initial in-tier order is sorted by node
    id, then ``_SWEEP_COUNT`` sweeps alternate left-to-right / right-to-left.
    Cards wrap into multiple rows per tier when the row exceeds the canvas
    width. Returns ``{node_id: (x, y), ..., "canvas": (w, h)}`` with integer
    pixel coordinates.
    """
    tiers: Dict[str, List[str]] = {t: [] for t in TIERS}
    by_id: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        nid = str(n["id"])
        by_id[nid] = n
        tiers.setdefault(tier_assign(n), []).append(nid)

    order: Dict[str, List[str]] = {
        t: _initial_order(ids) for t, ids in tiers.items() if ids
    }

    # Cross-tier adjacency (undirected, tier-agnostic) for barycenter sweeps.
    neighbors: Dict[str, List[str]] = {str(n["id"]): [] for n in nodes}
    for e in edges:
        s, d = str(e.get("src")), str(e.get("dst"))
        if s in neighbors and d in neighbors and s != d:
            neighbors[s].append(d)
            neighbors[d].append(s)

    tier_seq = [t for t in TIERS if t in order]
    for _ in range(_SWEEP_COUNT):
        for direction in (1, -1):
            for ti in range(len(tier_seq)) if direction == 1 else range(len(tier_seq) - 1, -1, -1):
                t = tier_seq[ti]
                # Fixed reference = other tiers' current order, combined.
                ref: List[str] = []
                for ot in tier_seq:
                    if ot != t:
                        ref.extend(order[ot])
                ref_pos = {n: i for i, n in enumerate(ref)}
                nbr: Dict[str, List[str]] = {nid: [] for nid in order[t]}
                for e in edges:
                    s, d = str(e.get("src")), str(e.get("dst"))
                    if s in nbr and d not in nbr:
                        nbr[s].append(d)
                    if d in nbr and s not in nbr:
                        nbr[d].append(s)
                order[t] = sorted(
                    order[t],
                    key=lambda nid: (
                        _barycenter(nid, ref, nbr) if ref else 0.0,
                        ref_pos.get(nid, 0),
                        nid,
                    ),
                )

    max_cols = max(1, (width - LABEL_W - 2 * PAD_X) // (CARD_W + GUTTER_X))
    positions: Dict[str, Tuple[int, int]] = {}
    y = PAD_Y
    for t in tier_seq:
        ids = order[t]
        rows = [ids[i : i + max_cols] for i in range(0, len(ids), max_cols)]
        for row in rows:
            x = LABEL_W + PAD_X
            for nid in row:
                positions[nid] = (int(x), int(y))
                x += CARD_W + GUTTER_X
            y += CARD_H + GUTTER_Y
        y += GUTTER_Y // 2  # extra breathing room between tiers

    canvas_w = int(width)
    canvas_h = int(y - (GUTTER_Y // 2) - GUTTER_Y + PAD_Y) if tier_seq else int(PAD_Y * 2)
    positions["canvas"] = (canvas_w, canvas_h)
    return positions


LANE_BAND = 28  # top headroom reserved for swimlane labels


def _flow_layers(
    ids: List[str],
    entry_id: str,
    edges: List[Dict[str, Any]],
    nodes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    """Layer per node. When nodes carry an explicit ``step`` (flow IR built by
    the extractor's BFS from the entry) it is trusted 1:1; otherwise layers
    are recomputed as BFS depth from the entry (visited set terminates on
    cycles), with nodes not reachable from the entry parked one layer below
    the deepest reachable one."""
    layer: Dict[str, int] = {}
    idset = set(ids)
    if entry_id in idset:
        adj: Dict[str, List[str]] = {}
        for e in edges:
            s, d = str(e.get("src")), str(e.get("dst"))
            if s in idset and d in idset:
                adj.setdefault(s, []).append(d)
        for nbrs in adj.values():
            nbrs.sort()
        layer[entry_id] = 0
        queue: deque = deque([entry_id])
        while queue:
            cur = queue.popleft()
            for nxt in adj.get(cur, []):
                if nxt not in layer:
                    layer[nxt] = layer[cur] + 1
                    queue.append(nxt)
    if layer:
        deepest = max(layer.values())
        for nid in ids:
            layer.setdefault(nid, deepest + 1)
    else:  # no entry on the canvas: deterministic flat layering by id
        for i, nid in enumerate(sorted(ids)):
            layer[nid] = 0
    if nodes:
        explicit = {
            str(n["id"]): int(n["step"]) - 1
            for n in nodes
            if n.get("step") is not None
        }
        if explicit:
            return {nid: explicit.get(nid, layer.get(nid, 0)) for nid in ids}
    return layer


def layout_flow(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    entry_id: str,
    lanes: Optional[List[Dict[str, Any]]] = None,
    width: int = 1440,
) -> Dict[str, Any]:
    """Top-down stepped layout: BFS layers from the entry, barycenter sweeps
    within layers (same method as :func:`layout_tiered`), optional module
    swimlanes that order nodes by lane inside each layer and reserve a label
    band at the top. Deterministic: sorted iteration, integer pixel output."""
    ids = [str(n["id"]) for n in nodes]
    layer = _flow_layers(ids, entry_id, edges, nodes=nodes)

    groups: Dict[int, List[str]] = {}
    for nid in ids:
        groups.setdefault(layer[nid], []).append(nid)
    lane_index: Dict[str, int] = {}
    if lanes:
        for i, lane in enumerate(lanes):
            for nid in lane.get("nodes") or []:
                lane_index[str(nid)] = i

    order: Dict[int, List[str]] = {}
    for ln, members in groups.items():
        order[ln] = sorted(
            members,
            key=lambda nid: (lane_index.get(nid, 1 << 30), nid),
        )

    neighbors: Dict[str, List[str]] = {nid: [] for nid in ids}
    for e in edges:
        s, d = str(e.get("src")), str(e.get("dst"))
        if s in neighbors and d in neighbors and s != d:
            neighbors[s].append(d)
            neighbors[d].append(s)

    layer_seq = sorted(order)
    for _ in range(_SWEEP_COUNT):
        for direction in (1, -1):
            seq = layer_seq if direction == 1 else list(reversed(layer_seq))
            for ln in seq:
                ref: List[str] = []
                for ol in layer_seq:
                    if ol != ln:
                        ref.extend(order[ol])
                ref_pos = {n: i for i, n in enumerate(ref)}
                nbr: Dict[str, List[str]] = {nid: [] for nid in order[ln]}
                for e in edges:
                    s, d = str(e.get("src")), str(e.get("dst"))
                    if s in nbr and d not in nbr:
                        nbr[s].append(d)
                    if d in nbr and s not in nbr:
                        nbr[d].append(s)
                order[ln] = sorted(
                    order[ln],
                    key=lambda nid: (
                        lane_index.get(nid, 1 << 30),
                        _barycenter(nid, ref, nbr) if ref else 0.0,
                        ref_pos.get(nid, 0),
                        nid,
                    ),
                )

    max_cols = max(1, (width - 2 * PAD_X) // (CARD_W + GUTTER_X))
    positions: Dict[str, Tuple[int, int]] = {}
    y = PAD_Y + (LANE_BAND if lanes else 0)
    for ln in layer_seq:
        ids_ln = order[ln]
        rows = [ids_ln[i : i + max_cols] for i in range(0, len(ids_ln), max_cols)]
        for row in rows:
            x = PAD_X
            for nid in row:
                positions[nid] = (int(x), int(y))
                x += CARD_W + GUTTER_X
            y += CARD_H + GUTTER_Y
        y += GUTTER_Y // 2  # breathing room between steps

    canvas_w = int(width)
    canvas_h = int(y - (GUTTER_Y // 2) - GUTTER_Y + PAD_Y) if layer_seq else int(PAD_Y * 2)
    positions["canvas"] = (canvas_w, canvas_h)
    return positions
