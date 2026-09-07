"""Self-contained architecture HTML renderer (stage 1: tiered arch view).

Builds a typed IR (:func:`build_arch_view`), validates it fail-closed
(:func:`validate`), and renders a single deterministic HTML file with inline
CSS/SVG only (:func:`render_html`). No network resources, no timestamps, no
randomness — identical graph state yields byte-identical output. Design
tokens follow the staged contract §4.4 (slate canvas + semantic palette,
mono typography, flat cards with 1px borders, glow only on focus).

The verdict ring is a rendering hook: nodes carrying a ``verdict`` field get
a colored outer ring ([STRONG]/[WEAK]/[REBUILT]/[REMOVED]); ``AnalyticsGraph``
does not expose verdicts today, so the field is simply omitted when absent.
"""
from __future__ import annotations

import html as html_lib
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.export.arch_layout import (
    CARD_H,
    CARD_W,
    TIERS,
    TIER_LABELS,
    layout_tiered,
    tier_assign,
)

_VERDICT_COLORS: Dict[str, str] = {
    "STRONG": "#34D399",
    "WEAK": "#FBBF24",
    "REBUILT": "#FB923C",
    "REMOVED": "#FB7185",
}

_KIND_STYLE: Dict[str, Tuple[str, str]] = {
    # kind -> (color, dash pattern)
    "calls": ("#22D3EE", ""),
    "imports": ("#34D399", "6 4"),
    "adapter": ("#FBBF24", "2 4"),
    "api": ("#A78BFA", "3 3"),
}

_TIER_COLORS: Dict[str, str] = {
    "cli": "#22D3EE",
    "adapters": "#FBBF24",
    "providers": "#FBBF24",
    "core": "#34D399",
    "storage": "#A78BFA",
    "export": "#FBBF24",
}


def _edge_kind(relation: str) -> str:
    rel = (relation or "").lower()
    if "import" in rel:
        return "imports"
    if "adapter" in rel:
        return "adapter"
    if rel == "api":
        return "api"
    return "calls"


def _evidence(data: Dict[str, Any]) -> str:
    path = str(data.get("path") or "")
    if not path:
        return ""
    line = data.get("line_start")
    return f"{path}:{int(line)}" if line else path


def build_arch_view(
    graph: AnalyticsGraph,
    title: str,
    project: str,
    scope: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the tiered ``ArchView`` IR from an :class:`AnalyticsGraph`."""
    nodes: List[Dict[str, Any]] = []
    for nid in sorted(graph.nodes):
        data = graph.nodes[nid]
        node: Dict[str, Any] = {
            "id": nid,
            "label": str(data.get("label") or nid),
            "tier": tier_assign(data),
            "role": str(data.get("kind") or "symbol"),
        }
        sym_count = data.get("symbol_count", data.get("symbols"))
        if isinstance(sym_count, int):
            node["symbols"] = sym_count
        verdict = data.get("verdict")
        if verdict:
            node["verdict"] = str(verdict)
        ev = _evidence(data)
        if ev:
            node["evidence"] = ev
        nodes.append(node)

    edges: List[Dict[str, Any]] = []
    for e in sorted(
        graph.edges, key=lambda x: (str(x.get("src")), str(x.get("dst")), str(x.get("relation")))
    ):
        edges.append(
            {
                "src": str(e.get("src")),
                "dst": str(e.get("dst")),
                "kind": _edge_kind(str(e.get("relation") or "")),
                "weight": int(e.get("weight", 1) or 1),
            }
        )

    positions = layout_tiered(nodes, edges, width=1440)
    canvas = positions.pop("canvas")
    return {
        "layout": "tiered",
        "title": title,
        "project": project,
        "generated_from": scope or "whole repository",
        "nodes": nodes,
        "edges": edges,
        "positions": {k: list(v) for k, v in sorted(positions.items())},
        "canvas": list(canvas),
    }


def validate(view: Dict[str, Any]) -> List[str]:
    """Return a list of IR violations (empty list = valid)."""
    violations: List[str] = []
    nodes = view.get("nodes") or []
    if not nodes:
        violations.append("nodes list is empty")
        return violations
    ids = {str(n.get("id")) for n in nodes}
    for e in view.get("edges") or []:
        if str(e.get("src")) not in ids:
            violations.append(f"edge references unknown src node: {e.get('src')}")
        if str(e.get("dst")) not in ids:
            violations.append(f"edge references unknown dst node: {e.get('dst')}")
    canvas = view.get("canvas") or [0, 0]
    w, h = int(canvas[0]), int(canvas[1])
    for nid, xy in sorted((view.get("positions") or {}).items()):
        x, y = int(xy[0]), int(xy[1])
        if not (0 <= x <= w - CARD_W and 0 <= y <= h - CARD_H):
            violations.append(f"node outside canvas: {nid} at ({x}, {y})")
    return violations


_CSS = """
:root { --canvas:#020617; --surface:#0F172A; --border:#1E293B; --ink:#FFFFFF;
        --muted:#94A3B8; }
:root[data-theme="light"] { --canvas:#F8FAFC; --surface:#FFFFFF; --border:#CBD5E1;
        --ink:#0F172A; --muted:#475569; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--canvas); color:var(--ink); font-family:ui-monospace,
       "JetBrains Mono","SF Mono",Menlo,monospace; }
header { display:flex; align-items:baseline; gap:24px; padding:20px 28px;
         border-bottom:1px solid var(--border); }
h1 { font-size:16px; font-weight:700; text-transform:uppercase; letter-spacing:2px; }
.meta { color:var(--muted); font-size:12px; letter-spacing:1px; text-transform:uppercase; }
#theme-toggle { margin-left:auto; background:var(--surface); color:var(--muted);
         border:1px solid var(--border); border-radius:6px; padding:6px 12px;
         font:inherit; font-size:11px; letter-spacing:1px; cursor:pointer; }
#theme-toggle:hover { color:var(--ink); }
#legend { display:flex; flex-wrap:wrap; gap:18px; padding:12px 28px;
          border-bottom:1px solid var(--border); font-size:11px; color:var(--muted);
          text-transform:uppercase; letter-spacing:1px; }
