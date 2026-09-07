"""Stage-1 tests for the arch HTML renderer: determinism (I3), layout
invariants, fail-closed validation (I8), self-containment (I2), and design
tokens per contract §4.4. Pure in-memory fakes — no DB, no network.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.export.arch_html import build_arch_view, generate_arch_html, render_html, validate
from sot_graph.export.arch_layout import CARD_H, CARD_W, layout_tiered, tier_assign


def _fake_graph() -> AnalyticsGraph:
    """10 nodes across 4 tiers (cli/core/storage/export), 12 edges."""
    g = AnalyticsGraph()
    paths: Dict[str, str] = {
        "cli:run": "src/sot_graph/cli.py",
        "cli:cmd_search": "src/sot_graph/commands/search.py",
        "core:reconciler": "src/sot_graph/reconciler.py",
        "core:verifier": "src/sot_graph/verifier.py",
        "core:evidence": "src/sot_graph/evidence.py",
        "core:envelope": "src/sot_graph/envelope.py",
        "core:watcher": "src/sot_graph/watcher.py",
        "storage:db": "src/sot_graph/db.py",
        "storage:snapshot": "src/sot_graph/snapshot.py",
        "export:scip": "src/sot_graph/export/scip.py",
    }
    for nid, p in paths.items():
        g.add_node(nid, label=nid.split(":")[-1], kind="symbol", path=p, line_start=10)
    edges: List[Any] = [
        ("cli:run", "cli:cmd_search", "calls"),
        ("cli:run", "core:reconciler", "calls"),
        ("cli:cmd_search", "core:verifier", "calls"),
        ("cli:cmd_search", "core:evidence", "calls"),
        ("core:reconciler", "core:envelope", "calls"),
        ("core:reconciler", "storage:db", "calls"),
        ("core:verifier", "core:envelope", "imports"),
        ("core:evidence", "storage:db", "calls"),
        ("core:envelope", "storage:db", "calls"),
        ("core:watcher", "core:reconciler", "calls"),
        ("storage:db", "storage:snapshot", "imports"),
        ("export:scip", "storage:db", "adapter"),
    ]
    for s, d, rel in edges:
        g.add_edge(s, d, relation=rel)
    return g


def test_tier_assign_heuristic() -> None:
    assert tier_assign({"path": "src/sot_graph/cli.py"}) == "cli"
    assert tier_assign({"path": "src/x/adapters/engine.py"}) == "adapters"
    assert tier_assign({"path": "src/x/providers/scip.py"}) == "providers"
    assert tier_assign({"path": "src/sot_graph/db.py"}) == "storage"
    assert tier_assign({"path": "src/sot_graph/export/scip.py"}) == "export"
    assert tier_assign({"path": "src/sot_graph/verifier.py"}) == "core"


def test_layout_integer_coords_within_canvas() -> None:
    g = _fake_graph()
    nodes: List[Dict[str, Any]] = [
        {"id": nid, "label": nid, "tier": tier_assign(data), "role": "symbol"}
        for nid, data in g.nodes.items()
    ]
    result = layout_tiered(nodes, list(g.edges), width=1440)
    w, h = result["canvas"]
    assert isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0
    for nid, (x, y) in result.items():
        if nid == "canvas":
            continue
        assert isinstance(x, int) and isinstance(y, int)
        assert 0 <= x <= w - CARD_W
        assert 0 <= y <= h - CARD_H


def test_render_deterministic_byte_equal() -> None:
    html1 = generate_arch_html(_fake_graph(), title="T", project="p")
    html2 = generate_arch_html(_fake_graph(), title="T", project="p")
    assert html1 == html2
    view = build_arch_view(_fake_graph(), "T", "p")
    assert render_html(view) == html1


def test_validate_rejects_dangling_edge() -> None:
    view = build_arch_view(_fake_graph(), "T", "p")
    view["edges"].append({"src": "cli:run", "dst": "ghost:node", "kind": "calls", "weight": 1})
    violations = validate(view)
    assert any("ghost:node" in v for v in violations)


def test_validate_rejects_empty_nodes() -> None:
    violations = validate({"nodes": [], "edges": [], "positions": {}, "canvas": [10, 10]})
    assert any("empty" in v for v in violations)


def test_rendered_html_self_contained() -> None:
    html = generate_arch_html(_fake_graph(), title="T", project="p")
    assert "http://" not in html
    assert "https://" not in html
    assert "fetch(" not in html


def test_design_tokens_present() -> None:
    html = generate_arch_html(_fake_graph(), title="T", project="p")
    for token in ("#020617", "#0F172A", "#1E293B", "#94A3B8", "#22D3EE", "#34D399", "#A78BFA", "#FBBF24"):
        assert token in html
    assert 'data-theme="dark"' in html
    assert "theme-toggle" in html


def test_fail_closed_on_dangling_edge() -> None:
    g = _fake_graph()
    g.add_edge("cli:run", "ghost:node", relation="calls")
    with pytest.raises(ValueError) as exc:
        generate_arch_html(g, title="T", project="p")
    assert "ghost:node" in str(exc.value)


def test_verdict_omitted_when_absent() -> None:
    view = build_arch_view(_fake_graph(), "T", "p")
    assert all("verdict" not in n for n in view["nodes"])
