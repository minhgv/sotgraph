"""Typed references and context-manager protocol evidence (T-02 / AC-02).

Pins the statically justified reference evidence added to the Python
extractor and consumed by pack:

- typed attribute/method REFERENCES (non-call uses: callbacks, values)
  carry the receiver type or import provenance and bind like calls;
- untyped attribute references stay unclaimed (never same-name bound);
- ``with X:`` / ``async with X:`` emit the context-manager protocol
  calls (``__enter__``/``__exit__``, ``__aenter__``/``__aexit__``) when
  the class is statically known, and stay honestly unresolved when the
  class does not implement the protocol;
- unresolved receiver cases never become fabricated call edges.
"""

import os
import shutil
import tempfile
import unittest

from sot_graph._vendor.graphify.extract import extract_python
from sot_graph.db import Database
from sot_graph.pack import build_bundle
from sot_graph.reconciler import Reconciler

SERVICE_SRC = '''\
from pkg.tool import tool


class Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Plain:
    def ping(self):
        return 1


class Service:
    def dispatch(self):
        handler = self.helper
        return handler()

    def helper(self):
        with Ctx() as c:
            return tool()
        with Plain():
            pass

    def save(self):
        saver = self.persist
        return saver()
'''

TOOL_SRC = '''\
def tool():
    return 42


def run_pipeline():
    step = tool
    return step()
'''

TEST_SRC = '''\
from pkg.service import Service, Ctx
from pkg import service
from pkg.tool import tool


def test_dispatch_runs():
    svc = Service()
    assert svc.dispatch() == 2


def test_ctx_protocol():
    with Ctx() as c:
        assert c is not None


def test_tool_value():
    assert tool() == 42
'''


def _refs(edges, relation="references"):
    return [e for e in edges if e["relation"] == relation]


