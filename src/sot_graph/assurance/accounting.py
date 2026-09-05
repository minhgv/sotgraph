"""SG-107 accounting contract — stable cap/collector id registry (P1-4).

Every bounded collection in the assurance package carries a STABLE
source id that lands in ``AssuranceFacts.truncation_sources`` (and
therefore in ``collection_truncated:<source>`` reason codes) whenever
the cap actually cuts a collection. This module is the single source of
truth for those ids and for the collectors that own them.

Why a registry (advisor P1-4): the previous contract test bound each
accounting site to ``(filename, SOURCE LINE NUMBER)``, so adding or
moving innocent lines in ``receipts.py`` broke the tripwire for the
wrong reason. The registry binds sites to ``(module, collector)``
instead — names that survive line drift — and exposes:

- :func:`ensure_accounted` — production-side fail-closed gate: receipt
  builders call it so an UNREGISTERED accounting source can never enter
  a receipt (it raises instead of silently emitting).
- :func:`iter_sql_limit_sites` / :func:`unregistered_limit_sites` —
  an AST sweep (line-independent by construction) that finds every SQL
  ``LIMIT`` literal under the assurance package and maps it to the
  enclosing collector, so a NEW silent cap cannot land unnoticed.
- :func:`registry_source_ids` — the id set the contract tests must be
  able to trigger in real receipts.

Non-truncating lookups (``LIMIT 1`` probes that return 0/1 rows) are
allowlisted per collector with a justification, never silently.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

__all__ = [
    "RECEIPT_CITED_FILE_CAP",
    "EDGES_SOURCE",
    "EVIDENCE_SOURCE",
    "LEDGER_RUNS_SOURCE",
    "TRANSITIVE_SOURCE",
    "CHANGED_FILES_SOURCE",
    "LEDGER_UNION_SOURCE_PATTERN",
    "ledger_union_source",
    "is_ledger_union_source",
    "AccountingSite",
    "LimitSite",
    "ACCOUNTED_SITES",
    "CAP_SOURCES_BY_ID",
    "NON_TRUNCATING_COLLECTORS",
    "LOGICAL_COLLECTION_SOURCES",
    "LEGACY_REASON_CODES",
    "reason_code_for",
    "assurance_package_dir",
    "registry_source_ids",
    "is_accounted_source",
    "ensure_accounted",
    "UnaccountedSource",
    "iter_sql_limit_sites",
    "unregistered_limit_sites",
    "unbacked_registry_sites",
]


#: Bounded-work cap on how many changed files a post-change receipt will
#: measure (journal staleness, evidence invalidation, snapshot citation).
#: The cap itself is fine; hiding it was not — receipts above the cap
#: carry ``changed_files_total`` / ``changed_files_truncated`` so the
#: partial closure evidence is visible instead of silently assumed
#: whole. (Owned here so the registry and the receipts agree; receipts
#: re-exports it for backward compatibility.)
RECEIPT_CITED_FILE_CAP = 200

# ---------------------------------------------------------------------------
# Stable source ids — these exact strings land in
# ``facts.truncation_sources`` / reason codes, so they may be extended
# but never renamed (receipts and operator tooling match on them).
# ---------------------------------------------------------------------------

EDGES_SOURCE = "edges_cap_500"
EVIDENCE_SOURCE = "evidence_cap_50"
LEDGER_RUNS_SOURCE = "ledger_runs_cap_200"
TRANSITIVE_SOURCE = "transitive_cap_200"
CHANGED_FILES_SOURCE = f"changed_files_cap_{RECEIPT_CITED_FILE_CAP}"

#: The evidence-union cap is caller-supplied, so its id is parametric:
#: ``ledger_union_cap_<limit>`` (receipts use ``ledger_union_cap_5000``).
LEDGER_UNION_SOURCE_PATTERN = "ledger_union_cap_<limit>"
_UNION_ID_RE = re.compile(r"^ledger_union_cap_\d+$")


def ledger_union_source(cap: Optional[int]) -> str:
    """Build the parametric evidence-union source id for one cap value."""
    return f"ledger_union_cap_{int(cap or 0)}"


def is_ledger_union_source(source_id: str) -> bool:
    """True when ``source_id`` belongs to the parametric union family."""
    return bool(_UNION_ID_RE.match(str(source_id)))


@dataclass(frozen=True)
class AccountingSite:
    """One registered accounting site.

    ``source_id`` is the stable diagnostic id; ``cap`` is ``None`` for
    the parametric union family; ``(module, collector)`` names the
    owning function INSIDE the assurance package — the registry binds
    to these, never to source line numbers.
    """

    source_id: str
    cap: Optional[int]
    module: str
    collector: str
    #: True when the cap is enforced by a SQL ``LIMIT`` in the collector
    #: (discoverable by :func:`iter_sql_limit_sites`); False for
    #: Python-level caps (BFS limit, list slice).
    sql_backed: bool
    description: str = ""


#: Every collection-bounding cap in the assurance package. A new cap
#: MUST land here (with accounting: twin COUNT + named truncation
#: source) — the contract tests fail on both an unregistered cap site
#: and a registry entry whose collector vanished.
ACCOUNTED_SITES: Tuple[AccountingSite, ...] = (
    AccountingSite(
        source_id=EDGES_SOURCE,
        cap=500,
        module="receipts",
        collector="_edges_of",
        sql_backed=True,
        description="one-hop callers/callees/relations rows per query",
    ),
    AccountingSite(
        source_id=EVIDENCE_SOURCE,
        cap=50,
        module="receipts",
        collector="diff_impact_receipt",
        sql_backed=True,
        description="invalidated provider_evidence rows per changed path",
    ),
    AccountingSite(
        source_id=LEDGER_RUNS_SOURCE,
        cap=200,
        module="receipts",
        collector="_ledger_cross_check",
        sql_backed=True,
        description="recent provider_runs window per ledger cross-check",
    ),
    AccountingSite(
        source_id=LEDGER_UNION_SOURCE_PATTERN,
        cap=None,  # parametric: ledger_union_cap_<caller limit>
        module="ledger",
        collector="union_evidence",
        sql_backed=True,
        description="evidence union rows (caller-supplied limit)",
    ),
    AccountingSite(
        source_id=TRANSITIVE_SOURCE,
        cap=200,
        module="receipts",
        collector="scope_receipt",
        sql_backed=False,
        description="bounded transitive BFS walk (db.explore_node limit)",
    ),
    AccountingSite(
        source_id=CHANGED_FILES_SOURCE,
        cap=RECEIPT_CITED_FILE_CAP,
        module="receipts",
        collector="diff_impact_receipt",
        sql_backed=False,
        description="changed files measured by one post-change receipt",
    ),
)

#: Collectors whose SQL ``LIMIT`` is a LOOKUP, not a bounded collection:
#: 0/1 rows, ambiguity surfaced by the decision path instead. Keyed by
#: ``(module, collector)`` with a justification — the line-independent
#: successor of the old ``_NON_TRUNCATING_LIMITS`` mapping.
NON_TRUNCATING_COLLECTORS: Dict[Tuple[str, str], str] = {
    ("engine", "resolve_symbol"): (
        "exact-symbol + LIKE disambiguation probes; LIMIT 1 returns 0/1 "
        "rows — a lookup, not a bounded collection; decision paths use "
        "resolve_symbol_identity (no LIMIT — ambiguity surfaced)"
    ),
}

#: Receipt ``collection_stats`` logical collection name → the stable
#: source id (or id family) that accounts for it. Merges per-query
#: stats (merge_collection_stats) onto registry ids.
LOGICAL_COLLECTION_SOURCES: Dict[str, str] = {
    "direct_edges": EDGES_SOURCE,
    "relations": EDGES_SOURCE,
    "transitive": TRANSITIVE_SOURCE,
    "ledger_runs": LEDGER_RUNS_SOURCE,
    "ledger_union": LEDGER_UNION_SOURCE_PATTERN,
    "changed_files": CHANGED_FILES_SOURCE,
    "invalidated_evidence": EVIDENCE_SOURCE,
}

CAP_SOURCES_BY_ID: Dict[str, AccountingSite] = {
    site.source_id: site for site in ACCOUNTED_SITES
}


def assurance_package_dir() -> Path:
    """Directory of the assurance package (sweep root)."""
    return Path(__file__).resolve().parent


def registry_source_ids() -> Set[str]:
    """Every id the contract must be able to surface in a receipt.

    Static ids plus the union family's pattern sentinel; parametric
    ``ledger_union_cap_<n>`` instances validate via
    :func:`is_ledger_union_source`.
    """
    return set(CAP_SOURCES_BY_ID)


#: The transitive BFS cap keeps its HISTORICAL reason code
#: (``transitive_truncated``, backward compat with live consumers — see
#: ``decide()`` in state.py); every other source emits the generic
#: ``collection_truncated:<source>``. The mapping lives here so the
#: contract tests derive expected diagnostics from the registry instead
#: of hardcoding per-source strings.
LEGACY_REASON_CODES: Dict[str, str] = {
    TRANSITIVE_SOURCE: "transitive_truncated",
}


def reason_code_for(source_id: str) -> str:
    """The degradation reason code emitted when ``source_id`` cuts."""
    return LEGACY_REASON_CODES.get(
        str(source_id), f"collection_truncated:{source_id}"
    )


def is_accounted_source(source_id: str) -> bool:
    """Fail-closed membership: is this truncation source registered?"""
    sid = str(source_id)
    if sid in CAP_SOURCES_BY_ID:
        return True
    return is_ledger_union_source(sid)


class UnaccountedSource(ValueError):
    """An accounting source id is not in the registry (fail-closed).

    Raised by :func:`ensure_accounted` at receipt-build time so an
    unregistered cap FAILS LOUDLY instead of silently emitting an
    accounting reason no contract test can recognize.
    """


def ensure_accounted(
    sources: Iterable[str], where: str = ""
) -> None:
    """Raise :class:`UnaccountedSource` if any source id is unregistered.

    Called by the receipt builders right before ``AssuranceFacts``
    construction: every id in ``facts.truncation_sources`` must resolve
    to a registry entry (static or parametric union family).
    """
    unknown = [str(s) for s in sources if not is_accounted_source(s)]
    if unknown:
        where_note = f" (in {where})" if where else ""
        raise UnaccountedSource(
            "UNACCOUNTED truncation source(s)"
            f"{where_note}: {unknown}. A collection-bounding cap must be "
            "registered in sot_graph.assurance.accounting.ACCOUNTED_SITES "
            "with a stable source id, twin COUNT accounting, and a named "
            "truncation source (SG-107)."
        )


# ---------------------------------------------------------------------------
# Line-independent AST sweep
# ---------------------------------------------------------------------------

_LIMIT_RE = re.compile(r"\bLIMIT\b")


@dataclass(frozen=True)
class LimitSite:
    """One SQL ``LIMIT`` literal found by the AST sweep.

    Keyed by ``(module, collector)`` — NEVER by line number, so innocent
    line insertions/removals cannot change sweep results.
    """

    module: str
    collector: str
    #: Whitespace-normalized SQL snippet containing the LIMIT.
    sql: str


class _LimitVisitor(ast.NodeVisitor):
    """Collect string constants containing ``LIMIT`` per collector.

    Standalone string-expression statements (module/class/function
    docstrings, prose) are skipped — ``LIMIT`` mentioned in prose is not
    a cap site. Comments never reach the AST.
    """

    def __init__(self, module: str) -> None:
        self.module = module
        self._fn_stack: List[str] = []
        self.sites: List[LimitSite] = []
        self._seen: Set[Tuple[str, str, str]] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Expr(self, node: ast.Expr) -> None:
        # Docstring / standalone string statement: prose, not SQL.
        if isinstance(node.value, ast.Constant):
            return
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Class body docstrings are Expr(Constant) → skipped by
        # visit_Expr; keep walking the rest of the body.
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _LIMIT_RE.search(node.value):
            sql = " ".join(node.value.split())
            collector = self._fn_stack[-1] if self._fn_stack else "<module>"
            key = (self.module, collector, sql)
            if key not in self._seen:
                self._seen.add(key)
                self.sites.append(
                    LimitSite(module=self.module, collector=collector, sql=sql)
                )


def iter_sql_limit_sites(package_dir: Path) -> List[LimitSite]:
    """Every SQL ``LIMIT`` literal under ``package_dir`` (line-free keys).

    The sweep result depends only on module names, collector names, and
    SQL text — so adding, removing, or moving innocent source lines can
    never change it. ``accounting`` itself is skipped: it owns the
    registry (ids, justifications, prose about caps), it collects
    nothing.
    """
    package_dir = Path(package_dir)
    sites: List[LimitSite] = []
    for path in sorted(package_dir.glob("*.py")):
        if path.stem == "accounting":
            continue
        tree = ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path)
        )
        visitor = _LimitVisitor(path.stem)
        visitor.visit(tree)
        sites.extend(visitor.sites)
    return sites


def unregistered_limit_sites(package_dir: Path) -> List[LimitSite]:
    """LIMIT sites that are neither accounted nor allowlisted lookups.

    Non-empty output means a NEW bounded collection landed without
    CollectionStats accounting + a registered stable source id — the
    exact false-assure bug SG-107 exists to prevent.
    """
    accounted = {
        (site.module, site.collector) for site in ACCOUNTED_SITES
    }
    return [
        site for site in iter_sql_limit_sites(package_dir)
        if (site.module, site.collector) not in accounted
        and (site.module, site.collector) not in NON_TRUNCATING_COLLECTORS
    ]


def unbacked_registry_sites(package_dir: Path) -> List[AccountingSite]:
    """SQL-backed registry entries whose collector owns no LIMIT.

    The line-independent successor of the old "stale registry entry"
    check: if a collector was renamed, its cap moved to another helper,
    or the SQL LIMIT was removed, the registry must be updated — never
    silently ignored.
    """
    with_limit = {
        (site.module, site.collector) for site in iter_sql_limit_sites(package_dir)
    }
    return [
        site for site in ACCOUNTED_SITES
        if site.sql_backed
        and (site.module, site.collector) not in with_limit
    ]
