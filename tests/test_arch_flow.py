"""Stage-2 tests for the arch flow view: budget truncation (§4.3), BFS step
contiguity, fail-closed validation (I8), honesty on unresolved targets (I5),
lanes grouping, and flow-render determinism (I3). Extraction tests use a real
``Database`` seeded in tmp_path — no repo DB dependency; layout/validator
tests are pure in-memory fakes.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from sot_graph.db import Database
from sot_graph.export.arch_flow import (
    UnresolvedFlowTarget,
    _step_layers,
    build_flow_view,
    generate_flow_html,
    resolve_flow_target,
)
from sot_graph.export.arch_html import generate_arch_html, validate
from sot_graph.export.arch_layout import CARD_H, CARD_W, layout_flow
from sot_graph.cli import cmd_arch


def _seed_db(tmp_path: Path) -> Database:
    """5-node call graph: cli -> search -> engine -> db, cli -> db."""
    db = Database(str(tmp_path / ".sot" / "sot.db"))
    nodes = [
        ("n:cli", "src/pkg/cli.py", "function", "cmd_search", "cmd_search", 10),
        ("n:search", "src/pkg/commands/search.py", "function", "search", "search", 20),
        ("n:engine", "src/pkg/core/engine.py", "function", "run", "run", 30),
        ("n:db", "src/pkg/db.py", "class", "Database", "Database", 40),
        ("n:orph", "src/pkg/util.py", "function", "orphan", "orphan", 50),
    ]
    for nid, path, kind, sym, label, line in nodes:
        db.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, signature, label,"
            " body, keywords, line_start, line_end, col_start, col_end, updated_at)"
            " VALUES (?, ?, ?, ?, NULL, NULL, ?, '', NULL, ?, NULL, NULL, NULL, 0)",
            (nid, path, kind, sym, label, line),
        )
    for s, d, r in [
        ("n:cli", "n:search", "calls"),
        ("n:search", "n:engine", "calls"),
        ("n:engine", "n:db", "calls"),
        ("n:cli", "n:db", "imports"),
    ]:
        db.conn.execute(
            "INSERT INTO graph_edges (path, src, dst, relation, line)"
            " VALUES ('x', ?, ?, ?, NULL)",
            (s, d, r),
        )
    db.conn.commit()
    return db


def _flow_fixture() -> tuple:
    nodes: List[Dict[str, Any]] = [
        {"id": "a", "label": "a", "step": 1, "role": "function", "entry": True},
        {"id": "b", "label": "b", "step": 2, "role": "function"},
        {"id": "c", "label": "c", "step": 2, "role": "function"},
        {"id": "d", "label": "d", "step": 3, "role": "function"},
    ]
    edges: List[Dict[str, Any]] = [
        {"src": "a", "dst": "b", "kind": "calls", "weight": 1},
        {"src": "a", "dst": "c", "kind": "calls", "weight": 1},
        {"src": "b", "dst": "d", "kind": "calls", "weight": 1},
    ]
    return nodes, edges


def test_layout_flow_integer_coords_within_canvas() -> None:
    nodes, edges = _flow_fixture()
    result = layout_flow(nodes, edges, "a", width=1440)
    w, h = result["canvas"]
    assert isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0
    for nid, (x, y) in result.items():
        if nid == "canvas":
            continue
        assert isinstance(x, int) and isinstance(y, int)
        assert 0 <= x <= w - CARD_W
        assert 0 <= y <= h - CARD_H


def test_layout_flow_entry_topmost_and_deterministic() -> None:
    nodes, edges = _flow_fixture()
    r1 = layout_flow(nodes, edges, "a", width=1440)
    r2 = layout_flow(nodes, edges, "a", width=1440)
    assert r1 == r2
    y_by_id = {nid: xy[1] for nid, xy in r1.items() if nid != "canvas"}
    assert y_by_id["a"] < y_by_id["b"] == y_by_id["c"] < y_by_id["d"]


def test_layout_flow_cycle_terminates() -> None:
    # No explicit step fields: exercises the BFS layering fallback on a cycle.
    nodes = [
        {"id": "a", "label": "a", "role": "function", "entry": True},
        {"id": "b", "label": "b", "role": "function"},
    ]
    edges = [
        {"src": "a", "dst": "b", "kind": "calls", "weight": 1},
        {"src": "b", "dst": "a", "kind": "calls", "weight": 1},
    ]
    result = layout_flow(nodes, edges, "a", width=800)
    assert set(result) == {"a", "b", "canvas"}


def test_step_layers_fallback_for_unreachable() -> None:
    edges = [
        {"src": "a", "dst": "b", "kind": "calls", "weight": 1},
        {"src": "x", "dst": "b", "kind": "calls", "weight": 1},
    ]
    steps = _step_layers("a", edges, node_count=3)
    assert steps["a"] == 1 and steps["b"] == 2 and steps["x"] == 3


def test_resolve_flow_target_unresolved() -> None:
    # Fresh empty DB: schema exists, zero nodes.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        empty = Database(str(Path(td) / "sot.db"))
        try:
            with pytest.raises(UnresolvedFlowTarget):
                resolve_flow_target(empty, "no_such_symbol_xyz")
        finally:
            empty.close()


def test_build_flow_view_steps_entry_evidence(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        view = build_flow_view(db, "cmd_search", project="p")
        assert view["layout"] == "flow"
        entries = [n for n in view["nodes"] if n.get("entry")]
        assert len(entries) == 1 and entries[0]["id"] == "n:cli"
        steps = sorted({n["step"] for n in view["nodes"]})
        assert steps == list(range(1, len(steps) + 1))
        assert validate(view) == []
        by_id = {n["id"]: n for n in view["nodes"]}
        assert by_id["n:cli"]["evidence"] == "src/pkg/cli.py:10"
        kinds = {e["kind"] for e in view["edges"]}
        assert kinds <= {"calls", "imports", "adapter", "api"}
    finally:
        db.close()


def test_budget_drops_nodes_and_their_edges(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        view = build_flow_view(db, "cmd_search", project="p", max_nodes=3)
        trunc = view["truncation"]
        assert trunc["capped"] is True
        assert trunc["shown"] == 3 and trunc["total"] == 4
        kept = {n["id"] for n in view["nodes"]}
        assert len(kept) == 3 and "n:cli" in kept
        for e in view["edges"]:
            assert e["src"] in kept and e["dst"] in kept
        assert validate(view) == []
    finally:
        db.close()


def test_no_budget_no_truncation(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        view = build_flow_view(db, "cmd_search", project="p")
        assert view["truncation"] == {
            "capped": False, "shown": 4, "total": 4, "hint_depth": 3,
        }
    finally:
        db.close()


def test_lanes_group_by_module(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        view = build_flow_view(db, "cmd_search", project="p", lanes="module")
        lanes = view["lanes"]
        assert [ln["label"] for ln in lanes] == sorted(ln["label"] for ln in lanes)
        member_ids = [nid for ln in lanes for nid in ln["nodes"]]
        assert sorted(member_ids) == sorted(n["id"] for n in view["nodes"])
        by_label = {ln["label"]: set(ln["nodes"]) for ln in lanes}
        assert by_label["pkg"] == {"n:cli", "n:db"}
        assert by_label["commands"] == {"n:search"}
    finally:
        db.close()


def test_validate_rejects_multiple_entry(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        view = build_flow_view(db, "cmd_search", project="p")
        view["nodes"][1]["entry"] = True
        violations = validate(view)
        assert any("exactly one entry" in v for v in violations)
    finally:
        db.close()


def test_validate_rejects_step_gap(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        view = build_flow_view(db, "cmd_search", project="p")
        for n in view["nodes"]:
            if n["step"] == 2:
                n["step"] = 5
        violations = validate(view)
        assert any("contiguous" in v for v in violations)
    finally:
        db.close()


def test_flow_render_deterministic_and_self_contained(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        h1 = generate_flow_html(db, "cmd_search", project="p")
        h2 = generate_flow_html(db, "cmd_search", project="p")
        assert h1 == h2
        assert "http://" not in h1 and "https://" not in h1 and "fetch(" not in h1
        assert "truncated" not in h1  # uncapped view has no badge
        assert "step" in h1 and "ENTRY" in h1
    finally:
        db.close()


def test_flow_passport_blob_parsable_and_counts(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        view = build_flow_view(db, "cmd_search", project="p")
        html = generate_flow_html(db, "cmd_search", project="p")
        match = re.search(
            r'<script type="application/json" id="arch-data">(.*?)</script>',
            html,
            re.S,
        )
        assert match, "passport JSON blob missing from flow HTML"
        blob = json.loads(match.group(1))
        assert len(blob) == len(view["nodes"])
        refs = sum(len(n["in"]) + len(n["out"]) for n in blob)
        assert refs == 2 * len(view["edges"])
        by_id = {n["id"]: n for n in blob}
        cli = by_id["n:cli"]
        assert len(cli["out"]) == 2 and cli["in"] == []
        assert cli["step"] == 1 and cli["evidence"] == "src/pkg/cli.py:10"
        assert "step" in cli and "tier" not in cli
    finally:
        db.close()


def test_flow_truncation_badge_rendered(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        html = generate_flow_html(db, "cmd_search", project="p", max_nodes=3)
        assert "truncated" in html and "3/4" in html
    finally:
        db.close()


def test_cmd_arch_flow_unresolved_exit2_no_file(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        out = tmp_path / "flow.html"
        args = argparse.Namespace(
            flow="no_such_symbol_xyz", output=str(out), depth=2, max_nodes=10,
            lanes="none", open=False, scope=None,
        )
        rc = cmd_arch(args, db, str(tmp_path))
        assert rc == 2
        assert not out.exists()
    finally:
        db.close()


def test_cmd_arch_flow_writes_file(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        out = tmp_path / "flow.html"
        args = argparse.Namespace(
            flow="cmd_search", output=str(out), depth=3, max_nodes=60,
            lanes="module", open=False, scope=None,
        )
        rc = cmd_arch(args, db, str(tmp_path))
        assert rc == 0
        assert out.exists() and out.stat().st_size > 0
    finally:
        db.close()


def test_tiered_view_still_renders(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        from sot_graph.analytics.graph import AnalyticsGraph

        graph = AnalyticsGraph.from_database(db)
        html = generate_arch_html(graph, title="T", project="p")
        assert "tiers" in html
    finally:
        db.close()
