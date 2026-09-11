"""sot_graph.receipt_explorer — read-only human views of assurance receipts (SG-205).

Answers the P1-6 operator questions for ONE serialized receipt (claim,
scope + binding, what is outside the scope, evidence, downgrade reasons,
remediation) and diffs TWO receipts — strictly from the data IN the
receipt payloads. A question the receipt cannot answer renders an
explicit "not recorded in this receipt" line; the explorer never
recomputes trust, never consults the live graph/DB, never reconciles.

Read-only by construction: every public entry point takes already-parsed
receipt data (plain dicts) and returns a string. File loading and
``ReceiptStore`` digest lookup live in the CLI layer. Inputs are never
mutated.

Schema gating: the current receipt schema version comes from
:mod:`sot_graph.assurance.receipts` so the two stay in sync. Older known
versions render best-effort under a banner; missing/garbage/newer
versions are REFUSED — an unrenderable field must never silently read as
absent-trust (a missing ``warnings`` key must not imply "no errors").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.assurance.receipts import (
    RECEIPT_SCHEMA_VERSION,
    _strip_volatile,
)

__all__ = [
    "UnsupportedReceiptVersion",
    "VersionGate",
    "KNOWN_RECEIPT_SCHEMA_VERSIONS",
    "NOT_RECORDED",
    "gate_receipt_version",
    "render_receipt",
    "diff_receipts",
]

#: Schema versions this renderer knows field-by-field. Older ones (see
#: the version-history comment on ``RECEIPT_SCHEMA_VERSION``) render
#: best-effort; anything else is refused.
KNOWN_RECEIPT_SCHEMA_VERSIONS: Tuple[str, ...] = (
    "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9",
    "1.10", "1.11", "1.12",
)

#: Explicit marker for a question the receipt's data cannot answer.
NOT_RECORDED = "not recorded in this receipt"

_MAX_VALUE_CHARS = 100


class UnsupportedReceiptVersion(ValueError):
    """The receipt's schema version is missing, malformed, or unknown."""


@dataclass(frozen=True)
class VersionGate:
    version: Optional[str]
    state: str          # "current" | "legacy" | "unsupported"
    banner: Optional[str]


def gate_receipt_version(receipt: Dict[str, Any]) -> VersionGate:
    """Classify a receipt's ``schema_version`` for rendering policy."""
    version = receipt.get("schema_version")
    if version == RECEIPT_SCHEMA_VERSION:
        return VersionGate(version=str(version), state="current", banner=None)
    if isinstance(version, str) and version in KNOWN_RECEIPT_SCHEMA_VERSIONS:
        return VersionGate(
            version=version,
            state="legacy",
            banner=(f"schema {version}: rendered best-effort; this renderer "
                    f"targets schema {RECEIPT_SCHEMA_VERSION} and fields may "
                    "be missing"),
        )
    if version is None:
        raise UnsupportedReceiptVersion(
            "receipt has no schema_version field; refusing to render "
            "(missing fields must never silently read as absent-trust)"
        )
    raise UnsupportedReceiptVersion(
        f"receipt schema_version {version!r} is not a known version "
        f"(renderer targets {RECEIPT_SCHEMA_VERSION}); refusing to render"
    )


