"""
src/sot_graph/analytics/conformance.py
Shared, honest architectural-conformance assessment.

Single source of truth for the conformance verdict consumed by BOTH the fact
bundler (``04_dependencies_violations.md`` + ``05_system_metrics.json``) and the
human / JSON-LD report (``analytics/report.py``). The detector never observes a
declared layer-policy artifact (none is ingested), therefore:

- strict conformance is NEVER claimed (``strict_conformance_claimed`` is always False);
- the layer policy is reported as unobserved (``layer_policy_observable`` is always False);
- every finding is labeled a heuristic rule candidate, never a verified violation;
- coverage denominators reflect the detector's actual eligibility (an edge is
  assessed only when both endpoints exist and classify as non-UNKNOWN layers);
- absence of findings is never phrased as conformance.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sot_graph.analytics.architecture import (
    ArchitecturalLayer,
    ArchitectureProfile,
    classify_node_layer,
)

# Conformance status vocabulary, emitted identically by the bundler and the report.
CONFORMANCE_NOT_ASSESSED = "NOT_ASSESSED"
CONFORMANCE_NO_DETECTED_VIOLATIONS = "NO_DETECTED_VIOLATIONS"
CONFORMANCE_VIOLATIONS_DETECTED = "VIOLATIONS_DETECTED"

DETECTOR_CLASSIFICATION = "AST_PATH_HEURISTIC"
DETECTOR_SUPPORTED_RULES = ["LAYER_BYPASS", "INVERTED_DEPENDENCY"]
DETECTOR_LIMITATIONS = [
    "Layer policy is not observable: no declared architecture-rules artifact is ingested; "
    "layer roles are inferred from path/label/keyword heuristics.",
    "Only LAYER_BYPASS (Presentation->Data) and INVERTED_DEPENDENCY (Data/Domain->Presentation) "
    "rules are supported; all other constraint types are out of scope.",
    "Edges with any UNKNOWN-layer endpoint are not assessed; assessed_edge_fraction publishes "
    "the denominator. Absence of findings is NOT evidence of conformance.",
]

_COVERAGE_KEYS = (
    "total_nodes",
    "classified_nodes",
    "classified_node_fraction",
    "total_edges",
    "assessed_edges",
    "assessed_edge_fraction",
)


def compute_detector_coverage(graph: Any) -> Dict[str, Any]:
    """Compute detector-eligibility coverage over the actual graph endpoints.

    An edge is assessed only when both of its actual endpoints exist in the
    graph and classify as non-UNKNOWN layers; the published denominators match
    that eligibility exactly.
    """
    node_layers = {
        node_id: classify_node_layer(node_id, data)
        for node_id, data in graph.nodes.items()
    }
    total_nodes = len(node_layers)
    classified_nodes = sum(
        1 for layer in node_layers.values() if layer is not ArchitecturalLayer.UNKNOWN
    )

    total_edges = len(graph.edges)
    assessed_edges = 0
    for edge in graph.edges:
        l_src = node_layers.get(edge["src"], ArchitecturalLayer.UNKNOWN)
        l_dst = node_layers.get(edge["dst"], ArchitecturalLayer.UNKNOWN)
        if l_src is not ArchitecturalLayer.UNKNOWN and l_dst is not ArchitecturalLayer.UNKNOWN:
            assessed_edges += 1

    return {
        "total_nodes": total_nodes,
        "classified_nodes": classified_nodes,
        "classified_node_fraction": round(classified_nodes / total_nodes, 4) if total_nodes else 0.0,
        "total_edges": total_edges,
        "assessed_edges": assessed_edges,
        "assessed_edge_fraction": round(assessed_edges / total_edges, 4) if total_edges else 0.0,
    }


def _detector_block(coverage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the ``detector`` sub-dict, publishing coverage when available.

    When ``coverage`` is None (report path without graph access), denominators
    are published as null rather than fabricated zeros.
    """
    if coverage is not None:
        return {
            "classification_method": DETECTOR_CLASSIFICATION,
            "supported_rules": list(DETECTOR_SUPPORTED_RULES),
            "coverage_available": True,
            **coverage,
            "limitations": list(DETECTOR_LIMITATIONS),
        }
    return {
        "classification_method": DETECTOR_CLASSIFICATION,
        "supported_rules": list(DETECTOR_SUPPORTED_RULES),
        "coverage_available": False,
        **{key: None for key in _COVERAGE_KEYS},
        "limitations": list(DETECTOR_LIMITATIONS)
        + [
            "Coverage denominators are unavailable: this report path has no graph access, "
            "so the in-scope edge count could not be computed.",
        ],
    }