#legend .item { display:inline-flex; align-items:center; gap:6px; }
.sw { width:10px; height:10px; border-radius:3px; display:inline-block; }
.ln { width:22px; height:0; border-top:2px solid; display:inline-block; }
#stage { overflow:auto; padding:16px; }
svg { display:block; background:var(--canvas); }
.card rect { fill:var(--surface); stroke-width:1px; transition:filter 150ms ease; }
.card:hover rect, .card:focus rect { filter:drop-shadow(0 0 4px var(--muted)); }
.card text { fill:var(--ink); font-family:inherit; }
.card .sub { fill:var(--muted); }
.tier-label { fill:var(--muted); font-size:11px; letter-spacing:2px;
              text-transform:uppercase; }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
"""


def _esc(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


def _legend_html() -> str:
    items: List[str] = []
    for t in TIERS:
        items.append(
            '<span class="item"><span class="sw" style="background:'
            + _TIER_COLORS[t]
            + '"></span>'
            + _esc(TIER_LABELS[t])
            + "</span>"
        )
    for kind in ("calls", "imports", "adapter", "api"):
        color, dash = _KIND_STYLE[kind]
        line_style = "dotted" if dash.startswith("2") else "dashed" if dash else "solid"
        items.append(
            '<span class="item"><span class="ln" style="border-color:' + color
            + ";border-top-style:" + line_style + ';"></span>' + kind.upper() + "</span>"
        )
    return '<div id="legend">' + "".join(items) + "</div>"


def _render_edges(view: Dict[str, Any]) -> List[str]:
    pos = view["positions"]
    parts: List[str] = []
    for e in view["edges"]:
        s, d = pos[e["src"]], pos[e["dst"]]
        kind = e["kind"]
        color, dash = _KIND_STYLE.get(kind, _KIND_STYLE["calls"])
        if d[1] > s[1]:
            x1, y1 = s[0] + CARD_W // 2, s[1] + CARD_H
            x2, y2 = d[0] + CARD_W // 2, d[1]
            dy = max(20, (y2 - y1) // 2)
            path = "M %d %d C %d %d, %d %d, %d %d" % (x1, y1, x1, y1 + dy, x2, y2 - dy, x2, y2)
        else:
            if s[0] <= d[0]:
                x1, y1 = s[0] + CARD_W, s[1] + CARD_H // 2
                x2, y2 = d[0], d[1] + CARD_H // 2
            else:
                x1, y1 = s[0], s[1] + CARD_H // 2
                x2, y2 = d[0] + CARD_W, d[1] + CARD_H // 2
            dx = max(20, abs(x2 - x1) // 2)
            path = "M %d %d C %d %d, %d %d, %d %d" % (x1, y1, x1 + dx, y1, x2 - dx, y2, x2, y2)
        dash_attr = ' stroke-dasharray="' + dash + '"' if dash else ""
        parts.append(
            '<path d="' + path + '" fill="none" stroke="' + color
            + '" stroke-opacity="0.35" stroke-width="1.2" marker-end="url(#arr-'
            + kind + ')"' + dash_attr + "><title>" + _esc(e["src"] + " -" + kind
            + "-> " + e["dst"]) + "</title></path>"
        )
    return parts


def _render_nodes(view: Dict[str, Any]) -> List[str]:
    parts: List[str] = []
    for n in view["nodes"]:
        x, y = view["positions"][n["id"]]
        color = _TIER_COLORS.get(n["tier"], "#94A3B8")
        ring = ""
        if n.get("verdict"):
            v = str(n["verdict"]).upper()
            vc = _VERDICT_COLORS.get(v)
            if vc:
                ring = (
                    '<rect x="%d" y="%d" width="%d" height="%d" rx="11" fill="none" '
                    'stroke="%s" stroke-width="2" stroke-opacity="0.9"/>'
                    % (x - 3, y - 3, CARD_W + 6, CARD_H + 6, vc)
                )
        sub = n["role"] + (f" · {n['symbols']} sym" if "symbols" in n else "")
        tip = n.get("evidence") or n["id"]
        parts.append(
            '<g class="card" tabindex="0">'
            + ring
            + '<rect x="%d" y="%d" width="%d" height="%d" rx="8" stroke="%s"/>'
            % (x, y, CARD_W, CARD_H, color)
            + "<title>" + _esc(tip) + "</title>"
            + '<text x="%d" y="%d" font-size="11" font-weight="700">%s</text>'
            % (x + 12, y + 24, _esc(n["label"][:26]))
            + '<text class="sub" x="%d" y="%d" font-size="10">%s</text>'
            % (x + 12, y + 44, _esc(sub[:32]))
            + "</g>"
        )
    return parts


def _render_tier_labels(view: Dict[str, Any]) -> List[str]:
    rows: Dict[str, int] = {}
    for n in view["nodes"]:
        t = n["tier"]
        y = view["positions"][n["id"]][1]
        if t not in rows or y < rows[t]:
            rows[t] = y
    parts: List[str] = []
    for t in TIERS:
        if t in rows:
            parts.append(
                '<text class="tier-label" x="16" y="%d">%s</text>'
                % (rows[t] + CARD_H // 2, _esc(TIER_LABELS[t]))
            )
    return parts


def render_html(view: Dict[str, Any]) -> str:
    """Render the view to one self-contained HTML string (no external refs)."""
    w, h = int(view["canvas"][0]), int(view["canvas"][1])
    n_edges = len(view["edges"])
    n_tiers = len({n["tier"] for n in view["nodes"]})
    markers: List[str] = []
    for kind in ("calls", "imports", "adapter", "api"):
        color = _KIND_STYLE.get(kind, _KIND_STYLE["calls"])[0]
        markers.append(
            '<marker id="arr-' + kind + '" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path '
            'd="M 0 0 L 10 5 L 0 10 z" fill="' + color + '"/></marker>'
        )
    svg = (
        '<svg width="' + str(w) + '" height="' + str(h) + '" viewBox="0 0 ' + str(w)
        + " " + str(h) + '" role="img" aria-label="' + _esc(view["title"]) + '">'
        + "<defs>" + "".join(markers) + "</defs>"
        + "".join(_render_tier_labels(view))
        + "".join(_render_edges(view))
        + "".join(_render_nodes(view))
        + "</svg>"
    )
    js = (
        '<script>(function(){var b=document.getElementById("theme-toggle");'
        "b.addEventListener(\"click\",function(){var r=document.documentElement;"
        "var toLight=r.getAttribute(\"data-theme\")!==\"light\";"
        "r.setAttribute(\"data-theme\",toLight?\"light\":\"dark\");"
        "b.textContent=toLight?\"\\u25d1 DARK\":\"\\u25d0 LIGHT\";});})();</script>"
    )
    head = (
        "<!DOCTYPE html><html lang=\"en\" data-theme=\"dark\"><head>"
        '<meta charset="utf-8">'
        "<title>" + _esc(view["title"]) + "</title>"
        "<style>" + _CSS + "</style></head><body>"
        "<header><h1>" + _esc(view["title"]) + "</h1>"
        '<span class="meta">project: ' + _esc(view["project"]) + "</span>"
        '<span class="meta">from: ' + _esc(view.get("generated_from", "")) + "</span>"
        '<span class="meta">' + str(len(view["nodes"])) + " nodes · "
        + str(n_edges) + " edges · " + str(n_tiers) + " tiers</span>"
        '<button id="theme-toggle" type="button">&#9680; LIGHT</button></header>'
        + _legend_html()
        + '<div id="stage">' + svg + "</div>"
        + js
        + "</body></html>"
    )
    return head


def generate_arch_html(
    graph: AnalyticsGraph,
    title: str,
    project: str,
    scope: Optional[str] = None,
) -> str:
    """Build + validate (fail-closed, I8); raise ValueError on any violation."""
    view = build_arch_view(graph, title, project, scope=scope)
    violations = validate(view)
    if violations:
        raise ValueError("arch view validation failed: " + "; ".join(violations))
    return render_html(view)