# --------------------------------------------------------------------------
# Reason codes (canonical vocabulary from assurance/state.py decide()).
# Static explanations only — the explorer explains what the receipt
# already decided, it never re-decides.
# --------------------------------------------------------------------------
_REASON_EXPLANATIONS: Dict[str, Tuple[str, str]] = {
    # code: (what it means, how an operator typically raises the status)
    "collection_error":
        ("a collector raised while gathering evidence; the receipt is "
         "fail-closed", "inspect the warnings/collection errors, fix the "
         "underlying read failure, then re-run the receipt command"),
    "target_not_found":
        ("the requested symbol was not found in the index",
         "check the symbol spelling or reconcile so the symbol is indexed"),
    "target_ambiguous":
        ("the requested symbol resolved to multiple candidates",
         "disambiguate the target (module-qualified name) and re-run"),
    "targets_partially_resolved":
        ("a multi-target scope receipt could not resolve every target — "
         "the merged blast radius is incomplete", "check per_target in "
         "the receipt; fix or drop the unresolved target names and re-run"),
    "snapshot_unbound":
        ("the receipt is not content-bound to a worktree snapshot "
         "(no scope_digest)", "re-run the receipt command so it captures a "
         "snapshot binding"),
    "stale_sources":
        ("cited files changed after the index generation was captured",
         "run `sotgraph reconcile` to rebuild the index for the current tree"),
    "open_conflicts":
        ("the evidence ledger has unresolved builtin-vs-provider conflicts",
         "resolve the conflicting provider evidence, then re-run"),
    "rename_gate_blocked":
        ("the rename/delete gate blocked this change",
         "address the gate reason in assurance.rename_gate before proceeding"),
    "transitive_truncated":
        ("the transitive impact walk hit its cap; impact beyond the cut is "
         "unexamined", "raise the depth/cap budget only with awareness of "
         "the unexamined tail"),
    "parser_failures":
        ("some files failed to parse and are excluded from evidence",
         "inspect the parser errors for the affected files"),
    "unresolved_over_budget":
        ("more unresolved symbols than the budget allows",
         "improve provider coverage or raise the budget deliberately"),
    "dynamic_dispatch_unresolved":
        ("dynamic dispatch (reflection/overriding) could not be resolved "
         "statically", "enumerate dynamic call sites manually for the "
         "affected symbols"),
    "coverage_below_floor":
        ("measured coverage is below the assurance floor",
         "measure coverage for the scope and close the reported gaps"),
    "enumeration_incomplete":
        ("the scope universe was not fully enumerated",
         "re-run after the enumeration completes; absence claims need a "
         "complete universe"),
    "parser_capability_incomplete":
        ("the parser could not handle all constructs in the universe",
         "extend parser capability or exclude the constructs explicitly"),
    "partial_ast_ceiling":
        ("partial-AST files cap the claim below absence assurance",
         "re-parse the partial files so the AST is complete"),
    "provider_capability_missing":
        ("a required evidence provider capability is missing",
         "install/enable the provider (see `sotgraph providers doctor`)"),
}


def _explain_reason(code: str) -> Tuple[str, str]:
    if code in _REASON_EXPLANATIONS:
        return _REASON_EXPLANATIONS[code]
    if code.startswith("collection_truncated:"):
        source = code.split(":", 1)[1]
        return (f"bounded collection '{source}' hit its cap; the cut is "
                "recorded in collection_stats",
                "raise the cap deliberately or accept the bounded view")
    return ("no explanation recorded for this code", "")


# --------------------------------------------------------------------------
# Small render helpers
# --------------------------------------------------------------------------
def _fmt(value: Any) -> str:
    if isinstance(value, str):
        return value
    text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    if len(text) > _MAX_VALUE_CHARS:
        text = text[: _MAX_VALUE_CHARS - 3] + "..."
    return text


def _short(value: Any, keep: int = 12) -> str:
    text = str(value or "")
    return text[:keep] if text else "?"


def _section(lines: List[str], title: str) -> None:
    lines.append("")
    lines.append(f"-- {title} " + "-" * max(0, 62 - len(title)))


def _kv(lines: List[str], key: str, value: Any, *,
        none_means: str = "none recorded") -> None:
    """Render one key with explicit missing-vs-empty semantics.

    ``KEY_ABSENT`` (sentinel) means the receipt lacks the field: render
    NOT_RECORDED, never an absent-trust "none". Legitimate falsy values
    (e.g. a 0 count) still render as-is.
    """
    if value is KEY_ABSENT:
        lines.append(f"  {key}: {NOT_RECORDED}")
    elif value is None or value == [] or value == {}:
        lines.append(f"  {key}: {none_means}")
    else:
        lines.append(f"  {key}: {_fmt(value)}")


class _K:
    """Sentinel distinguishing "field missing" from "field is None/empty"."""
    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "KEY_ABSENT"


KEY_ABSENT = _K()


def _pick(block: Any, *keys: str) -> Any:
    """First present key in ``block``; KEY_ABSENT when block/key missing."""
    if not isinstance(block, dict):
        return KEY_ABSENT
    for key in keys:
        if key in block:
            return block[key]
    return KEY_ABSENT


