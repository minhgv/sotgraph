"""
sot_graph.pack — k-hop ContextBundle packaging for AI agent prompt registers.

Slices the verified graph around one target symbol: the exact source span of
the target (level 0), full caller/callee contracts one hop out (level 1), and
folded signature-only stubs beyond that (level >= 2). Every payload that
originated from source code is marked ``content_is_untrusted`` so downstream
agents treat docstrings and comments strictly as data, never as instructions.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.envelope import compute_snapshot_generation
from sot_graph.tokenizer import estimate_tokens, truncate_to_token_budget

__all__ = ["PackError", "build_bundle", "render_yaml"]

BUNDLE_SCHEMA_VERSION = "2.2.0"
_DEFAULT_MAX_HOPS = 2
_DEFAULT_MAX_NODES = 50
_DEFAULT_MAX_BYTES = 65_536

# Completeness vocabulary mirrors CompletenessStatus (sot_graph.evidence):
# a truncated projection is PARTIAL; only an uncut bundle stays within the
# index capability. Never report a complete status when limits.truncated.
_COMPLETENESS_WITHIN_INDEX = "COMPLETE_WITHIN_INDEX_CAPABILITY"
_COMPLETENESS_TRUNCATED = "PARTIAL"
#: Shown only on truncated bundles: absence of entries is budget-driven,
#: never evidence of zero callers/callees.
_ABSENCE_INTERPRETATION = (
    "truncated_bundle: absent entries do NOT imply zero callers/callees; see accounting"
)
_OMITTED_REFS_SAMPLE = 20
#: Under a hard token budget the omitted-refs hint shrinks to a single
#: example so accounting honesty cannot crowd the required code context
#: out of the bundle (counts + omit_reason always stay; only the sample
#: thins — the remainder is fetchable with a higher budget).
_OMITTED_REFS_BUDGET_SAMPLE = 1
#: YAML framing slop (marker text, accounting digit width) between the
#: source-fit estimate and the final measured render.
_FIT_MARGIN_TOKENS = 24
#: Meaningful source floor: below this the "source" would be a marker
#: fragment, not usable code context. When the budget cannot honor it the
#: floor yields (to an absolute minimum) and the accounting publishes
#: explicit partial counts instead of leaving a thin fragment to imply
#: usefulness.
_MIN_USEFUL_SOURCE_TOKENS = 48
_MIN_USEFUL_SOURCE_BYTES = 192
#: Resource cap: only this many leading bytes of a target file are ever
#: materialized for span slicing (the freshness hash streams separately),
#: so an arbitrary oversized file is never read fully into memory.
_MAX_SOURCE_READ_BYTES = 1_048_576
#: Corpus-convention segments that shadow a "test" basename: a ``tests``
#: directory inside an evaluation/fixture/vendor corpus is corpus data,
#: not executable usage evidence. Fixture/eval/vendor take precedence
#: over test segments (same precedence intent as repo classifiers).
_NON_TEST_CORPUS_SEGMENTS = frozenset({
    "fixtures", "fixture", "testdata", "test_data", "testdata_",
    "evaluation", "evals", "__snapshots__", "__fixtures__",
    "golden", "goldens", "samples",
    "vendor", "_vendor", "vendored", "third_party", "thirdparty",
    "external", "node_modules", "bower_components",
})
_TEST_ROOT_SEGMENTS = frozenset({"tests", "test", "spec", "specs", "__tests__"})


class PackError(RuntimeError):
    """Fail-closed packaging error; ``code`` is a stable machine verdict."""

    def __init__(self, code: str, message: str, candidates: Optional[List[str]] = None):
        super().__init__(message)
        self.code = code
        self.candidates = candidates or []


def _dominant_candidate(db, row):
    """Return the single candidate that dominates on inbound references, else None.

    A candidate dominates when it is the only one with inbound edges, or has
    at least twice the inbound edge count of the runner-up. Keeps ambiguous
    ``sotgraph pack`` targets resolvable without a FQN when evidence is decisive.
    """
    counts = {
        r[0]: int(
            db.conn.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE dst = ? AND relation != 'defines'",
                (r[0],),
            ).fetchone()[0]
        )
        for r in row
    }
    ranked = sorted(row, key=lambda r: counts[r[0]], reverse=True)
    referenced = [r for r in ranked if counts[r[0]] > 0]
    if len(referenced) == 1:
        return referenced[0]
    if not referenced:
        return None
    top, runner_up = referenced[0], referenced[1]
    if counts[top[0]] >= 2 * counts[runner_up[0]]:
        return top
    return None


def _find_target(db, target: str) -> Tuple[Dict[str, Any], str]:
    """Resolve a target by exact FQN, FQN suffix, then bare symbol.

    Ambiguous matches are auto-resolved to the dominant candidate by inbound
    edge count — never silently: the node dict carries
    ``_ambiguous_auto_resolved`` plus the full ``_ambiguous_candidates`` list
    so the bundle can surface the resolution explicitly. Raises
    :class:`PackError` (with candidates) when no candidate wins.
    """
    row = db.conn.execute(
        "SELECT id,path,kind,symbol,fqn,signature,label,body,"
        "line_start,line_end,col_start,col_end FROM graph_nodes "
        "WHERE fqn = ? AND kind != 'file' LIMIT 2", (target,)
    ).fetchall()
    if len(row) > 1:
        raise PackError("AMBIGUOUS_TARGET", f"fqn matches multiple nodes: {target}")
    if not row:
        row = db.conn.execute(
            "SELECT id,path,kind,symbol,fqn,signature,label,body,"
            "line_start,line_end,col_start,col_end FROM graph_nodes "
            "WHERE (fqn LIKE ? OR fqn LIKE ?) AND kind != 'file' LIMIT 11",
            (f"%.{target}", f"{target}.%"),
        ).fetchall()
    auto_resolved = False
    amb_candidates: List[str] = []
    if len(row) > 1:
        dominant = _dominant_candidate(db, row)
        if dominant is None:
            raise PackError(
                "AMBIGUOUS_TARGET",
                f"target '{target}' matches {len(row)} nodes; qualify with a FQN",
                candidates=[r[4] for r in row[:10]],
            )
        amb_candidates = [r[4] for r in row[:10]]
        row = [dominant]
        auto_resolved = True
    if not row:
        row = db.conn.execute(
            "SELECT id,path,kind,symbol,fqn,signature,label,body,"
            "line_start,line_end,col_start,col_end FROM graph_nodes "
            "WHERE symbol = ? AND kind != 'file' LIMIT 11", (target,)
        ).fetchall()
        if len(row) > 1:
            dominant = _dominant_candidate(db, row)
            if dominant is None:
                raise PackError(
                    "AMBIGUOUS_TARGET",
                    f"symbol '{target}' is defined in {len(row)} places; use a FQN",
                    candidates=[r[4] for r in row[:10]],
                )
            amb_candidates = [r[4] for r in row[:10]]
            row = [dominant]
            auto_resolved = True
    if not row:
        raise PackError("TARGET_NOT_FOUND", f"no indexed symbol matches '{target}'")
    r = row[0]
    node = {
        "id": r[0], "path": r[1], "kind": r[2], "symbol": r[3], "fqn": r[4],
        "signature": r[5], "label": r[6], "body": r[7],
        "line_start": r[8], "line_end": r[9], "col_start": r[10], "col_end": r[11],
        "_ambiguous_auto_resolved": auto_resolved,
        "_ambiguous_candidates": amb_candidates,
    }
    return node, target


def _node_row(db, node_id: str) -> Optional[Dict[str, Any]]:
    r = db.conn.execute(
        "SELECT id,path,kind,symbol,fqn,signature,label,line_start,line_end "
        "FROM graph_nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not r:
        return None
    return {
        "id": r[0], "path": r[1], "kind": r[2], "symbol": r[3], "fqn": r[4],
        "signature": r[5], "label": r[6], "line_start": r[7], "line_end": r[8],
    }


def _neighbors(db, node_id: str) -> List[Tuple[str, str, Optional[int]]]:
    """(direction, node_id, line) for call/extends edges around a node."""
    rows = db.conn.execute(
        "SELECT 'in', e.src, e.line FROM graph_edges e "
        "WHERE e.dst = ? AND e.relation IN ('calls','extends') "
        "UNION ALL "
        "SELECT 'out', e.dst, e.line FROM graph_edges e "
        "WHERE e.src = ? AND e.relation IN ('calls','extends') "
        "ORDER BY 3, 2", (node_id, node_id)
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _slice_source_from_bytes(node: Dict[str, Any], raw_bytes: bytes,
                             total_size: Optional[int] = None,
                             read_cap: Optional[int] = None
                             ) -> Tuple[Optional[str], List[str]]:
    """Extract the exact source span from pre-read file bytes; None when spans are unknown.

    When the caller materialized only a bounded prefix of a larger file
    (``total_size > read_cap``) and the requested span reaches past that
    prefix, an explicit warning is emitted — the delivered source is then a
    bounded partial, never a silently clipped span.
    """
    warnings: List[str] = []
    if not node.get("line_start"):
        return None, ["span_unavailable: extractor recorded no line span"]
    text_content = raw_bytes.decode("utf-8", errors="replace")
    lines = text_content.splitlines(keepends=True)
    start = max(1, int(node["line_start"]))
    recorded_end = int(node["line_end"] or node["line_start"])
    end = recorded_end
    if end < start or end > len(lines) + 1:
        end = min(start + 200, len(lines) + 1)
        warnings.append("span_end_heuristic: recorded end line invalid")
    text = "".join(lines[start - 1:end])
    if not text.strip():
        return None, ["span_empty: recorded span has no content"]
    if (total_size is not None and read_cap is not None
            and total_size > read_cap and recorded_end >= len(lines)):
        warnings.append(
            f"source_read_bounded: file is {total_size} bytes, only the "
            f"first {read_cap} were materialized; the span reaches past "
            "the bounded prefix")
    return text, warnings


def _slice_source(node: Dict[str, Any]) -> Tuple[Optional[str], List[str]]:
    """Read the exact source span from disk; None when spans are unknown."""
    path = node["path"]
    try:
        with open(path, "rb") as handle:
            raw_bytes = handle.read()
    except OSError as exc:
        raise PackError("TARGET_MISSING", f"target file unreadable: {exc}") from exc
    return _slice_source_from_bytes(node, raw_bytes)


def _dedent_block(text: str) -> str:
    import textwrap
    return textwrap.dedent(text).strip("\n")
def _verify_neighbor_freshness(db, neighbor_path: str) -> Tuple[str, Optional[str]]:
    """Check if neighbor file exists and matches indexed hash.

    Returns (verdict, warning_or_none) where verdict is 'FRESH', 'STALE', or 'MISSING'.
    """
    if not os.path.isfile(neighbor_path):
        return "MISSING", f"neighbor_missing: file {neighbor_path} no longer exists on disk"

    journal = db.conn.execute(
        "SELECT sha256 FROM file_journal WHERE path = ?", (neighbor_path,)
    ).fetchone()
    if journal is None:
        return "UNKNOWN", f"neighbor_unindexed: file {neighbor_path} is not in file journal"

    try:
        with open(neighbor_path, "rb") as fh:
            disk_sha = hashlib.sha256(fh.read()).hexdigest()
        if disk_sha != journal[0]:
            return "STALE", f"neighbor_stale: file {neighbor_path} modified on disk since indexing"
        return "FRESH", None
    except OSError as exc:
        return "UNREADABLE", f"neighbor_error: cannot read {neighbor_path}: {exc}"


def build_bundle(
    db,
    root: str,
    target: str,
    max_hops: int = _DEFAULT_MAX_HOPS,
    max_nodes: int = _DEFAULT_MAX_NODES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the ContextBundle structure; raises :class:`PackError` closed."""
    node, matched = _find_target(db, target)
    amb_candidates: List[str] = node.pop("_ambiguous_candidates", [])

    journal = db.conn.execute(
        "SELECT sha256, generation FROM file_journal WHERE path = ?",
        (node["path"],),
    ).fetchone()
    if journal is None:
        raise PackError(
            "TARGET_MISSING",
            f"target file is not reconciled: {node['path']}; run `sotgraph reconcile`",
        )
    indexed_sha, base_generation = journal[0], int(journal[1] or 1)
    # Global staleness binding (same mechanism as envelopes/receipts): a caller
    # compares this against the DB's current MAX(generation) to detect drift.
    snapshot_generation = compute_snapshot_generation(db)

    # Bounded read (resource cap): the freshness hash streams the whole
    # file in chunks — exactness preserved — while only the leading
    # _MAX_SOURCE_READ_BYTES are materialized for span slicing, so an
    # arbitrary oversized file is never loaded into memory in full.
    digest = hashlib.sha256()
    head = bytearray()
    total_size = 0
    try:
        with open(node["path"], "rb") as handle:
            while True:
                chunk = handle.read(262_144)
                if not chunk:
                    break
                total_size += len(chunk)
                digest.update(chunk)
                if len(head) < _MAX_SOURCE_READ_BYTES:
                    head.extend(chunk[:_MAX_SOURCE_READ_BYTES - len(head)])
    except OSError as exc:
        raise PackError("TARGET_MISSING", f"target file no longer exists or unreadable: {node['path']}") from exc

    disk_sha = digest.hexdigest()
    raw_bytes = bytes(head)
    if disk_sha != indexed_sha:
        raise PackError(
            "STALE_SNAPSHOT",
            f"target changed on disk since last reconcile: {node['path']}; "
            "run `sotgraph reconcile` and re-pack",
        )

    full_source, warnings = _slice_source_from_bytes(
        node, raw_bytes, total_size=total_size, read_cap=_MAX_SOURCE_READ_BYTES)
    resolution: Dict[str, Any] = {
        "status": "AMBIGUOUS_AUTO_RESOLVED" if amb_candidates else "EXACT",
        "query": target,
        "selected_fqn": node["fqn"] or node["symbol"],
    }
    if amb_candidates:
        resolution["method"] = "dominant_inbound_edges"
        resolution["candidates"] = list(amb_candidates)
    if node.pop("_ambiguous_auto_resolved", False):
        warnings.append(
            f"ambiguous_target_auto_resolved: '{target}' matched multiple nodes; "
            f"selected dominant candidate {node['fqn']} by inbound reference count"
        )
    truncated = False
    #: Which budget phase dropped the trusted-instructions seed (byte runs
    #: before token), so the accounting omit_reason names the true cause.
    instructions_dropped: Dict[str, Optional[str]] = {"phase": None}
    #: Why the delivered source is partial (span oversize at read time,
    #: byte budget, or token budget) — cause-specific honesty flags.
    source_truncated_cause: Dict[str, Optional[str]] = {"cause": None}
    if any("source_read_bounded" in w for w in warnings):
        # The span reached past the materialized prefix of an oversized
        # file: the delivered source is a bounded partial even when it fits
        # the byte cap — never present it as untruncated.
        truncated = True
        source_truncated_cause["cause"] = "read_cap_bounded"
    if full_source is not None and len(full_source.encode("utf-8")) > max_bytes:
        # Honest oversize behavior: a symbol whose span exceeds the byte cap
        # no longer fails the whole bundle closed. Deliver identity metadata
        # plus a byte-truncated source prefix, explicitly flagged — an
        # oversize symbol is a projection problem, not a packaging failure.
        encoded = full_source.encode("utf-8")
        full_source = encoded[:max_bytes].decode("utf-8", errors="ignore")
        truncated = True
        source_truncated_cause["cause"] = "source_span_exceeds_byte_cap"
        warnings.append(
            f"target_source_oversize: span was {len(encoded)} bytes, "
            f"full_source truncated to max_bytes cap {max_bytes}; "
            "raise --max-bytes or split the symbol for the full span"
        )

    rel_path = (os.path.relpath(node["path"], root) if os.path.isabs(node["path"]) else node["path"]).replace(os.sep, "/")

    target_block = {
        "node_id": node["id"],
        "fqn": node["fqn"] or node["symbol"],
        "symbol": node["symbol"],
        "kind": node["kind"],
        "relative_path": rel_path,
        "trust_verdict": "STRONG",
        "indexed_sha256": indexed_sha,
        "span": {
            "start_line": node["line_start"],
            "end_line": node["line_end"],
            "start_column": node.get("col_start"),
            "end_column": node.get("col_end"),
        },
        "signature": node["signature"],
        "full_source": full_source,
    }

    visited = {node["id"]}
    inbound: List[Dict[str, Any]] = []
    outbound: List[Dict[str, Any]] = []
    level1_ids: List[str] = []

    # Discover the full 1-hop neighborhood up front so accounting can report
    # honest discovered/omitted counts even when caps stop traversal early.
    discovered_1hop: List[Tuple[str, str, Optional[int]]] = []
    seen_1hop = set()
    for direction, neighbor_id, line in _neighbors(db, node["id"]):
        if neighbor_id in visited or neighbor_id in seen_1hop:
            continue
        seen_1hop.add(neighbor_id)
        discovered_1hop.append((direction, neighbor_id, line))
    discovered_in_ids = [nid for d, nid, _ in discovered_1hop if d == "in"]
    discovered_out_ids = [nid for d, nid, _ in discovered_1hop if d == "out"]

    #: Per-category drop-phase flags: the last phase that dropped items in a
    #: category determines its omit_reason (token > byte > node cap).
    cap_dropped = {"inbound_callers": False, "outbound_callees": False, "transitive_stubs": False}
    byte_dropped = {"inbound_callers": False, "outbound_callees": False, "transitive_stubs": False}
    token_dropped = {"inbound_callers": False, "outbound_callees": False, "transitive_stubs": False}

    # Prioritized candidate selection (deterministic, stable within
    # classes, ties by call-site line). The value order is applied BEFORE
    # the node cap so a small ``max_nodes`` keeps the most valuable
    # neighbors instead of whichever rows happened to sort first by line —
    # otherwise a dropped test-module usage caller or a dropped direct
    # contract could never be recovered by later pruning phases.
    #   class 0: the FIRST test-module caller (earliest line) — one
    #     executable usage example is reserved a slot;
    #   class 1: direct outbound callees — exact same FILE, then same
    #     directory, then the rest (identity obligations);
    #   class 2: surplus production callers;
    #   class 3: surplus test-module callers.
    def _is_test_module(rel: str) -> bool:
        """A test module lives under a test root and is not shadowed by a
        fixture/evaluation/vendor corpus segment (which take precedence:
        ``evaluation/tests/`` is corpus data, not usage evidence)."""
        segments = [s for s in rel.replace("\\", "/").split("/") if s]
        if any(seg in _NON_TEST_CORPUS_SEGMENTS for seg in segments[:-1]):
            return False
        if not any(seg in _TEST_ROOT_SEGMENTS for seg in segments[:-1]):
            return False
        base = segments[-1]
        return base.startswith("test_") or base.endswith("_test.py")

    _rel_by_id: Dict[str, str] = {}
    _test_line_by_id: Dict[str, int] = {}
    for _direction, _nid, _line in discovered_1hop:
        _row = _node_row(db, _nid)
        if _row is None:
            continue
        _p = _row["path"]
        _rel_by_id[_nid] = (os.path.relpath(_p, root) if os.path.isabs(_p) else _p).replace(os.sep, "/")
        if _direction == "in" and _is_test_module(_rel_by_id[_nid]):
            _test_line_by_id[_nid] = _line or 0
    _reserved_test_id = (
        min(_test_line_by_id, key=lambda nid: (_test_line_by_id[nid], nid))
        if _test_line_by_id else None)

    def _neighbor_sort_key(item: Tuple[str, str, Optional[int]]):
        direction, neighbor_id, line = item
        rel = _rel_by_id.get(neighbor_id)
        if rel is None:
            return (4, 9, line or 0)
        if direction == "in":
            if neighbor_id == _reserved_test_id:
                return (0, 0, line or 0)      # reserved usage example
            if _is_test_module(rel):
                return (3, 0, line or 0)      # surplus test callers
            return (2, 0, line or 0)          # surplus production callers
        if rel == rel_path:
            cls = 0                       # exact same file
        elif os.path.dirname(rel) == os.path.dirname(rel_path):
            cls = 1                       # same directory
        else:
            cls = 2                       # elsewhere
        return (1, cls, line or 0)            # direct contracts

    for direction, neighbor_id, line in sorted(discovered_1hop, key=_neighbor_sort_key):
        if neighbor_id in visited:
            continue
        neighbor = _node_row(db, neighbor_id)
        if neighbor is None:
            continue
        visited.add(neighbor_id)
        if len(inbound) + len(outbound) >= max_nodes:
            cap_dropped["inbound_callers"] = True
            cap_dropped["outbound_callees"] = True
            warnings.append("node_cap_reached: 1-hop neighbors truncated")
            break

        n_verdict, n_warn = _verify_neighbor_freshness(db, neighbor["path"])
        if n_warn:
            warnings.append(n_warn)

        n_rel_path = (os.path.relpath(neighbor["path"], root) if os.path.isabs(neighbor["path"]) else neighbor["path"]).replace(os.sep, "/")

        if direction == "in":
            inbound.append({
                "node_id": neighbor["id"],
                "fqn": neighbor["fqn"] or neighbor["symbol"],
                "relative_path": n_rel_path,
                "trust_verdict": n_verdict,
                "callsite_line": line,
                "contract": neighbor["signature"] or neighbor["label"],
            })
        else:
            outbound.append({
                "node_id": neighbor["id"],
                "fqn": neighbor["fqn"] or neighbor["symbol"],
                "relative_path": n_rel_path,
                "trust_verdict": n_verdict,
                "signature": neighbor["signature"] or neighbor["label"],
            })
        level1_ids.append(neighbor_id)

    stubs: List[Dict[str, Any]] = []
    discovered_stub_refs: List[str] = []
    if max_hops >= 2:
        budget = max_nodes - len(visited) + 1
        stub_seen = set()
        for level1_id in level1_ids:
            if budget <= 0:
                cap_dropped["transitive_stubs"] = True
                warnings.append("node_cap_reached: 2-hop stubs truncated")
                break
            for _direction, neighbor_id, _line in _neighbors(db, level1_id):
                if neighbor_id in visited or neighbor_id in stub_seen:
                    continue
                neighbor = _node_row(db, neighbor_id)
                if neighbor is None or neighbor["kind"] == "file":
                    continue
                stub_seen.add(neighbor_id)
                discovered_stub_refs.append(neighbor["fqn"] or neighbor["symbol"])
                if budget <= 0:
                    cap_dropped["transitive_stubs"] = True
                    continue
                visited.add(neighbor_id)
                budget -= 1
                stubs.append({
                    "fqn": neighbor["fqn"] or neighbor["symbol"],
                    "signature": neighbor["signature"] or neighbor["label"],
                })

    # Hard byte cap: keep target + inbound contracts; drop from the tail.
    # Load trusted instructions first so the cap accounts for them too.
    trusted = _load_trusted_instructions(root, max_bytes)
    trusted_discovered = trusted is not None

    def _initial_accounting() -> Dict[str, Dict[str, Any]]:
        return {
            "instructions": {
                "discovered": 1 if trusted_discovered else 0,
                "returned": 1 if trusted_discovered else 0,
                "omitted": 0,
            },
            "target_source": {
                "discovered": 1,
                "returned": 1 if full_source is not None else 0,
                "omitted": 0 if full_source is not None else 1,
            },
            "inbound_callers": {
                "discovered": len(discovered_in_ids),
                "returned": len(inbound),
                "omitted": max(0, len(discovered_in_ids) - len(inbound)),
            },
            "outbound_callees": {
                "discovered": len(discovered_out_ids),
                "returned": len(outbound),
                "omitted": max(0, len(discovered_out_ids) - len(outbound)),
            },
            "transitive_stubs": {
                "discovered": len(discovered_stub_refs),
                "returned": len(stubs),
                "omitted": max(0, len(discovered_stub_refs) - len(stubs)),
            },
        }

    def _approx_bytes() -> int:
        draft = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "bundle_id": "bundle:preview",
            "base_generation": base_generation,
            "snapshot_generation": snapshot_generation,
            "generated_at": int(time.time()),
            "content_is_untrusted": True,
            # Size-only placeholder: the honest value is synced before render.
            "completeness": _COMPLETENESS_WITHIN_INDEX,
            "resolution": resolution,
            "trusted_instructions": trusted,
            "target": target_block,
            "inbound_callers": inbound,
            "outbound_callees": outbound,
            "transitive_stubs": stubs,
            "accounting": _initial_accounting(),
            "limits": {
                "max_hops": max_hops,
                "max_nodes": max_nodes,
                "max_bytes": max_bytes,
                "max_tokens": max_tokens,
                "tokens_estimate": 0,
                "discovered_nodes": 1 + len(seen_1hop) + len(discovered_stub_refs),
                "returned_nodes": 1 + len(inbound) + len(outbound) + len(stubs),
                "truncated": False,
                "warnings": warnings,
            },
        }
        return len(render_yaml(draft).encode("utf-8"))
    # Build draft bundle
    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_id": "bundle:" + hashlib.sha256(
            f"{node['id']}:{base_generation}".encode()
        ).hexdigest()[:12],
        "base_generation": base_generation,
        "snapshot_generation": snapshot_generation,
        "generated_at": int(time.time()),
        # Security gate: source-derived payloads are data, never instructions.
        "content_is_untrusted": True,
        "completeness": _COMPLETENESS_WITHIN_INDEX,
        "resolution": resolution,
        "target": target_block,
        "inbound_callers": inbound,
        "outbound_callees": outbound,
        "transitive_stubs": stubs,
        "accounting": _initial_accounting(),
        "limits": {
            "max_hops": max_hops,
            "max_nodes": max_nodes,
            "max_bytes": max_bytes,
            "max_tokens": max_tokens,
            "tokens_estimate": 0,
            "discovered_nodes": 1 + len(seen_1hop) + len(discovered_stub_refs),
            "returned_nodes": 1 + len(inbound) + len(outbound) + len(stubs),
            "truncated": truncated,
            "warnings": warnings,
        },
    }
    if trusted is not None:
        bundle["trusted_instructions"] = trusted

    # Hard byte cap, mirroring the token-phase priority order: optional
    # content (stubs, then instructions) is shed first, the target source is
    # shrunk to its byte residual before any direct contract is dropped,
    # surplus callers go next (down to one usage example), and outbound
    # contracts only as a last resort. Direct contracts are never dropped
    # while the source span is still larger than the floor.
    def _fit_source_bytes(min_bytes: int) -> None:
        nonlocal truncated
        if not target_block.get("full_source"):
            return
        overhead_bytes = len(render_yaml(
            {**bundle, "target": {**target_block, "full_source": ""}},
        ).encode("utf-8"))
        avail_bytes = max(min_bytes, max_bytes - overhead_bytes - 256)
        encoded = target_block["full_source"].encode("utf-8")
        if len(encoded) <= avail_bytes:
            return
        target_block["full_source"] = encoded[:avail_bytes].decode("utf-8", errors="ignore")
        truncated = True
        bundle["limits"]["truncated"] = True
        source_truncated_cause["cause"] = "byte_budget_exhausted"
        warnings.append("byte_cap_reached: target full_source truncated")

    def _pop_caller() -> None:
        nonlocal truncated
        inbound.pop()
        byte_dropped["inbound_callers"] = True
        truncated = True
        bundle["limits"]["truncated"] = True

    def _pop_callee() -> None:
        nonlocal truncated
        outbound.pop()
        byte_dropped["outbound_callees"] = True
        truncated = True
        bundle["limits"]["truncated"] = True

    while _approx_bytes() > max_bytes and stubs:
        stubs.pop()
        byte_dropped["transitive_stubs"] = True
        truncated = True
        bundle["limits"]["truncated"] = True
    if _approx_bytes() > max_bytes and bundle.get("trusted_instructions"):
        del bundle["trusted_instructions"]
        instructions_dropped["phase"] = "byte"
        truncated = True
        bundle["limits"]["truncated"] = True
        warnings.append("byte_cap_reached: trusted instructions omitted")
    if _approx_bytes() > max_bytes:
        _fit_source_bytes(_MIN_USEFUL_SOURCE_BYTES)
    while _approx_bytes() > max_bytes and len(inbound) > 1:
        _pop_caller()
    while _approx_bytes() > max_bytes and outbound:
        _pop_callee()
    while _approx_bytes() > max_bytes and inbound:
        _pop_caller()
    if _approx_bytes() > max_bytes and target_block.get("full_source"):
        _fit_source_bytes(_MIN_USEFUL_SOURCE_BYTES)
    if _approx_bytes() > max_bytes:
        # The identity metadata + source floor alone exceed the cap: keep
        # the honest minimum instead of an empty shell, and say so.
        byte_unreachable = (
            "byte_cap_unreachable: the bundle metadata floor exceeds "
            "max_bytes; delivered the identity + source floor honestly "
            "rather than an empty shell — raise --max-bytes")
        if byte_unreachable not in warnings:
            warnings.append(byte_unreachable)

    def _refresh_accounting() -> None:
        """Recompute per-category discovered/returned/omitted from live state."""
        def reason_for(category: str) -> Optional[str]:
            if token_dropped[category]:
                return "token_budget_exhausted"
            if byte_dropped[category]:
                return "byte_budget_exhausted"
            if cap_dropped[category]:
                return "node_cap"
            return None

        accounting: Dict[str, Dict[str, Any]] = {}
        if trusted_discovered:
            present = bundle.get("trusted_instructions") is not None
            entry: Dict[str, Any] = {
                "discovered": 1,
                "returned": 1 if present else 0,
                "omitted": 0 if present else 1,
            }
            if not present:
                entry["omit_reason"] = (
                    "byte_budget_exhausted"
                    if instructions_dropped["phase"] == "byte"
                    else "token_budget_exhausted")
            accounting["instructions"] = entry

        if full_source is None:
            # Seed never rendered: the recorded span was unusable, not budget.
            src_reason = "span_unavailable"
            if not any(w.startswith(("span_unavailable", "span_empty")) for w in warnings):
                src_reason = "budget_exhausted"
            accounting["target_source"] = {
                "discovered": 1, "returned": 0, "omitted": 1, "omit_reason": src_reason,
            }
        else:
            src_now = target_block.get("full_source")
            src_entry: Dict[str, Any] = {
                "discovered": 1,
                "returned": 0 if src_now == "" else 1,
                "omitted": 1 if src_now == "" else 0,
            }
            if src_now == "":
                src_entry["omit_reason"] = source_truncated_cause["cause"] or "token_budget_exhausted"
            elif (any("full_source truncated" in w for w in warnings)
                  or source_truncated_cause["cause"]):
                # Cause-specific honesty: name the actual constraint that
                # truncated the span (span oversize, read cap, byte budget,
                # or token budget) instead of a blanket token reason, and
                # publish explicit partial line counts.
                src_entry["truncated"] = True
                src_entry["omit_reason"] = (
                    source_truncated_cause["cause"] or "token_budget_exhausted")
                # Explicit partial counts: a truncated source must never
                # imply the full span was delivered.
                recorded = max(1, int(node["line_end"] or node["line_start"] or 1)
                               - max(1, int(node["line_start"] or 1)) + 1)
                delivered: str = src_now or ""
                src_entry["partial"] = True
                src_entry["returned_lines"] = len(delivered.splitlines())
                src_entry["recorded_lines"] = recorded
            accounting["target_source"] = src_entry

        neighbor_state = (
            ("inbound_callers", discovered_in_ids, [c["node_id"] for c in inbound]),
            ("outbound_callees", discovered_out_ids, [c["node_id"] for c in outbound]),
            ("transitive_stubs", discovered_stub_refs, [s["fqn"] for s in stubs]),
        )
        for category, discovered_refs, returned_refs in neighbor_state:
            returned_set = set(returned_refs)
            omitted_refs = [ref for ref in discovered_refs if ref not in returned_set]
            entry = {
                "discovered": len(discovered_refs),
                "returned": len(returned_refs),
                "omitted": len(omitted_refs),
            }
            if omitted_refs:
                entry["omit_reason"] = reason_for(category) or "budget_exhausted"
                # Sample of refs so the caller can fetch the remainder.
                refs_sample = (_OMITTED_REFS_SAMPLE if max_tokens is None
                               else _OMITTED_REFS_BUDGET_SAMPLE)
                entry["omitted_refs"] = omitted_refs[:refs_sample]
            accounting[category] = entry
        bundle["accounting"] = accounting

    def _sync_honesty() -> None:
        truncated_now = bool(bundle["limits"]["truncated"])
        bundle["completeness"] = (
            _COMPLETENESS_TRUNCATED if truncated_now else _COMPLETENESS_WITHIN_INDEX
        )
        if truncated_now:
            bundle["absence_interpretation"] = _ABSENCE_INTERPRETATION
        else:
            bundle.pop("absence_interpretation", None)

    def _measured_yaml() -> str:
        _refresh_accounting()
        _sync_honesty()
        return render_yaml(bundle)

    def _warn_once(message: str) -> None:
        """Append a warning at most once (repeated pruning passes must not
        duplicate warnings — each copy would itself cost budget tokens)."""
        if message not in warnings:
            warnings.append(message)

    # Hard token budget enforcement if max_tokens is provided
    if max_tokens is not None:
        if max_tokens < 32:
            raise PackError("BUDGET_TOO_SMALL", f"max_tokens ({max_tokens}) is too small to fit target block metadata (minimum 32 tokens required)")
        rendered = _measured_yaml()
        tok_count = estimate_tokens(rendered)
        # Truncation itself costs tokens (completeness flips to PARTIAL, the
        # absence note and accounting refs appear, estimate digits change), so
        # a single pruning pass can land just above budget. Iterate until the
        # measured render fits or nothing is left to cut; fail closed then.
        for _pass in range(8):
            progressed = False

            def _sync_lists() -> None:
                bundle["inbound_callers"] = inbound
                bundle["outbound_callees"] = outbound
                bundle["transitive_stubs"] = stubs
                bundle["limits"]["returned_nodes"] = (
                    1 + len(inbound) + len(outbound) + len(stubs))

            # Priority order under a hard token budget. Optional content is
            # shed before required content so the budget cannot be starved:
            #   1. transitive stubs  (level>=2 detail, optional by design)
            #   2. trusted instructions (operator-authored, re-readable in repo)
            #   3. target source bounded to the share left after the required
            #      neighbor sections, with a useful-share floor
            #   4. inbound callers from the tail — but at most down to one
            #      retained caller (value ordering keeps a test-module usage
            #      example in that slot): a single usage example is honest
            #      evidence, surplus caller coverage is elastic
            #   5. target source squeezed to its exact residual BEFORE any
            #      direct contract is dropped — contracts are a bounded,
            #      all-or-nothing obligation; the source span is elastic and
            #      its signature field always survives in the target block
            #   6. outbound callees from the tail (same-file contracts last)
            #   7. the last caller and then the source itself, only when the
            #      metadata floor alone reaches the budget

            def _fit_source(min_tokens: int) -> None:
                """Truncate full_source to the residual the budget allows."""
                nonlocal truncated, progressed, rendered, tok_count
                if not target_block.get("full_source"):
                    return
                source_truncated_cause["cause"] = "token_budget_exhausted"
                overhead_tokens = estimate_tokens(render_yaml({**bundle, "target": {**target_block, "full_source": ""}}))
                avail_source_tokens = max(
                    min_tokens,
                    max_tokens - overhead_tokens - _FIT_MARGIN_TOKENS)
                trunc_src, is_trunc, _ = truncate_to_token_budget(target_block["full_source"], avail_source_tokens)
                if is_trunc:
                    target_block["full_source"] = trunc_src
                    truncated = True
                    bundle["limits"]["truncated"] = True
                    progressed = True
                    _warn_once("token_cap_reached: target full_source truncated")
                    rendered = _measured_yaml()
                    tok_count = estimate_tokens(rendered)

            while tok_count > max_tokens and stubs:
                stubs.pop()
                token_dropped["transitive_stubs"] = True
                truncated = True
                bundle["limits"]["truncated"] = True
                progressed = True
                _sync_lists()
                rendered = _measured_yaml()
                tok_count = estimate_tokens(rendered)

            if tok_count > max_tokens and bundle.get("trusted_instructions"):
                del bundle["trusted_instructions"]
                instructions_dropped["phase"] = "token"
                truncated = True
                bundle["limits"]["truncated"] = True
                progressed = True
                _warn_once("token_cap_reached: trusted instructions omitted")
                rendered = _measured_yaml()
                tok_count = estimate_tokens(rendered)

            if tok_count > max_tokens and target_block.get("full_source"):
                # Keep a meaningful source share (signature plus leading
                # body) unless even that cannot fit above the pure-metadata
                # floor — then yield to the absolute minimum and let the
                # accounting partial counts tell the truth. Sparse bundles
                # give the source the full residual anyway.
                metadata_floor = estimate_tokens(render_yaml({
                    **bundle, "trusted_instructions": None,
                    "inbound_callers": [], "outbound_callees": [],
                    "transitive_stubs": [],
                    "target": {**target_block, "full_source": ""},
                }))
                feasible = max_tokens - metadata_floor >= _MIN_USEFUL_SOURCE_TOKENS
                _fit_source(_MIN_USEFUL_SOURCE_TOKENS if feasible else 16)

            while tok_count > max_tokens and len(inbound) > 1:
                # Shed surplus callers first; direct callee contracts and one
                # usage example outrank additional caller coverage.
                inbound.pop()
                token_dropped["inbound_callers"] = True
                truncated = True
                bundle["limits"]["truncated"] = True
                progressed = True
                _sync_lists()
                rendered = _measured_yaml()
                tok_count = estimate_tokens(rendered)

            if tok_count > max_tokens:
                # Contracts outrank the source share: squeeze the source to
                # its exact residual before any direct callee is dropped.
                _fit_source(16)

            if tok_count > max_tokens and not bundle.get("metadata_compact"):
                # Metadata compaction before any required context is dropped:
                # neighbor ``node_id`` lines duplicate the path/fqn identity
                # and FRESH ``trust_verdict`` lines restate the verified
                # default. No discovered content is omitted (accounting stays
                # exact), so the global truncated flag is untouched; the
                # compacted mode is disclosed via the limits flag + warning.
                # Compaction is kept only when it pays for its own disclosure
                # (flag + warning lines) — on small bundles it rolls back
                # instead of pushing the render over budget.
                bundle["metadata_compact"] = True
                bundle["limits"]["metadata_compact"] = True
                _compact_note = ("token_cap_reached: metadata compacted "
                                 "(neighbor node_id / FRESH trust_verdict omitted)")
                _warn_once(_compact_note)
                _compact_yaml = _measured_yaml()
                _compact_tokens = estimate_tokens(_compact_yaml)
                if _compact_tokens < tok_count:
                    rendered = _compact_yaml
                    tok_count = _compact_tokens
                    progressed = True
                else:
                    del bundle["metadata_compact"]
                    del bundle["limits"]["metadata_compact"]
                    if _compact_note in warnings:
                        warnings.remove(_compact_note)

            while tok_count > max_tokens and outbound:
                outbound.pop()
                token_dropped["outbound_callees"] = True
                truncated = True
                bundle["limits"]["truncated"] = True
                progressed = True
                _sync_lists()
                rendered = _measured_yaml()
                tok_count = estimate_tokens(rendered)

            while tok_count > max_tokens and inbound:
                # The one-usage floor yields to the budget itself on very
                # tight caps: a caller that cannot fit is omitted honestly
                # (accounting keeps discovered/omitted + reason).
                inbound.pop()
                token_dropped["inbound_callers"] = True
                truncated = True
                bundle["limits"]["truncated"] = True
                progressed = True
                _sync_lists()
                rendered = _measured_yaml()
                tok_count = estimate_tokens(rendered)

            if tok_count > max_tokens and target_block.get("full_source"):
                # Last resort: a bounded halving loop that converges even
                # when YAML framing shifts the measured count (empty source
                # when the metadata floor alone reaches the budget).
                _warn_once("token_cap_reached: target full_source truncated")
                guard = 0
                while tok_count > max_tokens and target_block.get("full_source") and guard < 48:
                    guard += 1
                    curr_src = target_block["full_source"]
                    target_block["full_source"] = "" if len(curr_src) <= 50 else curr_src[:len(curr_src) // 2]
                    source_truncated_cause["cause"] = "token_budget_exhausted"
                    truncated = True
                    bundle["limits"]["truncated"] = True
                    progressed = True
                    rendered = _measured_yaml()
                    tok_count = estimate_tokens(rendered)

            # Stable token estimation & final validation. Writing the real
            # estimate can change its own digit width, so re-measure until the
            # reported number matches the rendered bundle exactly.
            tok_est = estimate_tokens(_measured_yaml())
            bundle["limits"]["tokens_estimate"] = tok_est
            tok_count = estimate_tokens(_measured_yaml())
            if tok_count != tok_est:
                bundle["limits"]["tokens_estimate"] = tok_count
                tok_count = estimate_tokens(_measured_yaml())

            if tok_count <= max_tokens:
                break
            if not progressed and not (
                stubs or outbound or inbound
                or bundle.get("trusted_instructions")
                or target_block.get("full_source")
            ):
                raise PackError("BUDGET_TOO_SMALL", f"rendered bundle ({tok_count} tokens) exceeds budget ({max_tokens} tokens)")
            # Writing the real estimate can push the render a token or two
            # over (digit width); loop back into pruning with the re-measured
            # count instead of failing while content remains to cut.
        else:
            raise PackError("BUDGET_TOO_SMALL", f"rendered bundle ({tok_count} tokens) exceeds budget ({max_tokens} tokens)")
    else:
        _refresh_accounting()
        _sync_honesty()
        tok_est = estimate_tokens(render_yaml(bundle))
        bundle["limits"]["tokens_estimate"] = tok_est
        rendered = render_yaml(bundle)
        tok_count = estimate_tokens(rendered)
        if tok_count != tok_est:
            bundle["limits"]["tokens_estimate"] = tok_count
    return bundle

_TRUSTED_INSTRUCTION_FILES = ("AGENTS.md",)
_TRUSTED_MAX_BYTES = 8192


def _load_trusted_instructions(root: str, max_bytes: int) -> Optional[Dict[str, Any]]:
    """Repo-level instruction files are operator-authored, hence trusted.

    The bundle's global banner stays untrusted; this block carries an
    explicit per-block override so prompt builders can treat only this
    content as instructions.
    """
    for name in _TRUSTED_INSTRUCTION_FILES:
        path = os.path.join(root, name)
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read(min(_TRUSTED_MAX_BYTES, max(max_bytes // 4, 1024)))
            if text.strip():
                return {
                    "path": name,
                    "bytes": len(text.encode("utf-8")),
                    "content_is_untrusted": False,
                    "content": text,
                }
        except OSError:
            continue
    return None


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_block(text: str, indent: int) -> str:
    """Emit a block literal; falls back to a quoted scalar on unsafe text."""
    pad = " " * indent
    if "\t" in text:
        return " " + json.dumps(text, ensure_ascii=False)
    body = _dedent_block(text)
    lines = body.split("\n")
    out = ["|"]
    for line in lines:
        out.append(f"{pad}{line}" if line else "")
    return "\n".join(out)


def _emit_neighbor(out: List[str], entry: Dict[str, Any], compact: bool) -> None:
    """Render one inbound/outbound neighbor row.

    Under metadata compaction the derivable fields are omitted from the
    serialized form (the dict itself keeps them): ``node_id`` duplicates the
    path/fqn identity and a ``FRESH`` trust_verdict restates the verified
    default. Non-default verdicts (STALE, REBUILT, ...) carry real
    information and lead the row so it keeps its list marker.
    """
    fields: List[str] = []
    verdict = entry.get("trust_verdict")
    show_verdict = "trust_verdict" in entry and not (compact and verdict == "FRESH")
    if compact:
        if show_verdict:
            fields.append(f"trust_verdict: {_yaml_scalar(verdict)}")
        fields.append(f"fqn: {_yaml_scalar(entry['fqn'])}")
    else:
        fields.append(f"node_id: {_yaml_scalar(entry['node_id'])}")
        fields.append(f"fqn: {_yaml_scalar(entry['fqn'])}")
        if show_verdict:
            fields.append(f"trust_verdict: {_yaml_scalar(verdict)}")
    fields.append(f"relative_path: {_yaml_scalar(entry['relative_path'])}")
    if "callsite_line" in entry:
        fields.append(f"callsite_line: {_yaml_scalar(entry['callsite_line'])}")
    if "contract" in entry:
        fields.append(f"contract: {_yaml_scalar(entry['contract'])}")
    if "signature" in entry:
        fields.append(f"signature: {_yaml_scalar(entry['signature'])}")
    out.append(f"  - {fields[0]}")
    for field in fields[1:]:
        out.append(f"    {field}")


def render_yaml(bundle: Dict[str, Any]) -> str:
    """Deterministic YAML rendering for the fixed ContextBundle schema."""
    out: List[str] = []
    t = bundle["target"]
    out.append(f"schema_version: {_yaml_scalar(bundle['schema_version'])}")
    out.append(f"bundle_id: {_yaml_scalar(bundle['bundle_id'])}")
    out.append(f"base_generation: {bundle['base_generation']}")
    if "snapshot_generation" in bundle:
        out.append(f"snapshot_generation: {bundle['snapshot_generation']}")
    out.append(f"generated_at: {bundle['generated_at']}")
    out.append(f"content_is_untrusted: {_yaml_scalar(bundle['content_is_untrusted'])}")
    completeness = bundle.get("completeness")
    if completeness:
        out.append(f"completeness: {_yaml_scalar(completeness)}")
    resolution = bundle.get("resolution")
    if resolution:
        # Flow-style: honesty metadata must not crowd code context out of
        # tight token budgets, so each block renders on a single line.
        parts = []
        for key in ("status", "query", "selected_fqn", "method"):
            if resolution.get(key):
                parts.append(f"{key}: {_yaml_scalar(resolution[key])}")
        candidates = resolution.get("candidates") or []
        if candidates:
            parts.append("candidates: [" + ", ".join(_yaml_scalar(c) for c in candidates) + "]")
        out.append(f"resolution: {{{', '.join(parts)}}}")
    trusted = bundle.get("trusted_instructions")
    if trusted:
        out.append("")
        out.append("trusted_instructions:")
        out.append(f"  path: {_yaml_scalar(trusted['path'])}")
        out.append(f"  bytes: {trusted['bytes']}")
        out.append(f"  content_is_untrusted: {_yaml_scalar(trusted['content_is_untrusted'])}")
        out.append(f"  content: {_yaml_block(trusted['content'], 4)}")
    absence = bundle.get("absence_interpretation")
    if absence:
        # Anti-inference gate: sits directly above the neighbor sections so a
        # reader cannot mistake empty/short lists for "no callers exist".
        out.append("")
        out.append(f"absence_interpretation: {_yaml_scalar(absence)}")
    out.append("")
    out.append("target:")
    for key in ("node_id", "fqn", "symbol", "kind", "relative_path", "trust_verdict",
                "indexed_sha256"):
        out.append(f"  {key}: {_yaml_scalar(t.get(key))}")
    out.append("  span:")
    for key, value in t["span"].items():
        out.append(f"    {key}: {_yaml_scalar(value)}")
    if t.get("signature"):
        out.append(f"  signature: {_yaml_scalar(t['signature'])}")
    if t.get("full_source") is not None:
        out.append(f"  full_source: {_yaml_block(t['full_source'], 4)}")
    else:
        out.append("  full_source: null")

    out.append("")
    out.append("inbound_callers:")
    compact = bool(bundle.get("metadata_compact"))
    if bundle["inbound_callers"]:
        for caller in bundle["inbound_callers"]:
            _emit_neighbor(out, caller, compact)
    else:
        out.append("  []")

    out.append("")
    out.append("outbound_callees:")
    if bundle["outbound_callees"]:
        for callee in bundle["outbound_callees"]:
            _emit_neighbor(out, callee, compact)
    else:
        out.append("  []")

    out.append("")
    out.append("transitive_stubs:")
    if bundle["transitive_stubs"]:
        for stub in bundle["transitive_stubs"]:
            out.append(f"  - fqn: {_yaml_scalar(stub['fqn'])}")
            out.append(f"    signature: {_yaml_scalar(stub['signature'])}")
    else:
        out.append("  []")

    limits = bundle["limits"]
    out.append("")
    out.append("limits:")
    for key in ("max_hops", "max_nodes", "max_bytes", "max_tokens", "tokens_estimate",
                "discovered_nodes", "returned_nodes", "truncated", "metadata_compact"):
        if key in limits:
            out.append(f"  {key}: {_yaml_scalar(limits.get(key))}")
    if limits.get("warnings"):
        out.append("  warnings:")
        for warning in limits["warnings"]:
            out.append(f"    - {_yaml_scalar(warning)}")
    else:
        out.append("  warnings: []")
    accounting = bundle.get("accounting")
    if accounting:
        out.append("")
        out.append("accounting:")
        for category, entry in accounting.items():
            parts = []
            for key in ("discovered", "returned", "omitted"):
                parts.append(f"{key}: {entry.get(key, 0)}")
            if entry.get("omit_reason"):
                parts.append(f"omit_reason: {_yaml_scalar(entry['omit_reason'])}")
            if entry.get("truncated"):
                parts.append("truncated: true")
            if entry.get("partial"):
                parts.append("partial: true")
            if "returned_lines" in entry:
                parts.append(f"returned_lines: {entry['returned_lines']}")
                parts.append(f"recorded_lines: {entry['recorded_lines']}")
            refs = entry.get("omitted_refs") or []
            if refs:
                parts.append("omitted_refs: [" + ", ".join(_yaml_scalar(r) for r in refs) + "]")
            out.append(f"  {category}: {{{', '.join(parts)}}}")
    return "\n".join(out) + "\n"
