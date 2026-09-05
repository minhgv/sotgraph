"""Honest-conformance tests for the human report path (analytics/report.py).

Verifies that report.py reuses the SAME shared conformance assessment as the
fact bundler (analytics/conformance.py) and never emits ungrounded claims:

- No fabricated pattern when the architecture profile is absent (UNKNOWN, not
  "Modular Layered Architecture"); no CLEAN / ZERO_VIOLATIONS conformance claim.
- Profile absent => detector "did not run" => NOT_ASSESSED.
- Empty graph / no assessable edges => NOT_ASSESSED ("nothing to assess").
- Assessable edges with zero findings => NO_DETECTED_VIOLATIONS, scoped,
  strict conformance never claimed.
- Findings => VIOLATIONS_DETECTED, labeled heuristic rule candidates.
- Cross-path parity: bundler 05_system_metrics.json conformance == report
  JSON-LD conformance for the same graph, and both statuses appear in both
  markdown artifacts.
- Without graph access, coverage denominators are reported unavailable, never
  fabricated.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.analytics.bundle import ArchitectureBundler
from sot_graph.analytics.diagnostics import analyze_graph
from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.analytics.report import (
    generate_jsonld_schema,
    generate_markdown_report,
)
from sot_graph.cli import build_parser, cmd_report
from sot_graph.db import Database
from sot_graph.mcp_service import McpService
from sot_graph.reconciler import Reconciler

# (node_id, path, label) with paths chosen so the layer classifier is deterministic.
UNKNOWN_NODES = [
    ("plain.a", "src/plain/mod_a.py", "alpha"),
    ("plain.b", "src/plain/mod_b.py", "beta"),
]
PRES_NODE = ("ui.btn", "src/ui/widgets/button.py", "tap")
LOGIC_NODE = ("logic.svc", "src/logic/service.py", "run")
DATA_NODE = ("data.repo", "src/data/repo.py", "get_user")

FALSE_CONFORMANCE_PHRASES = [
    "ZERO_VIOLATIONS",
    "strictly conforms",
    "conforms to unidirectional",
    "🟢 **CLEAN**",
]


def build_graph(nodes, edges):
    g = AnalyticsGraph()
    for nid, path, label in nodes:
        g.add_node(nid, label=label, kind="function", path=path)
    for src, dst in edges:
        g.add_edge(src, dst, relation="calls")
    return g


class TestReportConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def _report(self, graph, with_graph=True, drop_profile=False):
        analysis = analyze_graph(graph)
        if drop_profile:
            analysis.architecture_profile = None
        g = graph if with_graph else None
        md = generate_markdown_report(analysis, project_name="ParityProj", graph=g)
        schema = generate_jsonld_schema(analysis, project_name="ParityProj", graph=g)
        return md, schema

    def _assert_no_false_conformance(self, md):
        for phrase in FALSE_CONFORMANCE_PHRASES:
            self.assertNotIn(phrase, md)

    def test_no_profile_not_assessed_no_fabricated_pattern(self):
        """Profile absent: detector 'did not run', pattern UNKNOWN, no clean claim."""
        md, schema = self._report(
            build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")]),
            drop_profile=True,
        )
        conf = schema["conformance"]
        self.assertEqual(conf["status"], "NOT_ASSESSED")
        self.assertIn("did not run", conf["summary"])
        self.assertFalse(conf["strict_conformance_claimed"])
        self.assertFalse(conf["layer_policy_observable"])
        self.assertEqual(conf["detector"]["assessed_edges"], 0)
        # JSON-LD path: no fabricated pattern or clean-violations story.
        self.assertEqual(schema["primaryPattern"], "UNKNOWN")
        self.assertIn("no pattern inferred", schema["primaryPatternNote"])
        self.assertIn("Not assessed", md)
        self._assert_no_false_conformance(md)
        self.assertIn("Detector did not run", md)
        self.assertIn("no pattern inferred or claimed", md)

    def test_empty_graph_not_assessed(self):
        """Empty graph: detector ran but had zero edges/nodes to assess."""
        md, schema = self._report(build_graph([], []))
        conf = schema["conformance"]
        self.assertEqual(conf["status"], "NOT_ASSESSED")
        self.assertIn("had nothing to assess", conf["summary"])
        d = conf["detector"]
        self.assertTrue(d["coverage_available"])
        self.assertEqual(d["total_edges"], 0)
        self.assertEqual(d["assessed_edges"], 0)
        self._assert_no_false_conformance(md)
        self.assertIn("NOT_ASSESSED", md)

    def test_no_assessable_edges_not_assessed(self):
        """All-UNKNOWN endpoints: nothing within the detector's supported scope."""
        md, schema = self._report(build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")]))
        conf = schema["conformance"]
        self.assertEqual(conf["status"], "NOT_ASSESSED")
        self.assertIn("had nothing to assess", conf["summary"])
        self.assertEqual(conf["detector"]["assessed_edges"], 0)
        self.assertEqual(conf["detector"]["total_edges"], 1)
        self._assert_no_false_conformance(md)

    def test_assessable_zero_findings_no_conformance_claim(self):
        """In-scope clean edges: scoped no-findings, strict conformance never claimed."""
        md, schema = self._report(
            build_graph(
                [PRES_NODE, LOGIC_NODE, DATA_NODE],
                [("ui.btn", "logic.svc"), ("logic.svc", "data.repo")],
            )
        )
        conf = schema["conformance"]
        self.assertEqual(conf["status"], "NO_DETECTED_VIOLATIONS")
        self.assertGreaterEqual(conf["detector"]["assessed_edges"], 1)
        self.assertFalse(conf["strict_conformance_claimed"])
        self.assertFalse(conf["layer_policy_observable"])
        self.assertIn("NO_DETECTED_VIOLATIONS", md)
        self.assertIn("NOT claimed", md)
        self.assertIn("not a conformance guarantee", md)
        self._assert_no_false_conformance(md)

    def test_findings_are_labeled_heuristic_candidates(self):
        """Presentation->Data edge: VIOLATIONS_DETECTED, candidate not verified."""
        md, schema = self._report(
            build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")])
        )
        conf = schema["conformance"]
        self.assertEqual(conf["status"], "VIOLATIONS_DETECTED")
        self.assertGreaterEqual(conf["violations_detected"], 1)
        self.assertEqual(conf["finding_nature"], "HEURISTIC_RULE_CANDIDATES")
        self.assertFalse(conf["strict_conformance_claimed"])
        self.assertIn("LAYER_BYPASS", md)
        self.assertIn("HEURISTIC_RULE_CANDIDATES", md)
        self.assertIn("NOT verified", md)
        self.assertIn("Candidate Rule Findings", md)
        self._assert_no_false_conformance(md)

    def test_cross_path_parity_bundle_vs_report(self):
        """Same graph: bundler JSON conformance == report JSON-LD conformance,
        and the shared status string appears in both markdown artifacts."""
        graphs = {
            "no_assessable": build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")]),
            "findings": build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")]),
            "assessable_zero": build_graph(
                [PRES_NODE, LOGIC_NODE, DATA_NODE],
                [("ui.btn", "logic.svc"), ("logic.svc", "data.repo")],
            ),
        }
        statuses = set()
        for name, graph in graphs.items():
            out_dir = os.path.join(self.test_dir, f"parity_{name}")
            generated = ArchitectureBundler(graph=graph, root_dir=self.test_dir).extract_bundle(out_dir)
            bundle_metrics = json.loads(generated["05_system_metrics.json"])
            bundle_conf = bundle_metrics["conformance"]

            _, schema = self._report(graph)
            report_conf = schema["conformance"]

            self.assertEqual(bundle_conf, report_conf, f"parity broken for {name}")
            # Qualified pattern inference must also match across paths.
            self.assertEqual(bundle_metrics["pattern_name"], schema["primaryPattern"], f"pattern parity broken for {name}")
            self.assertEqual(bundle_metrics["pattern_inference"], schema["primaryPatternNote"], f"pattern note parity broken for {name}")
            self.assertIn(bundle_conf["status"], generated["04_dependencies_violations.md"])
            statuses.add(report_conf["status"])

            md, _ = self._report(graph)
            self.assertIn(f"`{report_conf['status']}`", md)
            self._assert_no_false_conformance(md)

        self.assertEqual(
            statuses, {"NOT_ASSESSED", "VIOLATIONS_DETECTED", "NO_DETECTED_VIOLATIONS"}
        )

    def test_report_without_graph_coverage_unavailable_not_fabricated(self):
        """No graph access: denominators published as unavailable, never zeros."""
        md, schema = self._report(
            build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")]),
            with_graph=False,
        )
        conf = schema["conformance"]
        self.assertEqual(conf["status"], "VIOLATIONS_DETECTED")
        d = conf["detector"]
        self.assertFalse(d["coverage_available"])
        self.assertIsNone(d["assessed_edges"])
        self.assertIsNone(d["total_edges"])
        self.assertIn("Coverage denominators are unavailable", md)
        self.assertIn("Detector coverage:** unavailable", md)
        self.assertNotIn("**Detector coverage:** assessed edges", md)
        self._assert_no_false_conformance(md)

    def test_report_without_graph_no_profile_still_not_assessed(self):
        """No graph AND no profile: NOT_ASSESSED without any coverage numbers."""
        md, schema = self._report(
            build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")]),
            with_graph=False,
            drop_profile=True,
        )
        conf = schema["conformance"]
        self.assertEqual(conf["status"], "NOT_ASSESSED")
        self.assertIn("did not run", conf["summary"])
        self.assertFalse(conf["detector"]["coverage_available"])
        self.assertIsNone(conf["detector"]["assessed_edges"])
        self._assert_no_false_conformance(md)

    def test_zero_classified_coverage_pattern_not_claimed(self):
        """Bundle + report: inferred pattern is UNKNOWN when zero nodes classified.

        A heuristic pattern name inferred from zero classified nodes is
        ungrounded and must not be claimed in either path.
        """
        graph = build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")])
        out_dir = os.path.join(self.test_dir, "zero_class_bundle")
        generated = ArchitectureBundler(graph=graph, root_dir=self.test_dir).extract_bundle(out_dir)
        metrics = json.loads(generated["05_system_metrics.json"])
        self.assertEqual(metrics["pattern_name"], "UNKNOWN")
        self.assertIn("zero nodes were classified", metrics["pattern_inference"])
        self.assertIn("no pattern is claimed", metrics["pattern_inference"])

        _, schema = self._report(graph)
        self.assertEqual(schema["primaryPattern"], "UNKNOWN")
        self.assertEqual(schema["primaryPatternNote"], metrics["pattern_inference"])

    def test_section11_no_clean_assurance_zero_coverage(self):
        """UNKNOWN 2-node/1-edge graph: no padded clean-assurance recs anywhere.

        Regression for architecture.py padding: empty rec groups must stay
        empty at the source, and section 11 must print the scoped fallback.
        """
        graph = build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")])
        analysis = analyze_graph(graph)
        prof = analysis.architecture_profile
        # Source: no global clean-assurance padding in the profile itself.
        for recs in (prof.recommendations_p0, prof.recommendations_p1, prof.recommendations_p2):
            self.assertEqual(recs, [])
        md, _ = self._report(graph)
        sec11 = md.split("## 11.")[1].split("## 12.")[0]
        for term in (
            "Invariants Verified", "adhere cleanly", "clean separation",
            "well-modularized", "Zero high-risk", "No immediate P0",
        ):
            self.assertNotIn(term, sec11)
        for scope in ("P0", "P1", "P2"):
            self.assertIn(
                f"No candidate {scope} recommendations within the scoped detector rules", sec11
            )
        self.assertIn("not a global assurance", sec11)

    def test_section11_no_contradiction_with_medium_bypass(self):
        """MEDIUM LAYER_BYPASS: section 9 lists the finding, so section 11 must
        not claim verified invariants; the grounded P1 rec survives."""
        graph = build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")])
        analysis = analyze_graph(graph)
        prof = analysis.architecture_profile
        self.assertTrue(any(v.violation_type == "LAYER_BYPASS" for v in prof.violations))
        self.assertFalse(any(v.severity in ("CRITICAL", "HIGH") for v in prof.violations))
        md, _ = self._report(graph)
        sec9 = md.split("## 9.")[1].split("## 10.")[0]
        sec11 = md.split("## 11.")[1].split("## 12.")[0]
        self.assertIn("LAYER_BYPASS", sec9)
        self.assertNotIn("Invariants Verified", sec11)
        self.assertNotIn("Zero high-risk", sec11)
        self.assertIn("No candidate P0 recommendations within the scoped detector rules", sec11)
        # Grounded recommendation derived from the observed bypass survives.
        self.assertIn("Enforce Clean Layer Boundaries", sec11)

    def test_section11_filters_stale_producer_assurance(self):
        """Robust render: even if a stale producer emits padded clean-assurance
        recommendation lines, the report drops them instead of allowing them."""
        graph = build_graph([PRES_NODE, LOGIC_NODE, DATA_NODE], [("ui.btn", "logic.svc")])
        analysis = analyze_graph(graph)
        prof = analysis.architecture_profile
        prof.recommendations_p0 = list(prof.recommendations_p0) + [
            "**[Architectural Invariants Verified]** Zero high-risk circular dependencies "
            "detected across the codebase."
        ]
        prof.recommendations_p2 = list(prof.recommendations_p2) + [
            "**[Modular Scalability]** Maintain current clean separation of concerns."
        ]
        md = generate_markdown_report(analysis, project_name="Stale", graph=graph)
        sec11 = md.split("## 11.")[1].split("## 12.")[0]
        self.assertNotIn("Invariants Verified", sec11)
        self.assertNotIn("Zero high-risk", sec11)
        self.assertNotIn("clean separation", sec11)
        # With nothing grounded left, every group shows the scoped fallback.
        for scope in ("P0", "P2"):
            self.assertIn(
                f"No candidate {scope} recommendations within the scoped detector rules", sec11
            )


def _populate_layered_dart_project(root: Path) -> None:
    """Multi-layer Dart fixture (proven to yield classified nodes AND call edges)."""
    core = root / "lib" / "core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "app_router.dart").write_text(
        "class AppRouter { static void navigate(String path) {} }\n"
    )
    (core / "api_client.dart").write_text(
        "class ApiClient { Future<Map> get(String url) async => {}; }\n"
    )
    pres = root / "lib" / "features" / "auth" / "presentation"
    pres.mkdir(parents=True, exist_ok=True)
    (pres / "login_screen.dart").write_text(
        "import 'package:app/features/auth/bloc/auth_bloc.dart';\n"
        "class LoginScreen extends StatelessWidget {\n"
        "  void onLoginPressed() { AuthBloc.login(); }\n"
        "}\n"
    )
    bloc = root / "lib" / "features" / "auth" / "bloc"
    bloc.mkdir(parents=True, exist_ok=True)
    (bloc / "auth_bloc.dart").write_text(
        "import 'package:app/features/auth/domain/auth_usecase.dart';\n"
        "class AuthBloc {\n"
        "  static void login() { AuthUseCase.execute(); }\n"
        "}\n"
    )
    domain = root / "lib" / "features" / "auth" / "domain"
    domain.mkdir(parents=True, exist_ok=True)
    (domain / "auth_usecase.dart").write_text(
        "import 'package:app/features/auth/data/auth_repository.dart';\n"
        "class AuthUseCase {\n"
        "  static void execute() { AuthRepository.authenticate(); }\n"
        "}\n"
    )
    data = root / "lib" / "features" / "auth" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "auth_repository.dart").write_text(
        "import 'package:app/core/api_client.dart';\n"
        "class AuthRepository {\n"
        "  static void authenticate() => ApiClient().get('/auth');\n"
        "}\n"
    )