def _count_list(block: Any, key: str) -> Tuple[Any, Any]:
    """(count, items) for a list field; (KEY_ABSENT, KEY_ABSENT) if absent."""
    if not isinstance(block, dict) or key not in block:
        return KEY_ABSENT, KEY_ABSENT
    value = block[key]
    if isinstance(value, list):
        return len(value), value
    return _fmt(value), KEY_ABSENT


def _render_status(lines: List[str], receipt: Dict[str, Any]) -> None:
    _section(lines, "Q1 CLAIM — what SOT is claiming")
    assurance = receipt.get("assurance")
    status = _pick(assurance, "status")
    if status is KEY_ABSENT:
        lines.append(f"  status: {NOT_RECORDED}")
    else:
        lines.append(f"  status: {_fmt(status)}")
    profile = _pick(receipt.get("assurance_facts"), "claim_profile")
    _kv(lines, "claim profile", profile)
    _kv(lines, "reason codes", _pick(assurance, "reason_codes"))
    identity = receipt.get("identity")
    id_status = _pick(identity, "status")
    if id_status is not KEY_ABSENT:
        target = _pick(identity, "selected") or {}
        sym = _pick(target, "symbol") if isinstance(target, dict) else KEY_ABSENT
        suffix = f" (symbol: {_fmt(sym)})" if sym not in (KEY_ABSENT, None) else ""
        lines.append(f"  identity: {_fmt(id_status)}{suffix}")
    else:
        lines.append(f"  identity: {NOT_RECORDED}")
    request = receipt.get("request")
    req_target = _pick(request, "target")
    if req_target is not KEY_ABSENT:
        lines.append(f"  request target: {_fmt(req_target)}")


def _render_scope(lines: List[str], receipt: Dict[str, Any]) -> None:
    _section(lines, "Q2 SCOPE — approved/bounded scope and its binding")
    lines.append(f"  proof scope: {_fmt(receipt.get('proof_scope'))}")
    request = receipt.get("request")
    if isinstance(request, dict):
        parts = [f"{k}={_fmt(request[k])}" for k in request]
        lines.append(f"  request: {' '.join(parts)}")
    else:
        lines.append(f"  request: {NOT_RECORDED}")
    snapshot = receipt.get("snapshot")
    if isinstance(snapshot, dict) and snapshot:
        lines.append(
            "  snapshot: commit=" + _short(snapshot.get("commit_sha"))
            + f" dirty={_fmt(snapshot.get('dirty'))}"
            + f" generation={_fmt(snapshot.get('generation'))}"
            + f" role={_fmt(snapshot.get('role'))}"
        )
        scope_digest = snapshot.get("scope_digest")
        if scope_digest:
            lines.append(f"  content binding: scope_digest={_short(scope_digest, 16)}…"
                         " (cited files hashed into the binding)")
        else:
            lines.append("  content binding: UNBOUND (no scope_digest — "
                         "see snapshot_unbound reason if present)")
        descriptor = snapshot.get("descriptor_digest")
        if descriptor:
            lines.append(f"  descriptor digest: {_short(descriptor, 16)}…")
    else:
        lines.append(f"  snapshot: {NOT_RECORDED}")
    count, _items = _count_list(receipt, "stale_files")
    _kv(lines, "stale files", count)
    coverage = receipt.get("coverage")
    if isinstance(coverage, dict) and coverage:
        note = coverage.get("note")
        if note:
            lines.append(f"  coverage: {_fmt(note)}")
        lines.append(f"  coverage basis: {_fmt(coverage.get('basis'))}")
    else:
        lines.append(f"  coverage: {NOT_RECORDED}")


