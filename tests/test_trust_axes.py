"""
tests/test_trust_axes.py - Four-axes trust interface (Roadmap P1-3).

Covers:
- Axis independence: query_relevance is raw-query lexical evidence only
  (never anchor state); identity is whole-index name resolution (never the
  query); anchor_freshness is the disk measurement; scope_completeness is
  a result-set property (unknown per hit, asserted on the envelope).
- Conservative honesty: unmeasured dimensions are explicit "unknown";
  "exhaustive" is never emitted by search.
- Legacy verdict (STRONG/...) remains a compatibility field only and is
  preserved for existing callers.
- Surfaces: CLI search (JSON + human) and MCP search results.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from sot_graph.cli import cmd_search
from sot_graph.db import Database, identity_name_counts
from sot_graph.evidence import (
    AXES_SCHEMA_VERSION,
    AXES_SEMANTICS,
    CompletenessStatus,
    FreshnessStatus,
    LEGACY_VERDICT_NOTE,
    RelevanceType,
    ResolutionStatus,
    TrustEvidence,
    derive_trust_axes,
    query_names_identity,
)
from sot_graph.mcp_service import McpService
from sot_graph.reconciler import Reconciler

AXIS_NAMES = {
    "anchor_freshness",
    "identity",
    "query_relevance",
    "scope_completeness",
}


def _ev(
    freshness: FreshnessStatus = FreshnessStatus.FRESH,
    relevance: RelevanceType = RelevanceType.EXACT_SYMBOL,
    coverage=None,
    details=None,
) -> TrustEvidence:
    return TrustEvidence(
        freshness=freshness,
        relevance=relevance,
        resolution=ResolutionStatus.EXACT,
        completeness=CompletenessStatus.COMPLETE_WITHIN_INDEX_CAPABILITY,
        confidence=0.9,
        provenance="test",
        file_path="x.py",
        coverage=coverage,
        details=details or {},
    )


def _axes(
    *,
    freshness: FreshnessStatus = FreshnessStatus.FRESH,
    relevance: RelevanceType = RelevanceType.EXACT_SYMBOL,
    coverage: Optional[float] = None,
    details: Optional[dict] = None,
    **axis_kwargs: Any,
) -> Dict[str, str]:
    return derive_trust_axes(
        _ev(freshness=freshness, relevance=relevance, coverage=coverage, details=details),
        **axis_kwargs,
    )


# ---------------------------------------------------------------------------
# Pure derivation units
# ---------------------------------------------------------------------------


class TestAxisIndependence:
    def test_freshness_is_direct_disk_mapping(self):
        mapping = {
            FreshnessStatus.FRESH: "fresh",
            FreshnessStatus.STALE: "stale",
            FreshnessStatus.MISSING: "missing",
            FreshnessStatus.UNKNOWN: "unknown",
        }
        for status, value in mapping.items():
            assert _axes(freshness=status)["anchor_freshness"] == value

    def test_exact_relevance_survives_stale_anchor(self):
        """exact = verified lexical identity naming; staleness lives on the
        freshness axis and must not downgrade relevance."""
        named: Dict[str, Any] = dict(
            query="solo_fn", label="solo_fn", fqn="mod.solo_fn", same_identity_count=1
        )
        fresh = derive_trust_axes(_ev(freshness=FreshnessStatus.FRESH), **named)
        stale = derive_trust_axes(_ev(freshness=FreshnessStatus.STALE), **named)
        assert fresh["query_relevance"] == "exact"
        assert stale["query_relevance"] == "exact"
        assert fresh["anchor_freshness"] == "fresh"
        assert stale["anchor_freshness"] == "stale"

    def test_identity_is_query_independent(self):
        with_query = derive_trust_axes(
            _ev(), query="something_else", label="solo_fn", same_identity_count=3
        )
        without_query = derive_trust_axes(
            _ev(), query="", label="solo_fn", same_identity_count=3
        )
        assert with_query["identity"] == without_query["identity"] == "ambiguous"

    def test_relevance_ignores_anchor_relevance_enum(self):
        """Anchor evidence (EXACT_SPAN etc.) alone must never imply query
        relevance: unnamed + unmeasured query coverage stays unknown."""
        axes = derive_trust_axes(
            _ev(relevance=RelevanceType.EXACT_SPAN, coverage=None),
            query="unrelated words",
            label="solo_fn",
            same_identity_count=1,
        )
        assert axes["query_relevance"] == "unknown"


class TestIdentityAxis:
    @pytest.mark.parametrize(
        "count,expected",
        [
            (1, "unique"),
            (2, "ambiguous"),
            (17, "ambiguous"),
            (None, "unknown"),
            (0, "unknown"),
        ],
    )
    def test_count_mapping(self, count, expected):
        axes = derive_trust_axes(_ev(), label="solo_fn", same_identity_count=count)
        assert axes["identity"] == expected

    def test_no_indexed_name_is_unresolved(self):
        axes = derive_trust_axes(_ev(), label="", fqn="", same_identity_count=1)
        assert axes["identity"] == "unresolved"

    def test_unmeasured_count_is_unknown_even_when_named(self):
        axes = derive_trust_axes(_ev(), query="solo_fn", label="solo_fn")
        assert axes["identity"] == "unknown"


class TestQueryRelevanceAxis:
    def test_named_is_exact(self):
        axes = derive_trust_axes(
            _ev(),
            query="solo_fn",
            label="solo_fn",
            same_identity_count=1,
            query_token_coverage=None,
        )
        assert axes["query_relevance"] == "exact"

    def test_raw_query_token_coverage_semantic(self):
        axes = derive_trust_axes(
            _ev(coverage=1.0),
            query="zephyr_calc word",
            label="solo_fn",
            same_identity_count=1,
            query_token_coverage=0.5,
        )
        assert axes["query_relevance"] == "semantic"

    def test_zero_measured_coverage_is_weak(self):
        axes = derive_trust_axes(
            _ev(coverage=0.0),
            query="zzz qqq",
            label="solo_fn",
            same_identity_count=1,
            query_token_coverage=0.0,
        )
        assert axes["query_relevance"] == "weak"

    def test_unmeasured_query_is_unknown_not_semantic(self):
        axes = derive_trust_axes(
            _ev(coverage=None),
            query="zzz qqq",
            label="solo_fn",
            same_identity_count=1,
            query_token_coverage=None,
        )
        assert axes["query_relevance"] == "unknown"

    @pytest.mark.parametrize(
        "detail", ["nopath", "outside_root", "oversized", "binary", "error"]
    )
    def test_unmeasurable_anchor_stays_unknown(self, detail):
        """Documented conservative choice: the index-string comparison would
        technically be measurable, but an unverifiable anchor stays unknown."""
        axes = derive_trust_axes(
            _ev(details={detail: True}),
            query="solo_fn",
            label="solo_fn",
            same_identity_count=1,
        )
        assert axes["query_relevance"] == "unknown"


class TestRemovedAnchor:
    """details.removed = purged anchor: never labelled fresh."""

    def test_fresh_plus_removed_is_not_fresh(self):
        axes = derive_trust_axes(
            _ev(
                freshness=FreshnessStatus.FRESH,
                relevance=RelevanceType.NAME_ONLY,
                details={"removed": True, "stale": False},
            ),
            query="solo_fn",
            label="solo_fn",
            same_identity_count=1,
        )
        assert axes["anchor_freshness"] == "unknown"
        assert axes["query_relevance"] == "unknown"

    def test_unknown_freshness_zero_coverage_plus_removed(self):
        axes = derive_trust_axes(
            _ev(
                freshness=FreshnessStatus.UNKNOWN,
                relevance=RelevanceType.UNKNOWN,
                coverage=0.0,
                details={"removed": True},
            ),
            query="zzz",
            label="solo_fn",
            same_identity_count=1,
            query_token_coverage=0.0,
        )
        assert axes["anchor_freshness"] == "unknown"
        assert axes["query_relevance"] == "unknown"
        assert axes["scope_completeness"] == "unknown"

    def test_measured_missing_plus_removed_is_missing(self):
        axes = derive_trust_axes(
            _ev(freshness=FreshnessStatus.MISSING, details={"removed": True})
        )
        assert axes["anchor_freshness"] == "missing"


class TestScopeCompletenessAxis:
    @pytest.mark.parametrize(
        "freshness,details",
        [
            (FreshnessStatus.FRESH, {}),
            (FreshnessStatus.STALE, {}),
            (FreshnessStatus.MISSING, {"missing": True}),
            (FreshnessStatus.UNKNOWN, {"oversized": True}),
            (FreshnessStatus.UNKNOWN, {"nopath": True}),
        ],
    )
    def test_per_hit_scope_is_unknown_never_exhaustive(self, freshness, details):
        """Retrieval-cap/index-coverage is a result-set property: per-hit
        search evidence cannot establish it, so search emits unknown and the
        envelope asserts bounded."""
        axes = derive_trust_axes(_ev(freshness=freshness, details=details))
        assert axes["scope_completeness"] == "unknown"
        assert axes["scope_completeness"] != "exhaustive"


class TestQueryNamesIdentity:
    @pytest.mark.parametrize(
        "query,label,fqn,expected",
        [
            ("solo_fn", "solo_fn", "mod.solo_fn", True),
            ("solo_fn", "solo_fn", "", True),
            ("solo_fn", "solo_fn", "pkg::solo_fn", True),
            ("Fn", "other", "pkg.mod.Fn", True),
            ("mod.solo_fn", "solo_fn", "mod.solo_fn", True),
            ("solo other", "solo_fn", "mod.solo_fn", False),
            ("solo", "solo_fn", "mod.solo_fn", False),
            ("", "solo_fn", "mod.solo_fn", False),
            ("whatever", "", "", False),
        ],
    )
    def test_alignment_rules(self, query, label, fqn, expected):
        assert query_names_identity(query, label, fqn) is expected


class TestSemanticsContract:
    def test_semantics_cover_all_axes(self):
        assert set(AXES_SEMANTICS) == AXIS_NAMES

    def test_schema_version_is_int(self):
        assert isinstance(AXES_SCHEMA_VERSION, int)

    def test_legacy_note_marks_compat_only(self):
        assert "compatibility" in LEGACY_VERDICT_NOTE
        assert "autonomous" in LEGACY_VERDICT_NOTE


# ---------------------------------------------------------------------------
# Whole-index identity counting helper
# ---------------------------------------------------------------------------


class TestIdentityNameCounts:
    def test_counts_whole_index_batched(self, repo: Path):
        db = Database(str(repo / ".sot" / "sot.db"))
        try:
            counts = identity_name_counts(
                db.conn, ["solo_fn", "dup_fn", "missing_name"]
            )
        finally:
            db.close()
        assert counts.get("solo_fn") == 1
        assert counts.get("dup_fn") == 2
        assert "missing_name" not in counts

    def test_empty_labels_short_circuit(self, repo: Path):
        db = Database(str(repo / ".sot" / "sot.db"))
        try:
            assert identity_name_counts(db.conn, []) == {}
            assert identity_name_counts(db.conn, [None, "  "]) == {}
        finally:
            db.close()

    def test_broken_connection_returns_empty(self):
        conn = sqlite3.connect(":memory:")
        assert identity_name_counts(conn, ["x"]) == {}
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures / CLI + MCP surfaces
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def solo_fn():\n"
        "    return 1\n"
        "\n\n"
        "def caller():\n"
        "    return solo_fn()\n"
        "\n\n"
        "ZEPHYR_CALC = 'zephyr_calc'\n",
        encoding="utf-8",
    )
    (repo / "b.py").write_text("def dup_fn():\n    return 2\n", encoding="utf-8")
    (repo / "c.py").write_text("def dup_fn():\n    return 3\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()
    finally:
        db.close()
    return repo


def _cli_args(query: str, as_json: bool = True, limit: int = 10) -> argparse.Namespace:
    return argparse.Namespace(
        query=query,
        json=as_json,
        limit=limit,
        scope=None,
        threshold=0.5,
        jit=False,
        hybrid=False,
    )


def _search_cli(
    repo: Path,
    query: str,
    as_json: bool = True,
    capsys: Optional[pytest.CaptureFixture] = None,
):
    assert capsys is not None, "capsys fixture required"
    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        rc = cmd_search(_cli_args(query, as_json), db, str(repo))
    finally:
        db.close()
    assert rc == 0
    out = capsys.readouterr().out
    if as_json:
        return json.loads(out)["data"]
    return out


def _hit(results, symbol: str):
    matches = [r for r in results if r.get("symbol") == symbol]
    assert matches, f"no hit with symbol {symbol!r}"
    return matches[0]


class TestCliSearchAxes:
    def test_json_result_carries_axes_and_compat_fields(self, repo, capsys):
        data = _search_cli(repo, "solo_fn", capsys=capsys)
        hit = _hit(data["results"], "solo_fn")
        assert set(hit["axes"]) == AXIS_NAMES
        # legacy compat fields untouched
        assert hit["verdict"] in {
            "STRONG",
            "WEAK",
            "STALE",
            "REBUILT",
            "REMOVED",
            "NOPATH",
        }
        assert hit["evidence"]["legacy_verdict"] == hit["verdict"]

    def test_unique_named_hit_axes(self, repo, capsys):
        data = _search_cli(repo, "solo_fn", capsys=capsys)
        hit = _hit(data["results"], "solo_fn")
        assert hit["axes"]["identity"] == "unique"
        assert hit["axes"]["query_relevance"] == "exact"
        assert hit["axes"]["anchor_freshness"] == "fresh"
        assert hit["axes"]["scope_completeness"] == "unknown"

    def test_ambiguous_identity_on_duplicated_name(self, repo, capsys):
        data = _search_cli(repo, "dup_fn", capsys=capsys)
        hit = _hit(data["results"], "dup_fn")
        assert hit["axes"]["identity"] == "ambiguous"

    def test_unnamed_token_hit_is_semantic(self, repo, capsys):
        data = _search_cli(repo, "zephyr_calc", capsys=capsys)
        file_hit = _hit(data["results"], "app.py")
        assert file_hit["axes"]["query_relevance"] == "semantic"

    def test_stopword_only_query_honest_unknown(self, repo, capsys):
        """'return' is a verifier stop word: no raw-query coverage measured,
        so unnamed hits must report unknown — never a fabricated level."""
        data = _search_cli(repo, "return", capsys=capsys)
        for hit in data["results"]:
            assert hit["axes"]["query_relevance"] == "unknown"

    def test_stale_anchor_keeps_exact_relevance(self, repo, capsys):
        (repo / "app.py").write_text(
            "def solo_fn():\n    return 999\n", encoding="utf-8"
        )
        data = _search_cli(repo, "solo_fn", capsys=capsys)
        hit = _hit(data["results"], "solo_fn")
        assert hit["axes"]["anchor_freshness"] == "stale"
        assert hit["axes"]["query_relevance"] == "exact"
        assert hit["axes"]["identity"] == "unique"

    def test_envelope_scope_and_semantics(self, repo, capsys):
        data = _search_cli(repo, "solo_fn", capsys=capsys)
        assert data["axes_schema_version"] == AXES_SCHEMA_VERSION
        assert set(data["axes_semantics"]) == AXIS_NAMES
        assert "compatibility" in data["legacy_verdict_note"]
        assert data["result_set"]["scope_completeness"] == "bounded"

    def test_never_claims_exhaustive(self, repo, capsys):
        data = _search_cli(repo, "dup_fn", capsys=capsys)
        for hit in data["results"]:
            assert hit["axes"]["scope_completeness"] != "exhaustive"
        assert data["result_set"]["scope_completeness"] == "bounded"
        assert data["result_set"]["scope_completeness"] != "exhaustive"

    def test_human_output_shows_axes_and_legend(self, repo, capsys):
        out = _search_cli(repo, "solo_fn", as_json=False, capsys=capsys)
        assert "legacy anchor-compat field" in out
        assert "🧭 anchor=" in out
        assert "identity=" in out and "relevance=" in out and "scope=" in out


class TestMcpSearchAxes:
    def test_results_carry_axes_and_contract(self, repo: Path):
        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        try:
            res = service.search("solo_fn")
        finally:
            service.close() if hasattr(service, "close") else None
        assert set(res) >= {"axes_semantics", "legacy_verdict_note", "result_set"}
        assert set(res["axes_semantics"]) == AXIS_NAMES
        assert res["result_set"]["scope_completeness"] == "bounded"
        assert res["results"], "expected at least one hit"
        for hit in res["results"]:
            assert set(hit["axes"]) == AXIS_NAMES
            assert hit["verdict"]  # legacy compat preserved
        solo = _hit(res["results"], "solo_fn")
        assert solo["axes"] == {
            "anchor_freshness": "fresh",
            "identity": "unique",
            "query_relevance": "exact",
            "scope_completeness": "unknown",
        }

    def test_ambiguous_identity_on_mcp(self, repo: Path):
        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        res = service.search("dup_fn")
        dup = _hit(res["results"], "dup_fn")
        assert dup["axes"]["identity"] == "ambiguous"
        assert dup["axes"]["query_relevance"] == "exact"

    def test_empty_results_still_expose_contract(self, repo: Path):
        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        res = service.search("qqzzxxnohit")
        assert res["results"] == []
        assert set(res["axes_semantics"]) == AXIS_NAMES
        assert res["result_set"]["scope_completeness"] == "bounded"
