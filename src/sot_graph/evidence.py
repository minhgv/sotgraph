"""
sot_graph.evidence — Multi-dimensional Trust Evidence Model (Trust Model v2).

Provides fine-grained, independent dimensions for trust evaluation:
- Freshness: Physical disk synchronization state.
- Relevance: Level of AST symbol / span / token alignment.
- Resolution: Graph edge linkage certainty.
- Completeness: Discovery boundary and presence of unresolved edges.
- Confidence: Calibrated floating score (0.0 .. 1.0).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class FreshnessStatus(str, Enum):
    """Physical file status on disk relative to database index."""

    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class RelevanceType(str, Enum):
    """Semantic relevance level between query / node and physical disk contents."""

    EXACT_SYMBOL = "EXACT_SYMBOL"
    EXACT_SPAN = "EXACT_SPAN"
    FILE_TOKEN = "FILE_TOKEN"
    NAME_ONLY = "NAME_ONLY"
    UNKNOWN = "UNKNOWN"


class ResolutionStatus(str, Enum):
    """AST / Call graph resolution certainty."""

    EXACT = "EXACT"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CompletenessStatus(str, Enum):
    """Discovery completeness of usages, implementations, or graph neighborhood."""

    COMPLETE = "COMPLETE"
    COMPLETE_WITHIN_INDEX_CAPABILITY = "COMPLETE_WITHIN_INDEX_CAPABILITY"
    KNOWN_GAPS = "KNOWN_GAPS"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# Four-axes trust interface (Roadmap P1-3).
#
# Independent dimensions, each backed by its own measurement; "unknown" is
# emitted explicitly wherever a dimension was not measured. The legacy
# verdict (STRONG/WEAK/...) stays a backward-compatibility field only: it
# describes anchor verification and never implies answer correctness or
# scope coverage, and must not drive autonomous decisions.
# ---------------------------------------------------------------------------

AXES_SCHEMA_VERSION = 1


class AnchorFreshnessAxis(str, Enum):
    """Axis 1 — indexed anchor vs current disk state (disk measurement)."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


class IdentityAxis(str, Enum):
    """Axis 2 — does this hit's indexed name resolve uniquely in the index?

    Counted over the ENTIRE index (never just returned top-k). Independent
    of the query text; "unresolved" means the hit carries no indexed name.
    """

    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    UNKNOWN = "unknown"


class QueryRelevanceAxis(str, Enum):
    """Axis 3 — measured query-to-hit LEXICAL alignment (evidence levels,
    not a calibrated similarity or correctness score).

    exact: query string exactly names the hit's indexed identity. Verified
    string alignment only — no freshness/correctness claim (staleness lives
    on axis 1). semantic: measured query-token overlap with hit content.
    weak: identity unnamed and no measured token overlap. unknown: query
    alignment not measured.
    """

    EXACT = "exact"
    SEMANTIC = "semantic"
    WEAK = "weak"
    UNKNOWN = "unknown"


class ScopeCompletenessAxis(str, Enum):
    """Axis 4 — retrieval-cap / index-coverage bounds of a result set.

    A result-set property: per-hit it stays "unknown" unless the caller can
    prove coverage; bounded/exhaustive are asserted at envelope level.
    """

    EXHAUSTIVE = "exhaustive"
    BOUNDED = "bounded"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


#: One-line semantics shipped with JSON/MCP responses.
AXES_SEMANTICS: Dict[str, str] = {
    "anchor_freshness": "indexed anchor vs disk: fresh|stale|missing|unknown",
    "identity": "hit's indexed name unique in full index: unique|ambiguous|unresolved|unknown",
    "query_relevance": "query-to-hit lexical heuristic: exact(identity name)|semantic(raw-query token coverage)|weak|unknown; not calibrated, not correctness",
    "scope_completeness": "result-set retrieval/index coverage: exhaustive|bounded|partial|unknown; never repo coverage",
}

LEGACY_VERDICT_NOTE = (
    "verdict/legacy_verdict (e.g. STRONG) is a backward-compatibility field "
    "describing anchor verification only; not for autonomous decisions and "
    "never a correctness or scope-coverage claim. Use the four axes."
)


def query_names_identity(query: str, identity_name: str, fqn: str) -> bool:
    """True when the stripped query string exactly names the indexed identity
    (the node's bare symbol name, or the qualified name on '.' / '::'
    boundaries)."""
    q = (query or "").strip().strip("\"'")
    if not q or " " in q.strip():
        return False
    identity_name = (identity_name or "").strip()
    if identity_name and q == identity_name:
        return True
    return bool(fqn) and (fqn == q or fqn.endswith("." + q) or fqn.endswith("::" + q))