def _render_outside_scope(lines: List[str], receipt: Dict[str, Any]) -> None:
    _section(lines, "Q3 OUTSIDE SCOPE — what the claim does NOT cover")
    body: List[str] = []
    stats = receipt.get("collection_stats")
    if isinstance(stats, dict) and stats:
        for source, entry in sorted(stats.items()):
            if not isinstance(entry, dict):
                continue
            flag = "TRUNCATED" if entry.get("truncated") else "complete"
            body.append(
                f"  collection '{source}': returned "
                f"{_fmt(entry.get('returned_count'))} of "
                f"{_fmt(entry.get('enumerated_count'))} "
                f"(cap {_fmt(entry.get('cap'))}) — {flag}"
            )
    for key in ("changed_files_truncated",):
        if key in receipt and receipt[key]:
            body.append(f"  changed files: truncated at "
                        f"{_fmt(receipt.get('changed_files_total'))} total")
    transitive = receipt.get("transitive_impact")
    if isinstance(transitive, dict) and transitive.get("truncated"):
        body.append("  transitive impact: TRUNCATED at depth "
                    f"{_fmt(transitive.get('depth'))}")
    universe = receipt.get("scope_universe")
    if isinstance(universe, dict) and universe:
        if universe.get("enumeration_complete") is not True:
            body.append(f"  scope universe: enumeration_complete="
                        f"{_fmt(universe.get('enumeration_complete'))} "
                        "parser_capability_complete="
                        f"{_fmt(universe.get('parser_capability_complete'))}"
                        " — constructs outside the parsed universe are "
                        "unexamined")
        unsupported = universe.get("unsupported_constructs")
        if unsupported:
            body.append(f"  unsupported constructs: {_fmt(unsupported)}")
    unreadable = _pick(receipt.get("snapshot"), "unreadable")
    if unreadable not in (KEY_ABSENT, None) and unreadable:
        body.append(f"  unreadable cited files: {_fmt(unreadable)}")
    quarantined = receipt.get("quarantined_files")
    if isinstance(quarantined, list) and quarantined:
        body.append(f"  quarantined files: {len(quarantined)}"
                    f" (e.g. {_fmt(quarantined[:3])})")
    if body:
        lines.extend(body)
    elif isinstance(stats, dict) and "collection_stats" in receipt:
        # The block exists but yielded nothing: say so explicitly rather
        # than implying an audited-complete scope.
        lines.append(f"  collection caps: block present but empty — "
                     f"cap accounting {NOT_RECORDED}")
    else:
        lines.append(f"  collection caps: {NOT_RECORDED}")


def _render_evidence(lines: List[str], receipt: Dict[str, Any]) -> None:
    _section(lines, "Q4 EVIDENCE — what the conclusion rests on")
    rendered = False
    for key, label in (
        ("direct_callers", "direct callers"),
        ("direct_callees", "direct callees"),
        ("affected_files", "affected files"),
        ("candidate_tests", "candidate tests"),
        ("stale_files", "stale files"),
        ("changed_files", "changed files"),
        ("direct_nodes", "direct nodes"),
        ("caller_impacts", "caller impacts"),
        ("api_impacts", "api impacts"),
        ("test_impacts", "test impacts"),
        ("invalidated_evidence", "invalidated evidence entries"),
        ("remaining_gaps", "remaining gaps"),
    ):
        count, items = _count_list(receipt, key)
        if count is KEY_ABSENT:
            continue
        rendered = True
        line = f"  {label}: {count}"
        if isinstance(items, list) and items:
            line += f" (e.g. {_fmt(items[:3])})"
        lines.append(line)
    transitive = receipt.get("transitive_impact")
    if isinstance(transitive, dict) and transitive:
        rendered = True
        nodes = transitive.get("nodes")
        lines.append(
            f"  transitive impact: {len(nodes) if isinstance(nodes, list) else '?'}"
            f" nodes at depth {_fmt(transitive.get('depth'))}"
            f" (truncated={_fmt(transitive.get('truncated'))})"
        )
    anchors = receipt.get("source_anchors")
    if isinstance(anchors, list) and anchors:
        rendered = True
        lines.append(f"  source anchors: {_fmt(anchors)}")
    providers = receipt.get("providers")
    if isinstance(providers, dict) and providers:
        rendered = True
        counts = providers.get("provider_counts")
        if counts:
            lines.append(f"  provider evidence counts: {_fmt(counts)}")
        for key in ("unresolved_count", "open_conflicts"):
            if key in providers:
                lines.append(f"  {key}: {_fmt(providers[key])}")
    else:
        lines.append(f"  providers ledger: {NOT_RECORDED}")
    basis = receipt.get("evidence_basis")
    if isinstance(basis, dict) and basis:
        rendered = True
        for key in sorted(basis):
            lines.append(f"  {key}: {_fmt(basis[key])}")
    summary = receipt.get("summary")
    if isinstance(summary, dict) and summary:
        rendered = True
        for key in sorted(summary):
            lines.append(f"  summary.{key}: {_fmt(summary[key])}")
    if not rendered:
        lines.append(f"  evidence: {NOT_RECORDED}")


