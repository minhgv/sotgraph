"""Tests for the module-level rollup used by ``sotgraph arch --level module``."""
from __future__ import annotations

import pytest

from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.export.arch_module import (
    generate_module_html,
    module_key,
    rollup_modules,
)

PREFIX = "/repo/src/pkg"


def _sample_graph() -> AnalyticsGraph:
    g = AnalyticsGraph()
    g.add_node("n1", label="run", kind="function", path="/repo/src/pkg/cli.py")
    g.add_node("n2", label="main", kind="function", path="/repo/src/pkg/cli.py")
    g.add_node("n3", label="Database", kind="class", path="/repo/src/pkg/db.py")
    g.add_node("n4", label="store", kind="function", path="/repo/src/pkg/db.py")
    g.add_node("n5", label="render", kind="function", path="/repo/src/pkg/export/html.py")
    g.add_node("n6", label="outside", kind="function", path="/repo/tests/test_x.py")
    g.add_edge("n1", "n3", relation="calls")
    g.add_edge("n2", "n3", relation="imports")
    g.add_edge("n3", "n4", relation="calls")  # intra-module: dropped
    g.add_edge("n5", "n3", relation="imports")
    g.add_edge("n1", "n6", relation="calls")  # endpoint outside prefix: dropped
    return g


class TestModuleKey:
    def test_directory_and_file_modules(self):
        assert module_key(f"{PREFIX}/export/html.py", PREFIX) == "export"
        assert module_key(f"{PREFIX}/db.py", PREFIX) == "db"

    def test_package_markers_do_not_form_modules(self):
        assert module_key(f"{PREFIX}/__init__.py", PREFIX) is None
        assert module_key(f"{PREFIX}/__main__.py", PREFIX) is None

    def test_outside_prefix_is_none(self):
        assert module_key("/repo/tests/test_x.py", PREFIX) is None
        assert module_key("", PREFIX) is None


class TestRollup:
    def test_counts_and_aggregates(self):
        out = rollup_modules(_sample_graph(), PREFIX)
        assert sorted(out.nodes) == ["module/cli", "module/db", "module/export"]
        db = out.nodes["module/db"]
        assert db["symbol_count"] == 2
        assert db["class_count"] == 1
        assert db["kind"] == "module"

    def test_edges_weighted_and_self_loops_dropped(self):
        out = rollup_modules(_sample_graph(), PREFIX)
        pairs = {(e["src"], e["dst"]): e for e in out.edges}
        assert set(pairs) == {("module/cli", "module/db"), ("module/export", "module/db")}
        assert pairs[("module/cli", "module/db")]["weight"] == 2  # ties broken by name
        for e in out.edges:
            assert e["src"] != e["dst"]

    def test_deterministic(self):
        a = rollup_modules(_sample_graph(), PREFIX)
        b = rollup_modules(_sample_graph(), PREFIX)
        assert a.nodes == b.nodes
        assert a.edges == b.edges


class TestGenerateModuleHtml:
    def test_renders_and_is_deterministic(self):
        g = _sample_graph()
        a = generate_module_html(g, "T", "pkg", PREFIX)
        b = generate_module_html(g, "T", "pkg", PREFIX)
        assert a == b
        assert "module" in a
        assert 'src="http' not in a and 'href="http' not in a  # single-file, no refs

    def test_empty_graph_fails_closed(self):
        with pytest.raises(ValueError):
            generate_module_html(AnalyticsGraph(), "T", "pkg", PREFIX)
