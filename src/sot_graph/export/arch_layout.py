"""Deterministic tiered layout for architecture views, zero-dep and pure (no I/O).

Heuristic is v1 and purely path-based: a node's architectural tier is guessed
from its module path (see :data:`TIERS` / :func:`tier_assign`). It is a lexical
hint for presentation only — never a compiler-resolved fact. Node positions are
integer pixels; identical inputs always produce identical output (no random,
no wall-clock, stable dict iteration over sorted structures).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

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