def _render_downgrade(lines: List[str], receipt: Dict[str, Any]) -> None:
    _section(lines, "Q5 DOWNGRADE — why the status is not fully assured")
    assurance = receipt.get("assurance")
    status = _pick(assurance, "status")
    codes = _pick(assurance, "reason_codes")
    if status is KEY_ABSENT:
        lines.append(f"  status: {NOT_RECORDED}")
    elif status == "ASSURED_WITHIN_SCOPE":
        lines.append("  status is ASSURED_WITHIN_SCOPE: no downgrade "
                     "recorded in this receipt")
    elif not isinstance(codes, list) or not codes:
        lines.append("  status is downgraded but no reason codes are "
                     f"recorded in this receipt (status: {_fmt(status)})")
    else:
        for code in codes:
            meaning, _fix = _explain_reason(str(code))
            lines.append(f"  {code} — {meaning}")
    # Explicit missing-vs-empty semantics: a missing field must never
    # read as "no errors happened".
    _kv(lines, "collection errors", receipt.get("collection_errors", KEY_ABSENT))
    _kv(lines, "warnings", receipt.get("warnings", KEY_ABSENT))
    gate = _pick(assurance, "rename_gate")
    if isinstance(gate, dict) and gate.get("blocked"):
        lines.append(f"  rename gate BLOCKED: {_fmt(gate.get('reason'))}")


def _render_remediation(lines: List[str], receipt: Dict[str, Any]) -> None:
    _section(lines, "Q6 REMEDIATION — how to raise the status")
    found = False
    assurance = receipt.get("assurance")
    codes = _pick(assurance, "reason_codes")
    if isinstance(codes, list) and codes:
        for code in codes:
            _meaning, fix = _explain_reason(str(code))
            if fix:
                found = True
                lines.append(f"  for {code}: {fix}")
    omp = _pick(assurance, "omp_confirmations")
    if isinstance(omp, list) and omp:
        found = True
        lines.append("  OMP confirmations owed:")
        for item in omp:
            lines.append(f"    [ ] {_fmt(item)}")
    remaining_omp = receipt.get("omp_confirmations_remaining")
    if isinstance(remaining_omp, list) and remaining_omp:
        found = True
        lines.append("  OMP confirmations still open:")
        for item in remaining_omp:
            lines.append(f"    [ ] {_fmt(item)}")
    reconcile = receipt.get("reconcile")
    if isinstance(reconcile, dict) and reconcile:
        found = True
        note = reconcile.get("note")
        lines.append(f"  reconcile: {_fmt(note or 'required')}")
    gaps = receipt.get("remaining_gaps")
    if isinstance(gaps, list) and gaps:
        found = True
        lines.append(f"  remaining gaps: {_fmt(gaps)}")
    closure = receipt.get("closure_decision")
    if isinstance(closure, dict) and closure:
        found = True
        lines.append(f"  closure decision: {_fmt(closure)}")
    if not found:
        lines.append(f"  {NOT_RECORDED}")


