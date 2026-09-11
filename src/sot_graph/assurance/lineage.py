"""W5 — lineage/dossier chain: scope receipt → diff receipt → commit → outcome.

Three links make a dossier complete:

  scope_to_diff     — a diff-impact receipt carries ``pre_receipt_digest``
                      (or ``lineage.scope_receipt_digest``) that resolves to a
                      stored scope receipt.
  diff_to_commit    — the diff receipt resolves to a commit sha (its recorded
                      ``diff_identity.target``, a direct child of
                      ``lineage.head_sha``, or a file-subset match).
  commit_to_outcome — the commit resolves to a computed verdict (any verdict,
                      including ``unknown`` — the link is the verdict
                      computation, not a favourable label).

Anchor may be a receipt digest (full or unambiguous prefix), a receipt path,
or a commit ref resolvable by ``git rev-parse``. Fail-closed: nothing is
fabricated — missing links are named, never guessed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _store_dir(repo_root: str) -> str:
    return os.path.join(repo_root, ".sot", "receipts")


def _load_store(store_dir: str) -> Dict[str, Dict[str, Any]]:
    receipts: Dict[str, Dict[str, Any]] = {}
    p = Path(store_dir)
    if not p.is_dir():
        return receipts
    for f in sorted(p.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        digest = payload.get("digest") or f.stem
        payload["digest"] = str(digest)
        receipts[str(digest)] = payload
    return receipts


def _git(repo_root: str, *args: str, timeout: int = 15) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=repo_root,
            capture_output=True, text=True, timeout=timeout,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _rev_parse_commit(repo_root: str, ref: str) -> Optional[str]:
    sha = _git(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return sha if sha and SHA_RE.match(sha) else None


def _commit_parent(repo_root: str, sha: str) -> Optional[str]:
    line = _git(repo_root, "rev-list", "--parents", "-n", "1", sha)
    parts = line.split()
    return parts[1] if len(parts) > 1 else None


def _commit_files(repo_root: str, sha: str) -> Set[str]:
    out = _git(repo_root, "diff-tree", "--no-commit-id", "--name-only",
               "-r", sha)
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def _receipt_digest_of(payload: Dict[str, Any]) -> Optional[str]:
    d = payload.get("digest")
    return str(d) if isinstance(d, str) and d else None


def _scope_digest_of(receipt: Dict[str, Any]) -> Optional[str]:
    lineage = receipt.get("lineage") or {}
    for key in ("scope_receipt_digest",):
        v = lineage.get(key)
        if isinstance(v, str) and v:
            return v
    v = receipt.get("pre_receipt_digest")
    return v if isinstance(v, str) and v else None


def _head_sha_of(receipt: Dict[str, Any]) -> Optional[str]:
    lineage = receipt.get("lineage") or {}
    v = lineage.get("head_sha")
    return v if isinstance(v, str) and v else None


def _receipt_files(receipt: Dict[str, Any]) -> Set[str]:
    files = receipt.get("changed_files") or []
    out: Set[str] = set()
    for f in files:
        if isinstance(f, str) and f:
            out.add(f)
            out.add(os.path.basename(f))
            out.add(f.replace("\\", "/"))
    return {x for x in out if x}


def _match_commit_for_receipt(
    repo_root: str,
    receipt: Dict[str, Any],
    records: List[Any],
) -> Tuple[Optional[str], str, List[str]]:
    """Resolve the commit a diff receipt became.

    Confidence ladder (fail-closed, disclosed):
      high   — ``diff_identity.target`` IS a commit sha, or a commit is a
               direct child of ``lineage.head_sha`` and touches a receipt
               file.
      medium — a commit's file set covers all receipt files.
    Returns (sha, matched_via, candidate_shas).
    """
    identity = receipt.get("diff_identity") or {}
    target = str(identity.get("target") or "")
    if SHA_RE.match(target):
        sha = _rev_parse_commit(repo_root, target)
        if sha:
            return sha, "target", [sha]

    rfiles = _receipt_files(receipt)
    head = _head_sha_of(receipt)
    candidates: List[str] = []
    for rec in records:
        rec_files = {f.replace("\\", "/") for f in (rec.files or [])}
        rec_basenames = {os.path.basename(f) for f in rec_files}
        overlap = bool(rec_files & rfiles) or bool(rec_basenames & rfiles)
        if not overlap:
            continue
        if head:
            parent = _commit_parent(repo_root, rec.sha)
            if parent == head:
                return rec.sha, "head_child", [rec.sha]
        candidates.append(rec.sha)

    if rfiles:
        for rec in records:
            rec_files = {f.replace("\\", "/") for f in (rec.files or [])}
            rec_basenames = {os.path.basename(f) for f in rec_files}
            rel_rfiles = {os.path.basename(f) for f in rfiles}
            if rel_rfiles and rel_rfiles <= rec_basenames:
                return rec.sha, "file_subset", candidates[:5]
    return None, "none", candidates[:5]


def _verdict_for(repo_root: str, sha: str,
                 records: List[Any]) -> Dict[str, Any]:
    from sot_graph.outcome import label_outcomes, commit_verdict
    outcomes = label_outcomes(records)
    for o in outcomes:
        if o.sha == sha:
            v = dict(commit_verdict(o))
            v["kind"] = "commit_verdict"
            return v
    return {
        "kind": "commit_verdict", "sha": sha, "verdict": "unknown",
        "reason_codes": ["not_in_collected_window"],
    }


def build_chain(
    repo_root: str,
    ref: str,
    *,
    store_dir: Optional[str] = None,
    limit: int = 400,
    db: Any = None,
) -> Dict[str, Any]:
    """Assemble the dossier for one anchor ref. Never guesses links."""
    store_dir = store_dir or _store_dir(repo_root)
    receipts = _load_store(store_dir)
    chain: Dict[str, Any] = {
        "kind": "lineage_chain",
        "anchor": None,
        "scope_receipts": [],
        "diff_receipts": [],
        "commit": None,
        "outcome": None,
        "links": {
            "scope_to_diff": False,
            "diff_to_commit": False,
            "commit_to_outcome": False,
        },
        "missing": [],
        "complete": False,
    }

    # --- resolve anchor ---------------------------------------------------
    anchor_receipt: Optional[Dict[str, Any]] = None
    ref_s = str(ref).strip()
    if ref_s in receipts:
        anchor_receipt = receipts[ref_s]
    else:
        hits = [d for d in receipts if d.startswith(ref_s)]
        if len(hits) == 1:
            anchor_receipt = receipts[hits[0]]
        elif Path(ref_s).is_file():
            try:
                payload = json.loads(Path(ref_s).read_text(encoding="utf-8"))
                anchor_receipt = payload
            except (OSError, json.JSONDecodeError):
                pass

    anchor_sha: Optional[str] = None
    if anchor_receipt is None:
        anchor_sha = _rev_parse_commit(repo_root, ref_s)
        if anchor_sha is None:
            chain["error"] = (
                f"unresolvable ref {ref_s!r}: not a receipt digest and "
                "not a commit")
            return chain
        chain["anchor"] = {"kind": "commit", "id": anchor_sha}
    else:
        chain["anchor"] = {
            "kind": anchor_receipt.get("kind", "receipt"),
            "id": _receipt_digest_of(anchor_receipt) or ref_s,
        }

    # --- collect history once (used for matching AND verdict) -------------
    from sot_graph.outcome import collect_commit_records
    records = collect_commit_records(repo_root, limit=limit, db=db)

    diff_receipts: List[Dict[str, Any]] = []
    scope_digests: List[str] = []
    commit_sha: Optional[str] = anchor_sha
    matched_via = "anchor"

    if anchor_receipt is not None:
        kind = anchor_receipt.get("kind")
        if kind == "diff_impact":
            diff_receipts = [anchor_receipt]
            sd = _scope_digest_of(anchor_receipt)
            if sd:
                scope_digests.append(sd)
            if commit_sha is None:
                commit_sha, matched_via, _ = _match_commit_for_receipt(
                    repo_root, anchor_receipt, records)
        elif kind == "scope":
            sd = _receipt_digest_of(anchor_receipt)
            if sd:
                scope_digests.append(sd)
            for d, r in receipts.items():
                if r.get("kind") == "diff_impact" and _scope_digest_of(r) == sd:
                    diff_receipts.append(r)
            for r in diff_receipts:
                sha, _mv, _c = _match_commit_for_receipt(
                    repo_root, r, records)
                if sha:
                    commit_sha = sha
                    matched_via = _mv
                    break
        else:  # commit_verdict / reconcile / audit receipt — anchor as data
            if kind == "commit_verdict" and anchor_receipt.get("sha"):
                commit_sha = str(anchor_receipt["sha"])
                matched_via = "anchor"

    if anchor_sha is not None:
        # commit anchor: find diff receipts that plausibly produced it
        cfiles = _commit_files(repo_root, anchor_sha)
        c_basenames = {os.path.basename(f) for f in cfiles}
        parent = _commit_parent(repo_root, anchor_sha)
        for _d, r in receipts.items():
            if r.get("kind") != "diff_impact":
                continue
            rfiles = _receipt_files(r)
            rel_rfiles = {os.path.basename(f) for f in rfiles}
            head_match = parent is not None and _head_sha_of(r) == parent
            subset = bool(rel_rfiles) and rel_rfiles <= c_basenames
            if head_match or subset:
                diff_receipts.append(r)
                sd = _scope_digest_of(r)
                if sd and sd not in scope_digests:
                    scope_digests.append(sd)

    # --- materialize links -------------------------------------------------
    chain["diff_receipts"] = [
        {"digest": _receipt_digest_of(r), "target":
         (r.get("diff_identity") or {}).get("target")}
        for r in diff_receipts
    ]
    scope_rows = []
    for sd in scope_digests:
        scope_rows.append({
            "digest": sd,
            "resolved": sd in receipts,
        })
    chain["scope_receipts"] = scope_rows

    if commit_sha:
        chain["commit"] = {"sha": commit_sha, "matched_via": matched_via}
        chain["outcome"] = _verdict_for(repo_root, commit_sha, records)

    chain["links"]["scope_to_diff"] = bool(
        diff_receipts and scope_digests
        and all(r["resolved"] for r in scope_rows))
    chain["links"]["diff_to_commit"] = bool(diff_receipts and commit_sha)
    chain["links"]["commit_to_outcome"] = bool(
        commit_sha and chain["outcome"])

    if not scope_rows:
        chain["missing"].append(
            "scope_to_diff: no pre_receipt_digest/lineage link — mint "
            "diff-impact with --pre-receipt to bind a scope receipt")
    if not diff_receipts:
        chain["missing"].append(
            "diff_to_commit: no diff_impact receipt matched")
    if not commit_sha:
        chain["missing"].append(
            "diff_to_commit: no commit matched the receipt")
    if commit_sha and not chain["outcome"]:
        chain["missing"].append("commit_to_outcome: verdict not computed")

    chain["complete"] = all(chain["links"].values())
    return chain


def render_chain(chain: Dict[str, Any]) -> str:
    """Human dossier for `receipt chain`."""
    lines = ["# Lineage dossier", ""]
    a = chain.get("anchor") or {}
    lines.append(f"**anchor:** {a.get('kind','?')} `{a.get('id','?')}`")
    lines.append("")
    if chain.get("error"):
        lines.append(f"❌ {chain['error']}")
        return "\n".join(lines)

    if chain["scope_receipts"]:
        for s in chain["scope_receipts"]:
            mark = "✓" if s["resolved"] else "✗ (not in store)"
            lines.append(f"- scope  `{s['digest'][:12]}` {mark}")
    else:
        lines.append("- scope  — none linked")
    for r in chain["diff_receipts"]:
        lines.append(f"- diff   `{(r['digest'] or '?')[:12]}` "
                     f"target={r.get('target') or 'worktree'}")
    if not chain["diff_receipts"]:
        lines.append("- diff   — none matched")
    c = chain.get("commit")
    if c:
        lines.append(f"- commit `{c['sha'][:12]}` (via {c['matched_via']})")
    else:
        lines.append("- commit — none matched")
    o = chain.get("outcome")
    if o:
        icon = {"clear-fault": "✅", "still-hot": "🔥",
                "unknown": "❓"}.get(o.get("verdict"), "❓")
        lines.append(
            f"- verdict {icon} **{o.get('verdict')}**"
            f" ({o.get('outcome', '?')})")
    else:
        lines.append("- verdict — none")

    lines.append("")
    links = chain["links"]
    lines.append("**links:** scope→diff "
                 + ("✓" if links["scope_to_diff"] else "✗")
                 + " | diff→commit " + ("✓" if links["diff_to_commit"] else "✗")
                 + " | commit→outcome "
                 + ("✓" if links["commit_to_outcome"] else "✗"))
    lines.append("")
    lines.append("**chain complete:** " + ("✅ yes" if chain["complete"]
                                           else "❌ no"))
    for m in chain.get("missing", []):
        lines.append(f"- {m}")
    return "\n".join(lines)
