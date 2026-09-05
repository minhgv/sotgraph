"""test_lambda_comprehension_coverage.py — call ownership for inline scopes.

Coverage fix (advisor P1-1): calls inside lambdas, list/set/dict
comprehensions, generator expressions and (already-covered) nested defs
must be extracted and attributed to the ENCLOSING symbol scope — those
constructs have no symbol of their own.

Precision rule (advisor warning: "đi vào mọi child mù quáng có thể tạo
cạnh sai caller"): the walk is NOT a blind descent. Nested def/class
bodies own their calls (never attributed to the outer function), and
lambda parameters / comprehension targets shadow outer names at their
call sites, so a reused name is classified as a local variable and never
resolves into a false caller edge.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph._vendor.graphify.extract import extract_python  # noqa: E402
from sot_graph.db import Database  # noqa: E402
from sot_graph.extractor import parse_file_graph  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402


def _extract(src: str) -> dict:
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    return extract_python(path)


def _calls(src: str):
    """(caller, callee, line) for every extracted calls edge."""
    result = _extract(src)
    return {
        (e["source"], e["target"], e["source_location"])
        for e in result["edges"] if e["relation"] == "calls"
    }


def _call(src: str, callee: str):
    """The single edge targeting `callee`, or None."""
    hits = [c for c in _calls(src) if c[1] == callee]
    return hits[0] if len(hits) == 1 else None


class TestOwnershipAttribution(unittest.TestCase):
    def test_comprehension_calls_attributed_to_enclosing_function(self):
        src = (
            "def loader(items):\n"
            "    a = [transform(x) for x in items]\n"
            "    b = {check(x) for x in items}\n"
            "    c = {k: cache(k) for k in items}\n"
            "    d = (validate(x) for x in items)\n"
            "    return a, b, c, d\n"
        )
        for callee in ("transform", "check", "cache", "validate"):
            edge = _call(src, callee)
            self.assertIsNotNone(edge, f"{callee}() inside a comprehension is a real call")
            self.assertEqual(edge[0], "loader", f"{callee}() belongs to the enclosing function")

    def test_lambda_calls_attributed_to_enclosing_function(self):
        src = (
            "def loader(items):\n"
            "    mapped = list(map(lambda v: normalize(v), items))\n"
            "    keyed = sorted(items, key=lambda item: score(item))\n"
            "    return mapped, keyed\n"
        )
        self.assertEqual(_call(src, "normalize")[:2], ("loader", "normalize"))
        self.assertEqual(_call(src, "score")[:2], ("loader", "score"))

    def test_nested_comprehension_attributed_once(self):
        src = (
            "def loader(matrix):\n"
            "    flat = [deep(cell) for row in matrix for cell in row]\n"
            "    nested = [[deep(cell) for cell in row] for row in matrix]\n"
            "    return flat, nested\n"
        )
        edges = [c for c in _calls(src) if c[1] == "deep"]
        self.assertTrue(edges, "nested comprehension bodies must be entered")
        for edge in edges:
            self.assertEqual(edge[0], "loader", "inner scopes have no symbol of their own")

    def test_comprehension_condition_and_second_iterable_covered(self):
        src = (
            "def loader(items):\n"
            "    out = [pick(y, x) for x in first(items) if admit(x) for y in more(x)]\n"
            "    return out\n"
        )
        self.assertEqual(_call(src, "first")[:2], ("loader", "first"))
        self.assertEqual(_call(src, "admit")[:2], ("loader", "admit"))
        self.assertEqual(_call(src, "more")[:2], ("loader", "more"))
        self.assertEqual(_call(src, "pick")[:2], ("loader", "pick"))

    def test_attribute_call_inside_comprehension(self):
        src = (
            "def loader(items):\n"
            "    names = [obj.render() for obj in items]\n"
            "    return names\n"
        )
        edge = _call(src, "render")
        self.assertIsNotNone(edge, "attribute calls inside comprehensions are extracted")
        self.assertEqual(edge[0], "loader")

    def test_nested_def_call_not_attributed_to_outer(self):
        """Advisor false-caller case: nested defs own their calls."""
        src = (
            "def outer():\n"
            "    def inner():\n"
            "        return hidden()\n"
            "    return inner()\n"
        )
        calls = _calls(src)
        self.assertIn(("outer.inner", "hidden", "L3"), calls)
        self.assertNotIn(
            ("outer", "hidden", "L3"), calls,
            "a nested def's callees must NOT be duplicated onto the outer function",
        )


class TestInlineScopeShadowing(unittest.TestCase):
    def test_lambda_param_shadowing_prevents_false_edge(self):
        """A lambda param named like an outer callable must stay local."""
        src = (
            "def loader(items):\n"
            "    keyed = sorted(items, key=lambda transform: transform(1))\n"
            "    return keyed\n"
        )
        result = _extract(src)
        edge = next(e for e in result["edges"]
                    if e["relation"] == "calls" and e["target"] == "transform")
        self.assertTrue(edge.get("is_local_var") or edge.get("is_shadowed"),
                        "lambda param shadows the outer name — no project-symbol edge")

    def test_comprehension_target_shadowing_prevents_false_edge(self):
        src = (
            "def loader(items):\n"
            "    out = [helper(x) for helper in items]\n"
            "    return out\n"
        )
        result = _extract(src)
        edge = next(e for e in result["edges"]
                    if e["relation"] == "calls" and e["target"] == "helper")
        self.assertTrue(edge.get("is_local_var") or edge.get("is_shadowed"),
                        "comprehension target shadows the outer name")

    def test_nested_comprehension_reusing_same_name(self):
        """Same target name in outer and inner comprehension stays local."""
        src = (
            "def loader(rows):\n"
            "    out = [[fmt(r) for r in row] for row in rows]\n"
            "    return out\n"
        )
        result = _extract(src)
        edge = next(e for e in result["edges"]
                    if e["relation"] == "calls" and e["target"] == "fmt")
        self.assertEqual(edge["source"], "loader")

    def test_shadowing_does_not_leak_to_function_level(self):
        """After the comprehension, the same name resolves normally again."""
        src = (
            "def loader(items):\n"
            "    out = [helper(x) for x in items]\n"
            "    helper(out)\n"
            "    return out\n"
        )
        edges = [c for c in _calls(src) if c[1] == "helper"]
        self.assertEqual(len(edges), 2, "both call sites extracted")
        function_level = next(e for e in edges if e[2] == "L3")
        result = _extract(src)
        raw = next(e for e in result["edges"]
                   if e["relation"] == "calls" and e["target"] == "helper"
                   and e["source_location"] == "L3")
        self.assertFalse(raw.get("is_local_var"),
                         "a comprehension target must not shadow function-level code")

    def test_shadowed_inline_names_never_become_pending_edges(self):
        """Pipeline: shadowed inline calls resolve to nothing, real ones do."""
        root = Path(tempfile.mkdtemp())
        (root / "m.py").write_text(
            "def real_handler(v):\n"
            "    return v\n"
            "\n"
            "def loader(items):\n"
            "    keyed = sorted(items, key=lambda handler: handler(1))\n"
            "    out = [handler(x) for handler in items]\n"
            "    good = [real_handler(x) for x in items]\n"
            "    return keyed, out, good\n",
            encoding="utf-8",
        )
        record = parse_file_graph(str(root / "m.py"), str(root))
        pending_targets = {p["dst_symbol"] for p in record["pending"]}
        self.assertNotIn(
            "handler", pending_targets,
            "the shadowed name must not mint a pending external edge",
        )
        self.assertNotIn(
            "handler", {e["dst"].rsplit(":", 1)[-1] for e in record["edges"]},
            "and no intra-file edge either — the lambda param is not the project symbol",
        )
        resolved = {
            e["dst"].rsplit(":", 1)[-1] for e in record["edges"]
            if e["relation"] == "calls"
        } | pending_targets
        self.assertIn(
            "real_handler", resolved,
            "unshadowed comprehension calls must reach resolution",
        )


class TestNoRegressionOnPlainScopes(unittest.TestCase):
    def test_plain_function_calls_unchanged(self):
        src = (
            "def caller():\n"
            "    util(1)\n"
            "    obj.method()\n"
            "    return 0\n"
        )
        calls = _calls(src)
        self.assertIn(("caller", "util", "L2"), calls)
        self.assertIn(("caller", "method", "L3"), calls)

    def test_self_recursion_filters_still_apply(self):
        src = "def fix(x):\n    return fix(x - 1)\n"
        self.assertEqual([c for c in _calls(src) if c[1] == "fix"], [],
                         "self-recursion is still filtered")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