def qualify_pattern_inference(
    profile: Optional[ArchitectureProfile],
    coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Honestly qualify the inferred architecture pattern for bundle + report.

    The pattern name comes from heuristic path/label inference, so it is never
    presented as a verified declared pattern. When the profile is absent, or
    when zero nodes were classified into layers (zero classified coverage), the
    inference is ungrounded and no pattern is claimed (``UNKNOWN``).
    """
    if profile is None:
        return {
            "pattern_name": "UNKNOWN",
            "pattern_inference": (
                "Not inferred: architecture profile unavailable; no pattern inferred or claimed."
            ),
        }
    if coverage is not None and coverage.get("classified_nodes", 0) == 0:
        return {
            "pattern_name": "UNKNOWN",
            "pattern_inference": (
                f"Ungrounded: heuristic detection suggested '{profile.pattern_name}', but zero "
                "nodes were classified into architectural layers, so the inference has no "
                "classified evidence and no pattern is claimed."
            ),
        }
    return {
        "pattern_name": profile.pattern_name,
        "pattern_inference": (
            "Heuristically inferred from AST signatures & layer directory conventions; "
            "not a verified declared pattern."
        ),
    }


def assess_conformance(
    profile: Optional[ArchitectureProfile],
    coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Single source of truth for the conformance verdict, shared by the
    bundler (markdown + JSON) and the report (markdown + JSON-LD).

    ``coverage`` is the dict returned by :func:`compute_detector_coverage`, or
    None when the caller cannot access the graph (denominators published as
    unavailable instead of fabricated).
    """
    violations = profile.violations if profile else None

    if violations is None:
        # Detector never ran, so no edge counts as assessed.
        if coverage is not None:
            coverage = dict(coverage)
            coverage["assessed_edges"] = 0
            coverage["assessed_edge_fraction"] = 0.0
        status = CONFORMANCE_NOT_ASSESSED
        summary = "Architecture profile unavailable; the violation detector did not run."
    elif violations:
        status = CONFORMANCE_VIOLATIONS_DETECTED
        summary = (
            f"{len(violations)} candidate finding(s) from heuristic rules; each is anchored "
            "to the observed edge (source/target symbols and paths) and is NOT verified "
            "against any declared layer policy."
        )
    elif coverage is None:
        status = CONFORMANCE_NO_DETECTED_VIOLATIONS
        summary = (
            "Detector ran and produced no findings, but this report path has no graph access, "
            "so the in-scope edge denominator is unavailable. Absence of findings is not "
            "evidence of conformance."
        )
    elif coverage["assessed_edges"] == 0:
        status = CONFORMANCE_NOT_ASSESSED
        summary = (
            "No layer policy observable and no edges within the detector's supported scope; "
            "the detector had nothing to assess. Absence of findings is not evidence of conformance."
        )
    else:
        status = CONFORMANCE_NO_DETECTED_VIOLATIONS
        summary = (
            f"Detector ran over {coverage['assessed_edges']} in-scope edge(s) and found no "
            "violations within the supported scope. Strict conformance is NOT claimed: the "
            "layer policy is not observable and classification is heuristic."
        )

    return {
        "status": status,
        "summary": summary,
        "layer_policy_observable": False,
        "strict_conformance_claimed": False,
        "violations_detected": len(violations) if violations else 0,
        "finding_nature": "HEURISTIC_RULE_CANDIDATES",
        "detector": _detector_block(coverage),
    }
