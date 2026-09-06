"""Federated provider orchestration (P2).

Moved — not copied — from private CLI helpers so CLI and MCP drive ONE
engine: plan negotiation, capability routing, typed provider outcomes,
candidate normalization, target-conflict adjudication, and the shared
federation result contract.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from .routing import (
    COMMAND_CAPABILITY,
    QUERYABLE_PROVIDERS,
    effective_provider_spec,
    parse_provider_spec,
    supports_capability,
)

__all__ = [
    "federation_plan",
    "managed_read_dispatch",
    "run_federated_query",
    "federated_extras",
    "cbm_candidates_from_outcome",
    "target_conflicts",
    "envelope_fed_kwargs",
    "architecture",
    "search_rows_from_payload",
    "trace_edges_from_payload",
]


def managed_read_dispatch(
    root: str, command_kind: str, symbol: str, *,
    provider_policy: str = "builtin_only", limit: int = 20,
    scope: str = "", builtin_target=None,
) -> dict:
    """Data-only persisted-admin read path, separate from explicit legacy CLI.

    Search is currently the only managed evidence operation. Usages is an
    accepted surface operation but abstains until the runtime allowlists it.
    No discovery, preparation, indexing, database construction or ledger I/O.
    Native diagnostics are never copied into public remediation. The returned
    candidates are supplemental evidence, not replacements for builtin hits.
    """
    result: dict = {
        "policy": provider_policy, "operation": command_kind,
        "status": "builtin_only", "reason": None, "warnings": [],
        "fail_message": None, "candidates": [], "conflicts": [],
        "providers_extra": [], "coverage": {}, "known_gaps": [],
        "truncated": False,
    }

    def refuse(reason: str, *, invalid: bool = False) -> dict:
        message = (
            f"Managed external read unavailable ({reason}). "
            "Ask a trusted administrator to inspect provider status and configuration."
        )
        required = invalid or provider_policy == "require_external"
        fallback_message = "builtin served by fallback when the builtin query succeeds: "
        if reason == "managed_not_configured":
            fallback_message += (
                "no external provider is wired into this managed request because "
                "managed opt-in is absent or disabled. "
            )
        fallback_message += message
        result.update(status="error" if required else "fallback", reason=reason,
                      fail_message=message if required else None,
                      warnings=[] if required else [fallback_message], known_gaps=[message])
        return result

    if provider_policy not in ("builtin_only", "prefer_external", "require_external"):
        return refuse("invalid_policy", invalid=True)
    # Strong isolation: even policy/config validation and imports below are
    # bypassed for builtin reads. Repository defaults cannot enable execution.
    if provider_policy == "builtin_only":
        return result
    if command_kind != "search":
        return refuse("unsupported_operation")
    if (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
            or not isinstance(scope, str) or not isinstance(symbol, str)
            or not symbol.strip() or "\x00" in symbol or len(symbol) > 1000):
        return refuse("invalid_request", invalid=True)
    limit = min(limit, 20)  # managed search wire is deliberately fixed at 20
    try:
        root = os.path.realpath(root)
        scope_path = os.path.realpath(os.path.join(root, scope))
        if os.path.commonpath((root, scope_path)) != root:
            return refuse("invalid_scope", invalid=True)
    except (TypeError, ValueError, OSError):
        return refuse("invalid_scope", invalid=True)

    try:
        import stat

        from sot_graph.config import _FALSY, _TRUTHY, _coerce_bool, tomllib
        from sot_graph.providers.trusted_config import load_managed_installation

        # Read untrusted repository policy once, with a hard size bound and
        # no symlink/FIFO traversal. Directory-relative open pins .sot against
        # replacement between checking its type and opening config.toml.
        document: dict = {}
        try:
            directory = os.open(os.path.join(root, ".sot"),
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            directory = None
        if directory is not None:
            try:
                try:
                    fd = os.open("config.toml", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
                except FileNotFoundError:
                    fd = None
                if fd is not None:
                    with os.fdopen(fd, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_size > 262144:
                            return refuse("repository_config_invalid")
                        raw = stream.read(262145)
                        if len(raw) > 262144:
                            return refuse("repository_config_invalid")
                    document = tomllib.loads(raw.decode("utf-8"))
            finally:
                os.close(directory)
        # Default false is not a deny. Only explicit restriction fields are
        # authoritative; executable, registry and grants are never consumed.
        providers = document.get("providers", {})
        if not isinstance(providers, dict):
            return refuse("repository_config_invalid")
        repo_provider = providers.get("codebase-memory", {})
        if not isinstance(repo_provider, dict):
            return refuse("repository_config_invalid")
        denied = False
        for policy, key in ((document, "allow_external"), (repo_provider, "enabled")):
            if key in policy:
                denied |= not _coerce_bool("repository policy", key, policy[key])
        env_allow = os.environ.get("SOT_PROVIDERS_ALLOW_EXTERNAL")
        if env_allow is not None:
            normalized = env_allow.strip().lower()
            if normalized not in _TRUTHY | _FALSY:
                return refuse("repository_config_invalid")
            denied |= normalized in _FALSY
        if denied:
            return refuse("repository_denied")
    except Exception:
        return refuse("repository_config_invalid")
    try:
        installation = load_managed_installation(root)
    except Exception:
        return refuse("trusted_config_invalid")
    if installation is None:
        return refuse("managed_not_configured")

    try:
        # Use the installation's adapter directly: it owns the exact registry,
        # runtime locks, binding validation and managed-only invocation path.
        # Do not probe or construct a second adapter/lineage trust path here.
        from sot_graph.providers.base import SymbolRequest

        # Managed capabilities use wire names (search_graph), not the generic
        # legacy routing name search_symbols. This typed method maps exactly
        # to the allowed wire operation and retains every adapter/runtime gate.
        outcome = installation.provider.search_symbols(SymbolRequest(
            repo_root=root, query=symbol, limit=20, timeout_seconds=30.0,
        ))
        method = "search_symbols"
        if outcome is None or not outcome.ok:
            return refuse("managed_query_failed")
    except Exception:
        return refuse("managed_query_failed")

    try:
        candidates, truncated, gap = cbm_candidates_from_outcome(
            outcome, method, "codebase-memory", repo_root=root,
        )
        if gap:
            return refuse("invalid_provider_payload")
        scoped = []
        for candidate in candidates:
            path = candidate.get("subject", {}).get("path")
            if not isinstance(path, str) or not path:
                continue
            candidate_path = os.path.realpath(os.path.join(root, path))
            if os.path.commonpath((root, candidate_path)) != root:
                continue
            if os.path.commonpath((scope_path, candidate_path)) != scope_path:
                continue
            scoped.append(candidate)
        bounded = scoped[:limit]
        conflicts = target_conflicts(builtin_target, bounded, repo_root=root)
        # Materialize plain JSON values; a malformed native value fails closed
        # instead of escaping via repr/exception diagnostics in an adapter.
        import json

        result.update(
            status="ok", candidates=bounded, conflicts=conflicts,
            providers_extra=[{"name": "codebase-memory", "role": "candidate-evidence"}],
            coverage={"codebase-memory": {
                "queried": True, "method": method, "scope": scope,
                "limit": limit, "scope_completeness": "bounded",
            }},
            known_gaps=[
                "Managed search is bounded to one 20-row native page; scope filtering is local.",
                "External candidates retain source, snapshot and exact-compatibility trust ceilings.",
            ],
            truncated=bool(truncated or len(scoped) > limit),
        )
        return json.loads(json.dumps(result, allow_nan=False))
    except Exception:
        # Also drop any partially assembled evidence on normalization failure.
        result.update(candidates=[], conflicts=[], providers_extra=[], coverage={}, truncated=False)
        return refuse("invalid_provider_payload")


def federation_plan(provider_spec: Optional[str], root: str, command_kind: str, db=None) -> dict:
    """Resolve one provider spec into an executable plan.

    builtin/absent never spawns anything; every other mode is gated behind
    ``allow_external`` and probing. ``require:<name>`` fails closed (returns
    ``fail_message``) when blocked or unhealthy; the other modes degrade to
    an honest builtin-only fallback with a warning.
    """
    from sot_graph.config import load_config
    from sot_graph.providers.codebase_memory import CodebaseMemoryProvider
    from sot_graph.providers.scip import ScipProvider
    from sot_graph.providers_registry import resolve_capability
    try:
        mode, name = parse_provider_spec(provider_spec)
    except ValueError as exc:
        return {"mode": "invalid", "name": None, "warnings": [],
                "fail_message": str(exc), "provider": None, "status": None}
    plan: dict = {"mode": mode, "name": name, "warnings": [],
                  "fail_message": None, "provider": None, "status": None,
                  "providers": [], "statuses": []}
    if mode == "builtin":
        return plan

    cfg = load_config(root)
    if mode in ("prefer", "require"):
        if not cfg.allow_external and name != "scip":
            msg = "external providers disabled (allow_external=false)"
            if mode == "require":
                plan["fail_message"] = f"{msg}: require:{name} fails closed"
            else:
                plan["warnings"].append(f"{msg}; using sot-builtin only")
            return plan
        names = [name]
    else:  # auto | all: registry-ranked external providers for this command
        ranked = [
            st.name for st in resolve_capability(root, COMMAND_CAPABILITY[command_kind], cfg)
            if st.name != "sot-builtin"
        ]
        names = [n for n in ranked if n in QUERYABLE_PROVIDERS]
        if mode == "auto":
            names = names[:1]
    if not names:
        if not cfg.allow_external:
            plan["warnings"].append(
                "external providers disabled (allow_external=false); using sot-builtin only"
            )
        else:
            plan["warnings"].append(
                f"no queryable external provider for '{command_kind}'; using sot-builtin only"
            )
        return plan

    # Probe EVERY ranked queryable provider ('all' keeps the full ranked
    # list; 'auto' still truncates to the best one). Healthy providers stay
    # in plan["providers"]; unhealthy ones only warn (require fails closed).
    # NOTE(adapter-factory): CodebaseMemoryProvider is the only wired
    # adapter; a provider->adapter factory replaces this hardcode while
    # routing keeps flowing through QUERYABLE_PROVIDERS + registry
    # resolution.
    statuses: list = []
    first_healthy = None
    for target in names:
        assert target is not None
        pcfg = cfg.providers.get(target)
        if target not in QUERYABLE_PROVIDERS:
            msg = f"provider '{target}' is not queryable through an adapter"
            if mode == "require":
                plan["fail_message"] = msg
            else:
                plan["warnings"].append(f"{msg}; using sot-builtin only")
            continue
        if pcfg is not None and pcfg.enabled is False:
            msg = f"provider '{target}' is disabled in configuration"
            if mode == "require":
                plan["fail_message"] = msg
            else:
                plan["warnings"].append(f"{msg}; using sot-builtin only")
            continue
        if target == "scip":
            provider = ScipProvider(db=db)
        else:
            provider = CodebaseMemoryProvider(config=pcfg, db=db)
        st = provider.probe(root)
        statuses.append({
            "name": target, "installed": st.installed, "healthy": st.healthy,
            "version": st.version, "detail": st.detail,
        })
        if not (st.installed and st.healthy):
            msg = f"provider '{target}' unavailable ({st.detail})"
            if mode == "require":
                plan["fail_message"] = f"{msg}: failing closed"
            else:
                plan["warnings"].append(f"{msg}; using sot-builtin only")
            continue
        req_cap = COMMAND_CAPABILITY.get(command_kind)
        if mode == "require" and req_cap and not supports_capability(provider, req_cap):
            msg = f"provider '{target}' does not support required capability '{req_cap}'"
            plan["fail_message"] = f"{msg}: failing closed"
            continue
        plan["providers"].append(provider)
        if first_healthy is None:
            first_healthy = provider
    plan["statuses"] = statuses
    if plan["fail_message"]:
        return plan
    plan["status"] = statuses[0] if statuses else None
    plan["provider"] = first_healthy
    return plan


def run_federated_query(
    plan: dict, root: str, command_kind: str, symbol: str,
    *, staged: bool = False, working_tree: bool = False, depth: int = 2,
):
    """Invoke the negotiated provider method; returns ``(outcome, method)``."""
    from sot_graph.providers.base import ImpactRequest, SymbolRequest, TraceRequest

    provider = plan.get("provider")
    if provider is None:
        return None, None

    if command_kind == "diff-impact":
        method = "impact" if (supports_capability(provider, "impact") and callable(getattr(provider, "impact", None))) else None
    elif command_kind == "usages":
        if supports_capability(provider, "usages") and callable(getattr(provider, "usages", None)):
            method = "usages"
        elif supports_capability(provider, "callgraph") and callable(getattr(provider, "trace", None)):
            method = "trace"
        elif supports_capability(provider, "trace") and callable(getattr(provider, "trace", None)):
            method = "trace"
        else:
            method = None
    elif command_kind in ("trace", "explore"):
        if supports_capability(provider, "trace") and callable(getattr(provider, "trace", None)):
            method = "trace"
        elif supports_capability(provider, "callgraph") and callable(getattr(provider, "trace", None)):
            method = "trace"
        else:
            method = None
    elif command_kind in ("search", "symbols"):
        if supports_capability(provider, "search_symbols") and callable(getattr(provider, "search_symbols", None)):
            method = "search_symbols"
        else:
            method = None
    elif supports_capability(provider, "search_symbols") and callable(getattr(provider, "search_symbols", None)):
        method = "search_symbols"
    else:
        method = None
    if method is None:
        return None, None

    outcome: Any = None
    if method == "impact":
        # P3.1: the wire tool diffs git refs; ``symbol`` carries the SOT
        # diff target (e.g. HEAD~1) and staged/working-tree scopes surface
        # as an adapter-side scope conflict, never a merged guess.
        outcome = provider.impact(ImpactRequest(
            repo_root=root, path=root, since=symbol,
            depth=depth, staged=staged, working_tree=working_tree,
        ))
    elif method == "usages":
        outcome = provider.usages(SymbolRequest(repo_root=root, query=symbol))
    elif method == "trace":
        outcome = provider.trace(TraceRequest(repo_root=root, symbol=symbol))
    elif method == "search_symbols":
        outcome = provider.search_symbols(
            SymbolRequest(repo_root=root, query=symbol)
        )
    return outcome, method

def _span_from_lines(value) -> Optional[tuple[int, int]]:
    """Wire ``lines`` cell (``"38-54"``) -> ``(start, end)``; None on drift."""
    if not isinstance(value, str):
        return None
    start_s, sep, end_s = value.partition("-")
    if not (start_s.isdigit() and (not sep or end_s.isdigit())):
        return None
    return int(start_s), int(end_s) if sep else int(start_s)


def search_rows_from_payload(payload: Mapping) -> tuple:
    """Structured ``search_graph`` rows: ``(rows, has_more, drift)``.

    Columns are addressed by NAME (``cols``), never by position, and rows
    missing the ``qn`` or ``file`` column are skipped — never guessed. A
    malformed ``cols``/``rows`` shape reports ``drift=True`` so callers
    abstain instead of guessing.
    """
    cols = payload.get("cols")
    rows = payload.get("rows")
    if not isinstance(cols, list) or not isinstance(rows, list):
        return [], bool(payload.get("has_more")), True
    try:
        idx = {name: i for i, name in enumerate(cols)}
    except TypeError:
        return [], True, True
    if "qn" not in idx or "file" not in idx:
        return [], True, True
    out: list = []
    for row in rows:
        if not isinstance(row, list) or len(row) < len(cols):
            continue
        span = _span_from_lines(row[idx["lines"]]) if "lines" in idx else None
        out.append({
            "qualified_name": row[idx["qn"]],
            "kind": row[idx["label"]] if "label" in idx else None,
            "path": row[idx["file"]],
            "start_line": span[0] if span else None,
            "end_line": span[1] if span else None,
            "rank": row[idx["rank"]] if "rank" in idx else None,
        })
    return out, bool(payload.get("has_more")), False


def trace_edges_from_payload(payload: Mapping) -> list:
    """Structured ``trace_path`` edges: directed rows with evidence metadata.

    Every row keeps its side (``callees`` = root -> callee, ``callers`` =
    caller -> root), hop, and the resolver evidence columns when present.
    Edge type separation (CALLS vs CALL_REFERENCE vs USAGE) travels through
    the ``edge_type`` column when the wire provides it.
    """
    edges: list = []
    root_name = payload.get("function")
    for side in ("callees", "callers"):
        section = payload.get(side)
        if not isinstance(section, Mapping):
            continue
        cols = section.get("cols")
        if not isinstance(cols, list) or "name" not in cols:
            continue
        idx = {name: i for i, name in enumerate(cols)}
        groups = section.get("groups")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            prefix = str(group.get("qn_prefix") or "")
            for row in group.get("rows") or []:
                if not isinstance(row, list) or len(row) < len(cols):
                    continue
                edge = {
                    "direction": side,
                    "qualified_name": f"{prefix}.{row[idx['name']]}" if prefix else str(row[idx["name"]]),
                    "hop": row[idx["hop"]] if "hop" in idx else None,
                    "edge_type": row[idx["edge_type"]] if "edge_type" in idx else None,
                    "strategy": row[idx["strategy"]] if "strategy" in idx else None,
                    "confidence": row[idx["confidence"]] if "confidence" in idx else None,
                }
                edge["root"] = root_name
                edges.append(edge)
    return edges


def _candidate_entry(assertion, provider_name: str) -> dict:
    subj = assertion.subject
    resolution = getattr(assertion.resolution, "value", assertion.resolution)
    return {
        "provider": provider_name,
        "relation": assertion.relation,
        "verdict": assertion.verdict,
        "resolution": str(resolution),
        "subject": {
            "qualified_name": getattr(subj, "qualified_name", None),
            "kind": getattr(subj, "kind", None),
            "path": getattr(subj, "path", None),
            "start_line": getattr(subj, "start_line", None),
            "end_line": getattr(subj, "end_line", None),
        },
        "targets": list(assertion.targets),
        "problems": list(assertion.problems),
    }


def snapshot_match_of(outcome):
    """Read the snapshot-binding report off a provider outcome, tolerantly.

    Preferred shape: duck-typed ``outcome.snapshot_match`` with
    ``{bound, fresh, detail}``. An adapter may instead travel the verdict in
    ``metadata`` (``freshness`` FRESH/STALE/UNKNOWN/UNBOUND +
    ``snapshot_bound``); derive the same shape from it so a bound+fresh
    adapter outcome is never silently capped at UNVERIFIABLE. Returns
    ``None`` when neither shape is present (treated as unbound).
    """
    match = getattr(outcome, "snapshot_match", None)
    if match is not None:
        return match
    metadata = getattr(outcome, "metadata", None) or {}
    if not isinstance(metadata, Mapping):
        return None
    if "freshness" not in metadata and "snapshot_bound" not in metadata:
        return None
    freshness = str(metadata.get("freshness") or "")
    return {
        "bound": bool(metadata.get("snapshot_bound")),
        "fresh": freshness == "FRESH",
        "detail": f"adapter freshness marker: {freshness or 'absent'}",
    }


def cbm_candidates_from_outcome(outcome, method: str, provider_name: str,
                                repo_root: Optional[str] = None):
    """Normalize a provider QueryOutcome into candidate entries.

    Returns ``(candidates, truncated, gap_note)``. When the outcome carries
    a snapshot binding report (see :func:`snapshot_match_of`) and
    ``repo_root`` is given, each candidate's subject span is re-verified
    against current source via :func:`verify_subject`; only VERIFIED +
    bound+fresh candidates may reach SUPPORTED. Candidates gain ``verified``
    and ``detail`` fields describing the on-disk verification result.
    """
    from sot_graph.providers.normalization import (
        VERSION_COMPATIBLE,
        normalize_assertion,
        trust_ceiling,
    )
    from sot_graph.providers.verification import verify_subject

    snapshot_match = snapshot_match_of(outcome)
    version_compatibility = (
        (outcome.metadata or {}).get("version_compatibility")
        or VERSION_COMPATIBLE
    )

    def _finish(assertion):
        cand = _candidate_entry(assertion, provider_name)
        if repo_root is None:
            return cand
        subject = assertion.subject
        verification = (
            verify_subject(subject, repo_root)
            if getattr(subject, "path", None)
            else None
        )
        has_span = getattr(subject, "start_line", None) is not None
        verdict, resolution = trust_ceiling(
            snapshot_bound=(
                bool(snapshot_match.get("bound"))
                if isinstance(snapshot_match, Mapping)
                else bool(getattr(snapshot_match, "bound", False))
            ),
            has_span=has_span,
            unique_target=len(assertion.targets) == 1,
            verification=verification,
            snapshot_match=snapshot_match,
            version_compatibility=version_compatibility,
        )
        cand["verdict"] = verdict
        cand["resolution"] = str(getattr(resolution, "value", resolution))
        cand["verified"] = (
            getattr(verification, "status", None) if verification else None
        )
        cand["detail"] = getattr(verification, "detail", "") if verification else ""
        return cand

    candidates: list = []
    truncated = bool((outcome.metadata or {}).get("wire_status") == "truncated")
    payload = outcome.payload

    if not isinstance(payload, Mapping):
        # P3.1 exit gate: no production evidence parser reads whitespace
        # text reports. A non-structured payload is drift, not a guess.
        return candidates, truncated, (
            f"{provider_name} payload is not structured JSON; abstaining "
            "(text-report parsing was removed in P3.1)"
        )

    if method == "impact":
        # detect_changes carries no mappable relation; record each impacted
        # path as an explicitly UNMAPPED advisory candidate. diff_identity
        # rides in metadata so builtin and CBM sides of one comparison are
        # pinned to the same diff before anyone merges them.
        impacted = payload.get("impacted")
        impacted = impacted if isinstance(impacted, list) else []
        for entry in impacted:
            path = entry.get("path") if isinstance(entry, dict) else entry
            if not isinstance(path, str):
                continue
            assertion = normalize_assertion(
                raw_subject={"path": path},
                provider_relation="detect_changes",
                targets=(path,),
                snapshot_bound=False,
                version_compatibility=version_compatibility,
            )
            candidates.append(_finish(assertion))
        return candidates, truncated or bool(payload.get("truncated")), None

    if method == "trace":
        for edge in trace_edges_from_payload(payload):
            # Directed evidence: callees are root -> callee, callers are
            # caller -> root. The subject is always the far side and the
            # target is the root symbol; direction/hop/strategy/confidence
            # travel on the candidate without invention (missing -> None).
            assertion = normalize_assertion(
                raw_subject={"qualified_name": edge["qualified_name"], "kind": "unknown"},
                provider_relation="call",
                targets=(str(edge["root"]),),
                snapshot_bound=False,
                version_compatibility=version_compatibility,
            )
            cand = _finish(assertion)
            cand["direction"] = edge["direction"]
            cand["hop"] = edge["hop"]
            cand["edge_type"] = edge["edge_type"]
            cand["strategy"] = edge["strategy"]
            cand["confidence"] = edge["confidence"]
            candidates.append(cand)
        return candidates, truncated or bool(payload.get("has_more")), None

    if "symbols" in payload and isinstance(payload["symbols"], list):
        for sym in payload["symbols"]:
            if not isinstance(sym, dict):
                continue
            raw = {
                "qualified_name": sym.get("qualified_name") or sym.get("name") or "",
                "kind": sym.get("kind", "symbol"),
                "path": sym.get("path"),
            }
            if sym.get("span"):
                raw["span"] = sym["span"]
            relation = sym.get("relation") or ("define" if sym.get("is_definition") else "references")
            assertion = normalize_assertion(
                raw_subject=raw,
                provider_relation=relation,
                targets=(raw["qualified_name"],),
                snapshot_bound=False,
                version_compatibility=version_compatibility,
            )
            cand = _finish(assertion)
            cand["provider_relation"] = relation
            candidates.append(cand)
        is_trunc = truncated or bool(payload.get("truncated") or payload.get("has_more"))
        return candidates, is_trunc, None
    rows, has_more, drift = search_rows_from_payload(payload)
    if drift:
        return candidates, True, (
            f"{provider_name} search payload missing valid cols/rows; abstaining"
        )
    for row in rows:
        raw = {
            "qualified_name": row["qualified_name"],
            "kind": row["kind"],
            "path": row["path"],
        }
        if row["start_line"] is not None:
            raw["span"] = {"start_line": row["start_line"], "end_line": row["end_line"]}
        assertion = normalize_assertion(
            raw_subject=raw,
            provider_relation="define",
            targets=(row["qualified_name"],),
            snapshot_bound=False,
            version_compatibility=version_compatibility,
        )
        cand = _finish(assertion)
        cand["rank"] = row["rank"]
        candidates.append(cand)
    return candidates, (truncated or has_more), None


def target_conflicts(builtin_target, candidates: list,
                     repo_root: Optional[str] = None) -> list:
    """Record builtin vs external target disagreements.

    ``builtin_target`` is ``(label, path, line)`` from the local graph, or
    None. A conflict is recorded when an external candidate claiming the
    same symbol name lands on a different file/span.

    When ``repo_root`` is given, both sides are checked against current
    source: if exactly ONE side's span verifies (status VERIFIED), that side
    becomes the recorded resolution (``resolution="source_verified"``) and
    the other is marked contradicted. The conflict is still listed — never
    silently dropped. Without a decisive verification the conflict stays
    ``recorded-not-resolved``.
    """
    from sot_graph.providers.verification import VERIFIED, verify_subject

    conflicts: list = []
    if not builtin_target:
        return conflicts
    label, bpath, bline = builtin_target
    for cand in candidates:
        subj = cand["subject"]
        qn = subj.get("qualified_name") or ""
        if label and qn.rsplit(".", 1)[-1] != label:
            continue
        cpath, cline = subj.get("path"), subj.get("start_line")
        if not cpath:
            continue
        differs = os.path.normpath(cpath) != os.path.normpath(bpath or "")
        span_differs = (
            not differs and bline is not None and cline is not None
            and int(cline) != int(bline)
        )
        if not (differs or span_differs):
            continue

        conflict = {
            "kind": "target_mismatch",
            "symbol": label,
            "builtin": {"path": bpath, "line": bline},
            "external": {
                "provider": cand["provider"],
                "qualified_name": qn, "path": cpath, "line": cline,
            },
            "policy": "recorded-not-resolved",
            "resolution": "recorded-not-resolved",
        }

        if repo_root:
            cbm_status = cand.get("verified")
            if cbm_status is None and subj.get("path"):
                cbm_status = verify_subject(subj, repo_root).status
            builtin_status = None
            if bpath:
                builtin_subject = {
                    "qualified_name": label, "kind": "unknown",
                    "path": bpath, "start_line": bline,
                }
                builtin_status = verify_subject(builtin_subject, repo_root).status

            external_side = dict(conflict["external"])
            builtin_side = dict(conflict["builtin"])
            if cbm_status == VERIFIED and builtin_status != VERIFIED:
                conflict["resolution"] = "source_verified"
                conflict["resolved"] = external_side | {"verified": cbm_status}
                conflict["contradicted"] = builtin_side | {"verified": builtin_status}
            elif builtin_status == VERIFIED and cbm_status != VERIFIED:
                conflict["resolution"] = "source_verified"
                conflict["resolved"] = builtin_side | {"verified": builtin_status}
                conflict["contradicted"] = external_side | {"verified": cbm_status}

        conflicts.append(conflict)
    return conflicts


def _diff_identity(root: str, target: str) -> Optional[str]:
    """Pin a diff to its commit pair: ``<base-sha>..<head-sha>``.

    Both builtin and CBM sides of one impact comparison must carry the same
    identity before anyone merges them; unresolvable refs yield None and the
    gap is declared rather than guessed.
    """
    import subprocess

    def _sha(ref: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", "-C", root, "rev-parse", "--verify", ref],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    base = _sha(target)
    head = _sha("HEAD")
    if base is None or head is None:
        return None
    return f"{base[:12]}..{head[:12]}"


def federated_extras(
    provider_spec: Optional[str],
    root: str,
    command_kind: str,
    symbol: str,
    builtin_target=None,
    *,
    staged: bool = False,
    working_tree: bool = False,
    depth: int = 2,
    db=None,
) -> Optional[dict]:
    """Run the optional external-provider evidence path for one command.

    Returns ``None`` for an absent/builtin spec so the caller proceeds
    completely untouched; otherwise a dict with warnings, fail_message,
    candidates, conflicts, providers_extra, coverage, known_gaps, truncated,
    and (for diff-impact) the diff_identity both sides must share.
    """
    plan = federation_plan(provider_spec, root, command_kind, db=db)
    result = {
        "warnings": list(plan["warnings"]), "fail_message": plan["fail_message"],
        "candidates": [], "conflicts": [], "providers_extra": [],
        "coverage": None, "known_gaps": None, "truncated": False,
        "diff_identity": None,
    }
    if plan["mode"] == "builtin":
        return None
    if plan["fail_message"]:
        return result
    if command_kind == "diff-impact":
        result["diff_identity"] = _diff_identity(root, symbol)
        if result["diff_identity"] is None:
            result["warnings"].append(
                f"cannot resolve diff identity for {symbol!r}; "
                "builtin and external impact sets are not directly comparable"
            )
        if staged or working_tree:
            scopes = ", ".join(
                s for s, on in (("staged", staged), ("working-tree", working_tree))
                if on
            )
            result["warnings"].append(
                f"scope conflict: {scopes} analysis is builtin-only; external "
                "evidence for git-ref scopes is never merged with it"
            )
            result["known_gaps"] = [
                f"scope conflict: {scopes} scope unsupported by external "
                "providers; builtin evidence only"
            ]
            return result

    healthy = plan["providers"]
    if not healthy:
        result["known_gaps"] = []
        return result
    # mode 'all' may carry several healthy providers; each one is a
    # candidate-evidence source and its candidates keep per-provider
    # provenance ("provider" on each entry, one coverage cell per name).
    result["providers_extra"] = [
        {"name": st["name"], "version": st["version"], "role": "candidate-evidence"}
        for st in plan["statuses"] if st["healthy"] and st["installed"]
    ]
    gaps: list = []
    coverage: dict = {}
    candidates: list = []
    conflicts: list = []
    truncated = False
    for provider in healthy:
        pname = provider.name
        per_plan = dict(plan, provider=provider, name=pname)
        outcome, method = run_federated_query(
            per_plan, root, command_kind, symbol,
            staged=staged, working_tree=working_tree, depth=depth,
        )
        cov: dict = {
            "queried": bool(outcome is not None and outcome.ok), "method": method,
        }
        if outcome is None:
            gaps.append(f"{pname}: capability negotiation found no invocable method for '{command_kind}'")
            cov["error"] = "no invocable method"
            if plan["mode"] == "require":
                plan["fail_message"] = result["fail_message"] = (
                    f"require:{pname}: no invocable method for '{command_kind}'; failing closed"
                )
                coverage[pname] = cov
                break
            result["warnings"].append(
                f"{pname}: no invocable method for '{command_kind}'; using sot-builtin only"
            )
        elif not outcome.ok:
            cov["error"] = outcome.error
            if outcome.next_action:
                gaps.append(f"{pname}: {outcome.next_action}")
            if plan["mode"] == "require":
                plan["fail_message"] = result["fail_message"] = (
                    f"require:{pname}: query failed ({outcome.error}); "
                    "failing closed"
                )
                coverage[pname] = cov
                break
            result["warnings"].append(
                f"{pname} query failed ({outcome.error}); using sot-builtin only"
            )
        else:
            sm = snapshot_match_of(outcome)
            sm_bound = (
                bool(sm.get("bound")) if isinstance(sm, dict)
                else bool(getattr(sm, "bound", False))
            )
            if not sm_bound:
                gaps.append(
                    "snapshot binding unproven: "
                    f"{pname} candidates are capped at UNVERIFIABLE"
                )
            per_candidates, one_truncated, gap_note = cbm_candidates_from_outcome(
                outcome, method or "search_symbols", pname, repo_root=root
            )
            candidates.extend(per_candidates)
            truncated = truncated or one_truncated
            if gap_note:
                gaps.append(gap_note)
            for cand in per_candidates:
                verified = cand.get("verified")
                detail = cand.get("detail") or ""
                if verified is not None and verified != "VERIFIED":
                    qn = cand["subject"].get("qualified_name") or "<unknown>"
                    gaps.append(
                        f"{pname}: {qn}: source verification {verified}"
                        + (f" ({detail})" if detail else "")
                    )
            # Conflicts stay per provider pair vs builtin; entries record
            # the provider they came from.
            conflicts.extend(target_conflicts(
                builtin_target, per_candidates, repo_root=root
            ))
        coverage[pname] = cov
    result["candidates"] = candidates
    result["truncated"] = truncated
    result["conflicts"] = conflicts
    result["coverage"] = coverage
    result["known_gaps"] = gaps
    return result

def architecture(provider_spec: Optional[str], root: str):
    """Expose ``get_architecture`` through the same negotiated plan (P3.1).

    Returns a QueryOutcome (or an abstained outcome when the spec is
    builtin/blocked). Inference claims without source anchors are the
    provider's own; the orchestrator does not re-label them verified.
    """
    from sot_graph.providers.base import ArchitectureRequest

    plan = federation_plan(provider_spec, root, "architecture")
    if plan["mode"] == "builtin":
        return None
    provider = plan["provider"]
    if provider is None:
        return None
    return provider.architecture(ArchitectureRequest(repo_root=root))


def envelope_fed_kwargs(db, fed: dict) -> dict:
    """Keyword additions for wrap_envelope reflecting one federation run."""
    from sot_graph.envelope import get_active_providers

    providers = get_active_providers(db) + fed["providers_extra"]
    return {
        "providers": providers,
        "coverage": fed["coverage"],
        "known_gaps": fed["known_gaps"],
        "truncated": fed["truncated"],
        "conflicts_detected": fed["conflicts"],
    }


def resolve_federated_spec(explicit: Optional[str], root: str) -> Optional[str]:
    """Effective spec for one command: explicit wins, then config auto (P2.c')."""
    from sot_graph.config import load_config

    cfg = load_config(root)
    return effective_provider_spec(explicit, cfg.providers_mode, cfg.allow_external)
