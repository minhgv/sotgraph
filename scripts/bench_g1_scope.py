#!/usr/bin/env python3
"""bench_g1_scope.py — G1 replay: multi-target scope-receipt vs real commits.

Measures whether a task-level scope receipt (W1 ``scope_receipt_multi``)
predicts the file surface a real change actually touched. For each sampled
commit with ≥2 touched symbols:

    targets   = commit.touched_symbols (cap 8)
    predicted = scope_receipt_multi(targets).affected_files  (union)
    actual    = commit.files (the change's true footprint)

Metrics per commit:
    recall_union       = |pred ∩ actual| / |actual|
    recall_best_single = max over targets of single-target recall
    precision          = |pred ∩ actual| / |pred|   (noise floor —
                         blast radius legitimately exceeds the edit set)

Pass bars (blueprint W1): recall_union >= recall_best_single for every
commit (union is a superset by construction — this verifies the merge
machinery), and precision drop vs best single <= 0.10 absolute.

Honest limits (recorded, not hidden):
  - the graph indexes CURRENT state; old commits' symbols may have moved
    or been deleted (per-target resolution stats are reported)
  - affected_files trivially contains the target's own file — recall has
    a structural floor; precision is the informative axis for noise.

Usage:
  python3 scripts/bench_g1_scope.py [--limit 400] [--sample 40]
      [--report benchmarks/three_gates/g1_report.json] [--gate]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph.outcome import collect_commit_records  # noqa: E402

REPORT_PATH = _REPO / "benchmarks" / "three_gates" / "g1_report.json"
MAX_TARGETS = 8          # mirror the MCP cap — union cost stays bounded
PRECISION_DROP_BAR = 0.10


def _eval_commit(
    db: Any, root: str, rec: Any,
) -> Optional[Dict[str, Any]]:
    """One replay task: multi-scope over the commit's touched symbols."""
    from sot_graph.assurance.receipts import scope_receipt_multi

    targets = list(dict.fromkeys(rec.touched_symbols))[:MAX_TARGETS]
    if len(targets) < 2:
        return None
    # affected_files are absolute graph paths; commit files are
    # repo-relative — normalize both to repo-relative before intersecting.
    root_n = str(Path(root).resolve()) + "/"
    def rel(p: str) -> str:
        return p[len(root_n):] if p.startswith(root_n) else p
    changed = {rel(f) for f in rec.files}
    if not changed:
        return None

    multi = scope_receipt_multi(db, root, targets)
    pred_union = {rel(f) for f in multi["affected_files"]}
    # per_target carries each sub-receipt's affected_files list — the
    # best-single baseline comes from the same multi call (no re-run).
    per_target = multi["per_target"]

    best_single_recall = 0.0
    best_single_pred = 0
    best_single_inter = 0
    for t in targets:
        if per_target[t]["identity_status"] != "UNIQUE":
            continue
        spred = {rel(f) for f in per_target[t]["affected_files"]}
        hit = len(spred & changed)
        if hit / len(changed) > best_single_recall:
            best_single_recall = hit / len(changed)
            best_single_pred = len(spred)
            best_single_inter = hit

    inter = len(pred_union & changed)
    return {
        "sha": rec.short_sha,
        "subject": rec.subject,
        "risk_level": rec.risk_level,
        "targets": targets,
        "resolved_targets": sum(
            1 for t in targets
            if per_target[t]["identity_status"] == "UNIQUE"),
        "changed_files": len(changed),
        "pred_union": len(pred_union),
        "pred_best_single": best_single_pred,
        "recall_union": round(inter / len(changed), 4),
        "recall_best_single": round(best_single_recall, 4),
        "precision_union": round(inter / len(pred_union), 4)
        if pred_union else 0.0,
        "precision_best_single": round(
            best_single_inter / best_single_pred, 4)
        if best_single_pred else None,
        "union_ge_best_single": inter >= 0 and (
            inter / len(changed)) >= best_single_recall - 1e-9,
        "assurance_status": multi["assurance"]["status"],
        "partial_targets": multi["assurance_facts"]["partial_targets"],
    }


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0}
    def mean(k: str) -> float:
        vals = [r[k] for r in rows if r[k] is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0
    return {
        "n": n,
        "mean_recall_union": mean("recall_union"),
        "mean_recall_best_single": mean("recall_best_single"),
        "mean_precision_union": mean("precision_union"),
        "mean_precision_best_single": mean("precision_best_single"),
        "union_ge_best_rate": round(
            sum(1 for r in rows if r["union_ge_best_single"]) / n, 4),
        "precision_drop": round(
            mean("precision_best_single") - mean("precision_union"), 4),
        "partial_resolution_rate": round(
            sum(1 for r in rows if r["partial_targets"]) / n, 4),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="G1 replay: multi-target scope vs real commits")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--sample", type=int, default=40,
                    help="max commits evaluated (with >=2 touched symbols)")
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--root", default=str(_REPO))
    ap.add_argument("--gate", action="store_true")
    args = ap.parse_args(argv)

    db_file = Path(args.root) / ".sot" / "sot.db"
    if not db_file.is_file():
        print(f"❌ no index at {db_file} — run `sotgraph reconcile` first",
              file=sys.stderr)
        return 2
    from sot_graph.db import Database

    # Read-write like the CLI: scope receipts record generation-scoped
    # evidence invalidation into the ledger (designed side-effect).
    db = Database(str(db_file))
    try:
        records = collect_commit_records(args.root, limit=args.limit, db=db)
        candidates = [r for r in records if len(set(r.touched_symbols)) >= 2
                      and r.files][: args.sample]
        rows: List[Dict[str, Any]] = []
        for rec in candidates:
            row = _eval_commit(db, args.root, rec)
            if row:
                rows.append(row)
                print(f"  {row['sha']} recall={row['recall_union']:.0%} "
                      f"(best single {row['recall_best_single']:.0%}) "
                      f"prec={row['precision_union']:.0%} "
                      f"targets={row['resolved_targets']}/{len(row['targets'])}")
    finally:
        db.close()

    agg = aggregate(rows)
    checks = {
        "union_covers_best_single": {
            "passed": bool(rows) and agg["union_ge_best_rate"] == 1.0,
            "detail": f"{agg.get('union_ge_best_rate')}",
        },
        "precision_drop_within_bar": {
            "passed": bool(rows)
            and agg["precision_drop"] <= PRECISION_DROP_BAR + 1e-9,
            "detail": f"drop={agg.get('precision_drop')} "
                      f"(bar {PRECISION_DROP_BAR})",
        },
        "sample_size": {"passed": len(rows) >= min(10, args.sample),
                        "detail": f"{len(rows)} commits evaluated"},
    }
    report = {
        "benchmark": "g1-scope-replay",
        "environment": {"python": platform.python_version()},
        "params": {"limit": args.limit, "sample": args.sample,
                   "max_targets": MAX_TARGETS},
        "honest_limits": [
            "graph reflects CURRENT state — past symbols may be stale",
            "affected_files structurally contains each target's own file",
            "precision is informational: blast radius exceeds edit set",
        ],
        "rows": rows,
        "aggregate": agg,
        "checks": checks,
    }
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n",
                   encoding="utf-8")
    print(f"\nG1 replay: {agg}")
    for name, chk in checks.items():
        print(f"  {name}: {'PASS' if chk['passed'] else 'FAIL'} "
              f"({chk['detail']})")
    print(f"  report: {out}")
    if args.gate:
        return 0 if all(c["passed"] for c in checks.values()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