def _extract_jsonld(md):
    block = md.split("## 12. Machine-Readable Architecture Schema (JSON-LD)", 1)[1]
    return json.loads(block.split("```json", 1)[1].split("```", 1)[0])


_COVERAGE_RE = re.compile(r"assessed edges `(\d+)` / `(\d+)`")


class TestShippedPathIntegration(unittest.TestCase):
    """End-to-end: the shipped CLI and MCP report paths receive REAL detector
    denominators (graph wired at the callsite), and share the bundler's verdict.
    """

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, ".sot", "sot.db")
        db = Database(cls.db_path)
        _populate_layered_dart_project(Path(cls.test_dir))
        Reconciler(db, cls.test_dir).reconcile()
        db.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def _bundle_conformance(self):
        db = Database(self.db_path)
        try:
            bundler = ArchitectureBundler(db=db, root_dir=self.test_dir)
            out_dir = os.path.join(self.test_dir, "integration_bundle")
            generated = bundler.extract_bundle(out_dir)
            metrics = json.loads(generated["05_system_metrics.json"])
            return metrics["conformance"], metrics["pattern_name"]
        finally:
            db.close()

    def _assert_real_denominators(self, md, bundle_conf, bundle_pattern):
        # Real, non-fabricated coverage must be published (not "unavailable").
        self.assertIn("Detector coverage:** assessed edges", md)
        self.assertNotIn("Detector coverage:** unavailable", md)
        m = _COVERAGE_RE.search(md)
        self.assertIsNotNone(m)
        assessed, total = int(m.group(1)), int(m.group(2))
        self.assertGreaterEqual(assessed, 1)
        self.assertGreater(total, 0)
        # The shipped report shares the bundler's exact verdict + pattern.
        schema = _extract_jsonld(md)
        self.assertEqual(schema["conformance"], bundle_conf)
        self.assertEqual(schema["conformance"]["detector"]["assessed_edges"], assessed)
        self.assertEqual(schema["conformance"]["detector"]["total_edges"], total)
        self.assertTrue(schema["conformance"]["detector"]["coverage_available"])
        self.assertFalse(schema["conformance"]["strict_conformance_claimed"])
        self.assertEqual(schema["primaryPattern"], bundle_pattern)
        self.assertNotIn("ZERO_VIOLATIONS", md)

    def test_cli_report_receives_real_denominators(self):
        out_path = os.path.join(self.test_dir, "cli_report.md")
        parser = build_parser()
        args = parser.parse_args(["--root", self.test_dir, "report", "-o", out_path])
        db = Database(self.db_path)
        try:
            rc = cmd_report(args, db, self.test_dir)
        finally:
            db.close()
        self.assertEqual(rc, 0)
        md = Path(out_path).read_text(encoding="utf-8")
        bundle_conf, bundle_pattern = self._bundle_conformance()
        self._assert_real_denominators(md, bundle_conf, bundle_pattern)

    def test_mcp_report_receives_real_denominators(self):
        service = McpService(self.db_path, self.test_dir)
        res = service.get_architecture_report()
        self.assertIn("report_markdown", res)
        md = res["report_markdown"]
        bundle_conf, bundle_pattern = self._bundle_conformance()
        self._assert_real_denominators(md, bundle_conf, bundle_pattern)


if __name__ == "__main__":
    unittest.main()
