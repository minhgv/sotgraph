"""Honest-conformance tests for the ArchitectureBundler and the schema-driven report template.

Covers roadmap P1-1 requirements:
- Missing observable layer policy -> NOT_ASSESSED, never ZERO_VIOLATIONS / strict conformance.
- Candidate rule findings -> VIOLATIONS_DETECTED, clearly marked heuristic, anchored.
- Detector ran over in-scope edges with no findings -> NO_DETECTED_VIOLATIONS within
  published scope, never phrased as conformance.
- Coverage denominators match the detector's eligibility exactly.
- JSON and markdown emit the same verdict consistently.
- ARCHITECTURE_TEMPLATE.md is schema-driven: no domain assumptions, evidence refs or
  explicit UNKNOWN/[INFERENCE] required, referenced JSON keys must match the producer.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import sot_graph
from sot_graph.analytics.architecture import classify_node_layer
from sot_graph.analytics.bundle import ArchitectureBundler
from sot_graph.analytics.graph import AnalyticsGraph

TEMPLATE_PATH = Path(sot_graph.__file__).parent / "templates" / "ARCHITECTURE_TEMPLATE.md"

# (node_id, path, label) with paths chosen so the layer classifier is deterministic.
UNKNOWN_NODES = [
    ("plain.a", "src/plain/mod_a.py", "alpha"),
    ("plain.b", "src/plain/mod_b.py", "beta"),
]
PRES_NODE = ("ui.btn", "src/ui/widgets/button.py", "tap")
LOGIC_NODE = ("logic.svc", "src/logic/service.py", "run")
DATA_NODE = ("data.repo", "src/data/repo.py", "get_user")


def build_graph(nodes, edges):
    g = AnalyticsGraph()
    for nid, path, label in nodes:
        g.add_node(nid, label=label, kind="function", path=path)
    for src, dst in edges:
        g.add_edge(src, dst, relation="calls")
    return g


class TestBundleConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def _bundle(self, graph):
        out_dir = os.path.join(self.test_dir, f"bundle_{abs(hash(tuple(sorted(graph.nodes))))}")
        generated = ArchitectureBundler(graph=graph, root_dir=self.test_dir).extract_bundle(out_dir)
        metrics = json.loads(generated["05_system_metrics.json"])
        return generated["04_dependencies_violations.md"], metrics

    def test_missing_policy_not_assessed(self):
        """Unknown-layer graph: detector ran but observed no in-scope edges -> NOT_ASSESSED."""
        md, metrics = self._bundle(build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")]))
        conf = metrics["conformance"]
        self.assertEqual(conf["status"], "NOT_ASSESSED")
        self.assertEqual(conf["detector"]["assessed_edges"], 0)
        self.assertFalse(conf["layer_policy_observable"])
        self.assertFalse(conf["strict_conformance_claimed"])
        # Detector ran; the not-assessed reason is missing in-scope edges, not a skipped run.
        self.assertIn("had nothing to assess", conf["summary"])
        self.assertNotIn("did not run", conf["summary"])
        self.assertIn("NOT_ASSESSED", md)
        self.assertIn("Not assessed", md)
        self.assertNotIn("ZERO_VIOLATIONS", md)
        self.assertNotIn("strictly conforms", md)

    def test_no_profile_branch_not_assessed_and_zeroes_coverage(self):
        """Profile absent (detector never ran): NOT_ASSESSED and assessed edges forced to 0."""
        bundler = ArchitectureBundler(
            graph=build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")]),
            root_dir=self.test_dir,
        )
        bundler.profile = None  # simulate detector did not run
        conf = bundler._assess_conformance()
        self.assertEqual(conf["status"], "NOT_ASSESSED")
        self.assertEqual(conf["violations_detected"], 0)
        # Eligible edges exist in the graph, but must not be reported as assessed.
        self.assertGreater(bundler._compute_detector_coverage()["assessed_edges"], 0)
        self.assertEqual(conf["detector"]["assessed_edges"], 0)
        self.assertEqual(conf["detector"]["assessed_edge_fraction"], 0.0)
        self.assertIn("did not run", conf["summary"])
        self.assertNotIn("had nothing to assess", conf["summary"])

    def test_findings_are_heuristic_candidates_not_true_violations(self):
        """Presentation->Data edge fires LAYER_BYPASS; finding is a heuristic candidate."""
        md, metrics = self._bundle(build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")]))
        conf = metrics["conformance"]
        self.assertEqual(conf["status"], "VIOLATIONS_DETECTED")
        self.assertGreaterEqual(conf["violations_detected"], 1)
        self.assertEqual(conf["finding_nature"], "HEURISTIC_RULE_CANDIDATES")
        self.assertFalse(conf["strict_conformance_claimed"])
        self.assertIn("LAYER_BYPASS", md)
        self.assertIn("Candidate Rule Findings", md)
        self.assertIn("HEURISTIC_RULE_CANDIDATES", md)
        self.assertIn("NOT verified", md)  # candidate match, not a policy-verified violation
        self.assertNotIn("ZERO_VIOLATIONS", md)
        self.assertNotIn("strictly conforms", md)

    def test_no_false_conformance_when_scope_assessed(self):
        """Clean pres->logic->data edges: scoped no-findings, never conformance language."""
        md, metrics = self._bundle(
            build_graph([PRES_NODE, LOGIC_NODE, DATA_NODE], [("ui.btn", "logic.svc"), ("logic.svc", "data.repo")])
        )
        conf = metrics["conformance"]
        self.assertEqual(conf["status"], "NO_DETECTED_VIOLATIONS")
        self.assertGreaterEqual(conf["detector"]["assessed_edges"], 1)
        self.assertFalse(conf["strict_conformance_claimed"])
        self.assertFalse(conf["layer_policy_observable"])
        self.assertIn("NO_DETECTED_VIOLATIONS", md)
        self.assertIn("supported scope", md)
        self.assertIn("NOT claimed", md)
        self.assertNotIn("ZERO_VIOLATIONS", md)
        self.assertNotIn("strictly conforms", md)

    def test_coverage_matches_detector_eligibility(self):
        """Assessed edges = edges whose BOTH endpoints exist and are non-UNKNOWN layers.

        The detector (detect_architectural_violations) applies no edge-kind, test-path,
        or same-layer filter; dangling endpoints are UNKNOWN via map lookup default.
        """
        graph = build_graph(
            [PRES_NODE, LOGIC_NODE] + UNKNOWN_NODES,
            [
                ("ui.btn", "logic.svc"),      # eligible
                ("plain.a", "plain.b"),       # both UNKNOWN -> not assessed
                ("ui.btn", "ghost.missing"),  # dangling endpoint -> not assessed
            ],
        )
        bundler = ArchitectureBundler(graph=graph, root_dir=self.test_dir)
        coverage = bundler._assess_conformance()["detector"]
        self.assertEqual(coverage["assessed_edges"], 1)
        self.assertEqual(coverage["total_edges"], 3)
        self.assertEqual(coverage["classified_nodes"], 2)

        # Independent recomputation over the same eligibility rule.
        from sot_graph.analytics.architecture import ArchitecturalLayer
        expected = 0
        for edge in graph.edges:
            l_src = classify_node_layer(edge["src"], graph.nodes.get(edge["src"], {})) if edge["src"] in graph.nodes else None
            l_dst = classify_node_layer(edge["dst"], graph.nodes.get(edge["dst"], {})) if edge["dst"] in graph.nodes else None
            if l_src is not None and l_dst is not None \
                    and l_src is not ArchitecturalLayer.UNKNOWN and l_dst is not ArchitecturalLayer.UNKNOWN:
                expected += 1
        self.assertEqual(coverage["assessed_edges"], expected)

    def test_json_markdown_emit_same_verdict(self):
        """All three statuses: the JSON verdict string appears verbatim in the markdown."""
        graphs = [
            build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")]),
            build_graph([PRES_NODE, DATA_NODE], [("ui.btn", "data.repo")]),
            build_graph([PRES_NODE, LOGIC_NODE, DATA_NODE], [("ui.btn", "logic.svc"), ("logic.svc", "data.repo")]),
        ]
        statuses = set()
        for graph in graphs:
            md, metrics = self._bundle(graph)
            status = metrics["conformance"]["status"]
            statuses.add(status)
            self.assertIn(f"`{status}`", md)
            # Coverage denominators published identically in both artifacts.
            self.assertIn(str(metrics["conformance"]["detector"]["assessed_edges"]), md)
            self.assertIn(str(metrics["conformance"]["detector"]["total_edges"]), md)
        self.assertEqual(
            statuses, {"NOT_ASSESSED", "VIOLATIONS_DETECTED", "NO_DETECTED_VIOLATIONS"}
        )

    def test_metrics_json_backward_compatible_keys(self):
        _, metrics = self._bundle(build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")]))
        for key in [
            "project_root", "pattern_name", "primary_language", "framework_hints",
            "modularity_score_q", "modularity_verdict", "total_nodes", "total_edges",
            "total_files", "total_symbols", "graph_density", "average_degree",
            "total_communities", "total_violations", "total_routes",
            "total_functional_modules", "conformance",
        ]:
            self.assertIn(key, metrics)
        for key in ["status", "summary", "layer_policy_observable", "strict_conformance_claimed",
                    "violations_detected", "finding_nature", "detector"]:
            self.assertIn(key, metrics["conformance"])


class TestTemplateSchemaDriven(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = TEMPLATE_PATH.read_text(encoding="utf-8")
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_no_domain_assumptions(self):
        forbidden = [
            r"\bsso\b", r"\bbilling\b", r"\btelco\b", r"v-office", r"\bvoffice\b",
            r"\bbccs\b", r"\bunipay\b", r"\bumoney\b", r"\bbcel\b", r"\bilp\b", r"\berp\b",
            r"\bcrm\b", "kế toán", "hóa đơn", "hoa hồng", "sales manager", "web admin",
            "mini-app", "cổng thanh toán", "viễn thông", "khách hàng", "self-service portal",
        ]
        lowered = self.template.lower()
        # The forbidden-claims policy line legitimately lists domain examples; exempt it.
        body = "\n".join(
            line for line in lowered.splitlines() if "tuyệt đối cấm" not in line
        )
        for pat in forbidden:
            if pat.startswith(r"\b") or pat.startswith("v-"):
                self.assertIsNone(re.search(pat, body, re.I), f"domain assumption found: {pat}")
            else:
                self.assertNotIn(pat, body, f"domain assumption found: {pat}")

    def test_requires_evidence_refs_or_unknown_inference(self):
        self.assertIn("evidence: bundle://", self.template)
        self.assertIn("[INFERENCE]", self.template)
        self.assertIn("UNKNOWN", self.template)

    def test_conformance_status_vocabulary_and_forbidden_claims(self):
        for status in ["NOT_ASSESSED", "NO_DETECTED_VIOLATIONS", "VIOLATIONS_DETECTED"]:
            self.assertIn(status, self.template)
        self.assertIn("conformance.status", self.template)
        # Strict-conformance phrases appear only inside the mandatory forbidden list.
        m = re.search(r"Tuyệt đối cấm.*?(strictly conforms|ZERO_VIOLATIONS)", self.template, re.S | re.I)
        self.assertIsNotNone(m)
        self.assertEqual(len(re.findall(r"ZERO_VIOLATIONS", self.template)), 1)

    def test_transitions_and_connectivity_not_inferred_from_signals(self):
        # Call-graph edge is not transition proof.
        self.assertIn("cạnh gọi ≠ chuyển trạng thái", self.template)
        self.assertIn("UNKNOWN", self.template.split("### 4.1")[1].split("###")[0])
        # No hardwired example edges in the C4 example: every --> lives in a %% comment.
        c4_block = re.search(r"```mermaid\s*\ngraph TD.*?```", self.template, re.S).group(0)
        for line in c4_block.splitlines():
            if "-->" in line:
                self.assertIn("%%", line, f"uncommented default edge: {line.strip()}")
        # Connector label alone is not evidence of an external container.
        self.assertIn("TÍN HIỆU ỨNG VIÊN", self.template)

    def test_referenced_metrics_keys_match_producer(self):
        graph = build_graph(UNKNOWN_NODES, [("plain.a", "plain.b")])
        out_dir = os.path.join(self.test_dir, "template_ref_bundle")
        generated = ArchitectureBundler(graph=graph, root_dir=self.test_dir).extract_bundle(out_dir)
        metrics = json.loads(generated["05_system_metrics.json"])
        refs = set(re.findall(r"bundle://05_system_metrics\.json#([A-Za-z_][A-Za-z0-9_]*)", self.template))
        self.assertTrue(refs, "template must reference producer metrics keys")
        for key in refs:
            self.assertIn(key, metrics, f"template references unknown metrics key: {key}")


if __name__ == "__main__":
    unittest.main()