def render_receipt(receipt: Dict[str, Any]) -> str:
    """Render ONE parsed receipt as a terminal string (pure function).

    Raises :class:`UnsupportedReceiptVersion` for missing/unknown schema
    versions. Organized around the P1-6 operator questions; every
    question the receipt cannot answer prints an explicit
    ``not recorded in this receipt`` line.
    """
    gate = gate_receipt_version(receipt)
    lines: List[str] = []
    kind = receipt.get("kind") or "unknown-kind"
    digest = receipt.get("digest")
    digest_text = (_short(digest, 16) + "…") if digest else NOT_RECORDED
    lines.append(f"RECEIPT {kind} — schema {gate.version}, "
                 f"digest {digest_text}")
    if gate.state == "legacy":
        lines.append(f"[!] {gate.banner}")
    _render_status(lines, receipt)
    _render_scope(lines, receipt)
    _render_outside_scope(lines, receipt)
    _render_evidence(lines, receipt)
    _render_downgrade(lines, receipt)
    _render_remediation(lines, receipt)
    lines.append("")
    lines.append("(read-only view of the serialized receipt; nothing was "
                 "recomputed or reconciled)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Diff (P1-6 question 7)
# --------------------------------------------------------------------------
#: Keys compared only as informational header lines, never as leaf diffs
#: (stored receipts carry no ``digest`` at all — ``ReceiptStore`` strips
#: it — so diffing stored vs in-memory copies would produce a false one).
_HEADER_KEYS = ("digest",)


def _scalar_diff(path: str, old: Any, new: Any,
                 out: Dict[str, Tuple[Any, Any]]) -> None:
    out[path] = (old, new)


def _walk_diff(old: Any, new: Any, path: str,
               changed: Dict[str, Tuple[Any, Any]],
               added: Dict[str, Any],
               removed: Dict[str, Any]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            sub = f"{path}.{key}" if path else key
            if key not in new:
                removed[sub] = old[key]
            elif key not in old:
                added[sub] = new[key]
            else:
                _walk_diff(old[key], new[key], sub, changed, added, removed)
        return
    if isinstance(old, list) and isinstance(new, list):
        if old == new:
            return
        old_scalars = all(not isinstance(v, (dict, list)) for v in old)
        new_scalars = all(not isinstance(v, (dict, list)) for v in new)
        if old_scalars and new_scalars:
            # Multiset diff so pure reorders and duplicates stay honest
            # without drowning the view in whole-list replacements.
            remaining = list(new)
            kept = []
            for item in old:
                if item in remaining:
                    remaining.remove(item)
                else:
                    kept.append(item)
            if not remaining and not kept:
                return  # reorder only
            _scalar_diff(path, f"- {_fmt(kept) if kept else '∅'}",
                         f"+ {_fmt(remaining) if remaining else '∅'}", changed)
            return
        _scalar_diff(path, f"{len(old)} items", f"{len(new)} items", changed)
        return
    if old != new:
        _scalar_diff(path, old, new, changed)


def diff_receipts(old: Dict[str, Any], new: Dict[str, Any]) -> str:
    """Render a field-level diff of TWO parsed receipts (pure function).

    Volatile wall-clock fields (the canonical ``_strip_volatile`` set) are
    ignored so two receipts of one unchanged state show no differences.
    Raises :class:`UnsupportedReceiptVersion` if either side has an
    unknown schema version.
    """
    old_gate = gate_receipt_version(old)
    new_gate = gate_receipt_version(new)
    old_clean = _strip_volatile(
        {k: v for k, v in old.items() if k not in _HEADER_KEYS})
    new_clean = _strip_volatile(
        {k: v for k, v in new.items() if k not in _HEADER_KEYS})
    changed: Dict[str, Tuple[Any, Any]] = {}
    added: Dict[str, Any] = {}
    removed: Dict[str, Any] = {}
    _walk_diff(old_clean, new_clean, "", changed, added, removed)

    def _head(receipt: Dict[str, Any], gate: VersionGate) -> str:
        digest = receipt.get("digest")
        digest_text = (_short(digest, 12) + "…") if digest else "(no digest — stored form)"
        return f"schema {gate.version}, digest {digest_text}"

    lines = [f"RECEIPT DIFF old ({_head(old, old_gate)})"
             f" → new ({_head(new, new_gate)})"]
    if old_gate.version != new_gate.version:
        lines.append(f"[!] schema versions differ ({old_gate.version} vs "
                     f"{new_gate.version}): some changes may be schema "
                     "artifacts rather than state changes")
    if not (changed or added or removed):
        lines.append("no differences (volatile fields ignored)")
        return "\n".join(lines)
    for path, (old_value, new_value) in sorted(changed.items()):
        lines.append(f"  changed   {path}: {_fmt(old_value)} → {_fmt(new_value)}")
    for path, value in sorted(added.items()):
        lines.append(f"  added     {path}: {_fmt(value)}")
    for path, value in sorted(removed.items()):
        lines.append(f"  removed   {path}: {_fmt(value)}")
    total = len(changed) + len(added) + len(removed)
    lines.append(f"{total} difference(s)")
    return "\n".join(lines)