class TypedReferenceExtractionTests(unittest.TestCase):
    """Unit: extract_python emits statically justified reference edges."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="sot-typed-refs-")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.path = os.path.join(self.test_dir, "sample.py")
        with open(self.path, "w") as fh:
            fh.write(SERVICE_SRC)
        self.result = extract_python(__import__("pathlib").Path(self.path))
        self.assertIsNone(self.result["error"])

    def test_typed_self_reference_binds_enclosing_class(self):
        refs = [e for e in _refs(self.result["edges"])
                if e["source"] == "Service.dispatch" and e["target"] == "helper"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["call_kind"], "METHOD_CALL")
        self.assertEqual(refs[0]["receiver"], "Service")
        expected_line = next(
            i for i, line in enumerate(SERVICE_SRC.splitlines(), 1)
            if "handler = self.helper" in line)
        self.assertEqual(refs[0]["source_location"], f"L{expected_line}")

    def test_undefined_attribute_reference_is_typed_not_guessed(self):
        # `self.persist` names no defined symbol anywhere; the emitted row
        # is still a typed METHOD_CALL on the enclosing class — never an
        # unqualified name that a same-named symbol elsewhere could win.
        refs = [e for e in _refs(self.result["edges"])
                if e["target"] == "persist"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["call_kind"], "METHOD_CALL")
        self.assertEqual(refs[0]["receiver"], "Service")

    def test_untyped_foreign_receiver_is_silent(self):
        # `other.mystery()` (a call on an unknown object) yields only the
        # honest ATTRIBUTE call row that predates this change — no
        # reference row, no same-name binding.
        self.assertFalse([e for e in _refs(self.result["edges"])
                          if e["target"] == "mystery"])

    def test_same_file_context_manager_binds_dunders_directly(self):
        calls = [e for e in self.result["edges"] if e["relation"] == "calls"]
        dunders = sorted((e["source"], e["target"]) for e in calls
                         if e["target"].endswith(("__enter__", "__exit__")))
        # Ctx implements the protocol in this file: direct qualified edges.
        # Plain does not: a typed pending row on the known class only —
        # the resolver must refuse to bind it, never guess a same-name.
        self.assertEqual(dunders, [
            ("Service.helper", "Ctx.__enter__"),
            ("Service.helper", "Ctx.__exit__"),
            ("Service.helper", "__enter__"),
            ("Service.helper", "__exit__"),
        ])
        direct = [e for e in calls if e["target"] == "Ctx.__enter__"]
        self.assertEqual(direct[0]["source_location"],
                         f"L{next(i for i, line in enumerate(SERVICE_SRC.splitlines(), 1) if 'with Ctx()' in line)}")
        typed_plain = [e for e in calls if e["target"] == "__enter__"]
        self.assertEqual(typed_plain[0]["call_kind"], "METHOD_CALL")
        self.assertEqual(typed_plain[0]["receiver"], "Plain")

    def test_protocol_less_class_stays_pending_typed(self):
        calls = [e for e in self.result["edges"] if e["relation"] == "calls"]
        plain = [e for e in calls if e["target"] == "__enter__"
                 and e.get("receiver") == "Plain"]
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0]["call_kind"], "METHOD_CALL")

    def test_builtin_context_manager_is_skipped(self):
        calls = [e for e in self.result["edges"] if e["relation"] == "calls"]
        self.assertFalse([e for e in calls if e.get("receiver") == "open"
                          and e["target"] == "__enter__"])

    def test_async_with_uses_async_dunders(self):
        async_src = (
            "class ACtx:\n"
            "    async def __aenter__(self):\n"
            "        return self\n"
            "\n"
            "    async def __aexit__(self, *exc):\n"
            "        return False\n"
            "\n"
            "\n"
            "async def flow():\n"
            "    async with ACtx() as c:\n"
            "        return c\n"
        )
        path = os.path.join(self.test_dir, "async_sample.py")
        with open(path, "w") as fh:
            fh.write(async_src)
        result = extract_python(__import__("pathlib").Path(path))
        calls = [e for e in result["edges"] if e["relation"] == "calls"]
        dunders = sorted(e["target"] for e in calls
                         if e["target"].endswith(("__aenter__", "__aexit__")))
        # Same-file class: direct qualified edges to the async protocol.
        self.assertEqual(dunders, ["ACtx.__aenter__", "ACtx.__aexit__"])

    def test_call_target_not_duplicated_as_reference(self):
        calls = [e for e in self.result["edges"] if e["relation"] == "calls"]
        refs = _refs(self.result["edges"])
        # tool() is a call in helper; no reference row for it anywhere.
        self.assertTrue(any(e["target"] == "tool" for e in calls))
        self.assertFalse([e for e in refs if e["target"] == "tool"])

    def test_chained_access_emits_deepest_known_receiver_link(self):
        # 'a.b.c' truthful semantics: exactly one reference row, for the
        # deepest Name-anchored link ('http.client', receiver = imported
        # module root). The outer '.timeout_secs' claims nothing — its
        # receiver is the runtime value of 'http.client', which no static
        # evidence names. (An earlier comment claimed the outermost link
        # was emitted; this pins the actually supported identity.)
        chain_src = (
            "import pkg.http as http\n"
            "\n"
            "\n"
            "def fetch():\n"
            "    return http.client.timeout_secs\n"
        )
        path = os.path.join(self.test_dir, "chain.py")
        with open(path, "w") as fh:
            fh.write(chain_src)
        result = extract_python(__import__("pathlib").Path(path))
        self.assertIsNone(result["error"])
        rows = sorted(
            (e["source"], e["target"], e["receiver"], e["call_kind"],
             e.get("import_source"))
            for e in _refs(result["edges"]))
        self.assertEqual(
            rows, [("fetch", "client", "http", "QUALIFIED", "pkg.http")])


class ReferenceResolutionTests(unittest.TestCase):
    """End-to-end: extraction → reconcile → binding → pack evidence."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="sot-ref-e2e-", dir=".sot/tmp")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        os.makedirs(os.path.join(self.repo, "pkg"))
        os.makedirs(os.path.join(self.repo, "tests"))
        with open(os.path.join(self.repo, "pkg", "service.py"), "w") as fh:
            fh.write(SERVICE_SRC)
        with open(os.path.join(self.repo, "pkg", "tool.py"), "w") as fh:
            fh.write(TOOL_SRC)
        with open(os.path.join(self.repo, "tests", "test_service.py"), "w") as fh:
            fh.write(TEST_SRC)
        self.db = Database(os.path.join(self.repo, "index.db"))
        self.addCleanup(self.db.close)
        Reconciler(self.db, self.repo).reconcile(workers=1)

    def _edges(self, relation):
        return self.db.conn.execute(
            "SELECT s.symbol AS src, d.symbol AS dst, s.path AS sp, d.path AS dp "
            "FROM graph_edges e JOIN graph_nodes s ON s.id = e.src "
            "JOIN graph_nodes d ON d.id = e.dst WHERE e.relation = ?",
            (relation,),
        ).fetchall()

    def test_intra_file_typed_reference_promotes(self):
        rows = [(r[0], r[1]) for r in self._edges("references")]
        self.assertIn(("Service.dispatch", "Service.helper"), rows)

    def test_cross_file_protocol_calls_bind_from_test(self):
        # The test module imports Ctx from pkg.service; the with-statement
        # protocol calls bind to the class methods through the typed
        # resolver — real test evidence for a symbol no bare call reaches.
        rows = [(r[0], r[1]) for r in self._edges("calls")]
        self.assertIn(("test_ctx_protocol", "Ctx.__enter__"), rows)
        self.assertIn(("test_ctx_protocol", "Ctx.__exit__"), rows)

    def test_protocol_less_class_never_binds(self):
        rows = [(r[0], r[1]) for r in self._edges("calls")]
        self.assertNotIn(("Service.helper", "Plain.__enter__"), rows)
        pending = self.db.conn.execute(
            "SELECT call_kind, receiver, resolution_state FROM pending_edges "
            "WHERE dst_symbol = '__enter__' AND receiver = 'Plain'"
        ).fetchall()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][2], "UNRESOLVED")

    def test_undefined_self_reference_stays_unresolved(self):
        rows = [(r[0], r[1]) for r in self._edges("references")]
        self.assertNotIn(("Service.save", "Service.persist"), rows)
        pending = self.db.conn.execute(
            "SELECT resolution_state FROM pending_edges "
            "WHERE relation = 'references' AND dst_symbol = 'persist'"
        ).fetchall()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][0], "UNRESOLVED")

    def test_pack_surfaces_reference_evidence(self):
        bundle = build_bundle(self.db, self.repo, "Service.helper")
        inbound = [(c["fqn"].rsplit(".", 1)[-1], c["relation"])
                   for c in bundle["inbound_callers"]]
        self.assertIn(("dispatch", "references"), inbound)
        # The scoped locator form reaches the same symbol.
        scoped = build_bundle(
            self.db, self.repo, "pkg/service.py::Service.dispatch")
        self.assertEqual(scoped["resolution"]["status"], "PATH_SCOPED_TARGET")
        self.assertTrue(any(
            c["relative_path"].startswith("tests/") and c["relation"] == "calls"
            for c in scoped["inbound_callers"]))


if __name__ == "__main__":
    unittest.main()