def derive_trust_axes(
    evidence: TrustEvidence,
    *,
    query: str = "",
    same_identity_count: Optional[int] = None,
    symbol: str = "",
    label: str = "",
    fqn: str = "",
    query_token_coverage: Optional[float] = None,
) -> Dict[str, str]:
    """Derive the four axes for one hit. Every value traces to its own
    measurement: disk verification (freshness), an index COUNT over all
    nodes (identity), raw-query naming + ``query_token_coverage``
    (relevance). Unmeasured dimensions are explicit "unknown".

    ``query_token_coverage`` MUST be measured from the RAW USER QUERY
    (fraction of the user's query tokens found in the hit's current file
    content) — never from anchor/keyword-derived coverage. Pass None when
    the query was not measured against the hit. In the CLI/MCP search
    paths, TrustEvidence.coverage is exactly this measurement (the verifier
    is invoked with tokenize(raw_query)), so those call sites forward it.

    Conservatively, hits whose anchor could not be measured at all
    (nopath / outside-root / oversized / binary / read error) stay
    relevance-unknown even though the index-string name comparison would
    technically be measurable. scope_completeness is a result-set property:
    this per-hit derivation never claims bounded/exhaustive — the search
    envelope asserts that.
    """
    details = evidence.details or {}
    unmeasurable = bool(
        details.get("nopath")
        or details.get("outside_root")
        or details.get("oversized")
        or details.get("binary")
        or details.get("error")
        or details.get("removed")
    )

    freshness_map = {
        FreshnessStatus.FRESH: AnchorFreshnessAxis.FRESH,
        FreshnessStatus.STALE: AnchorFreshnessAxis.STALE,
        FreshnessStatus.MISSING: AnchorFreshnessAxis.MISSING,
        FreshnessStatus.UNKNOWN: AnchorFreshnessAxis.UNKNOWN,
    }
    if details.get("removed"):
        # Purged-from-graph marker: the anchor is gone. "missing" only when
        # the verifier measured the file as missing; a graph purge alone
        # (e.g. jit-reconcile removal on an otherwise fresh file) stays
        # conservatively "unknown" — never "fresh".
        anchor_freshness = (
            AnchorFreshnessAxis.MISSING
            if evidence.freshness == FreshnessStatus.MISSING
            else AnchorFreshnessAxis.UNKNOWN
        )
    else:
        anchor_freshness = freshness_map[evidence.freshness]

    # Axis 2 — index-name resolution, query-independent. A hit's identity
    # name is its bare symbol, falling back to label for symbol-less rows.
    identity_name = (symbol or "").strip() or (label or "").strip()
    if not identity_name and not (fqn or "").strip():
        identity = IdentityAxis.UNRESOLVED
    elif same_identity_count is None:
        identity = IdentityAxis.UNKNOWN
    elif same_identity_count <= 0:
        identity = IdentityAxis.UNKNOWN  # count inconsistent with the hit
    elif same_identity_count == 1:
        identity = IdentityAxis.UNIQUE
    else:
        identity = IdentityAxis.AMBIGUOUS

    # Axis 3 — raw-query-to-hit lexical evidence ONLY (never anchor
    # evidence): exact = query names the indexed identity; semantic =
    # measured raw-query token coverage > 0; weak = no measured overlap;
    # unknown = query alignment unmeasured.
    named = query_names_identity(query, identity_name, fqn)
    if unmeasurable:
        relevance = QueryRelevanceAxis.UNKNOWN
    elif named:
        relevance = QueryRelevanceAxis.EXACT
    elif query_token_coverage is None:
        relevance = QueryRelevanceAxis.UNKNOWN
    elif query_token_coverage > 0:
        relevance = QueryRelevanceAxis.SEMANTIC
    else:
        relevance = QueryRelevanceAxis.WEAK

    return {
        "anchor_freshness": anchor_freshness.value,
        "identity": identity.value,
        "query_relevance": relevance.value,
        "scope_completeness": ScopeCompletenessAxis.UNKNOWN.value,
    }


@dataclass(frozen=True)
class TrustEvidence:
    """Comprehensive multi-dimensional trust evidence for search hits and graph nodes."""

    freshness: FreshnessStatus
    relevance: RelevanceType
    resolution: ResolutionStatus
    completeness: CompletenessStatus
    confidence: float
    provenance: str = "trust_verifier:v2"
    file_path: str = ""
    file_hash: Optional[str] = None
    coverage: Optional[float] = None
    resolved_count: int = 0
    unresolved_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_verdict(self) -> str:
        """Convert multi-dimensional evidence to legacy verdict string for backward compatibility."""
        if self.details.get("nopath"):
            return "NOPATH"
        if self.details.get("removed"):
            return "REMOVED"
        if self.details.get("rehomed"):
            return "REBUILT"
        if self.freshness in (FreshnessStatus.MISSING, FreshnessStatus.STALE):
            return "STALE"
        if self.freshness == FreshnessStatus.UNKNOWN:
            return "WEAK"
        if self.freshness == FreshnessStatus.FRESH:
            if self.relevance in (RelevanceType.EXACT_SYMBOL, RelevanceType.EXACT_SPAN):
                return "STRONG" if self.confidence >= 0.7 else "WEAK"
            if self.confidence >= 0.5:
                return "STRONG"
            return "WEAK"
        return "WEAK"

    @property
    def is_grounded(self) -> bool:
        """Returns True if the evidence reflects a fresh, resolved, and verified physical asset."""
        return (
            self.freshness == FreshnessStatus.FRESH
            and self.confidence >= 0.5
            and self.resolution in (ResolutionStatus.EXACT, ResolutionStatus.INFERRED)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize evidence to dictionary."""
        d = asdict(self)
        d["legacy_verdict"] = self.to_legacy_verdict()
        return d
