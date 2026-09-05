#!/usr/bin/env python3
"""Shared CLI for the SG-201 / SG-202 exit-gate measurements (PILOT scope).

Subcommands
-----------
sg202      Task-sufficiency measurement (issue #9 exit gate).
sg201      Repo-map fixture/vendor contamination over the ACTUAL rendered
           map text (issue #8 exit gate, contamination half).
landmark-materials   Generate the human reviewer worksheet for the SG-201
                     landmark precision@20 study (renders the top of the
                     actual map into a CSV template).
landmark-aggregate   Aggregate filled reviewer CSVs with strict validation;
                     PENDING_HUMAN_EVIDENCE until real reviewer files exist.
all        sg202 + sg201 (one index build each; no shared state).

Exit codes (gate semantics, fail-closed): 0 = measured PASS;
1 = measured FAIL / oracle-validation failure; 2 = insufficient sampling
or not-evaluable (never a pass). Non-gate runs (--no-gate) exit 0 and
report the verdict.

Nothing here mutates production code or the shared .sot database.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.exit_gates.common import (  # noqa: E402
    build_temp_index,
    close_temp_index,
    parse_rendered_map,
    write_report,
)
from evaluation.exit_gates import sg201_contamination as sg201  # noqa: E402
from evaluation.exit_gates import sg202_task_sufficiency as sg202  # noqa: E402

LANDMARK_ROWS = 20
LANDMARK_COLUMNS = ("rank", "path", "symbol_stub", "verdict", "reviewer_note",
                    "reviewer_name", "attestation", "reviewed_at")
VALID_VERDICTS = {"landmark", "not_landmark", "unsure"}
MIN_REVIEWERS = 3          # protocol minimum before the gate MAY be closed
ATTESTATION_PREFIX = "I personally reviewed"


def _gate_exit_code(report) -> int:
    gate = report.get("gate", {})
    verdict = gate.get("verdict")
    if verdict == "PASS":
        return 0
    if verdict in ("INSUFFICIENT_SAMPLING", "NOT_EVALUABLE"):
        return 2
    return 1


def cmd_sg202(args) -> int:
    report = sg202.run_task_sufficiency(
        args.root, seed=args.seed, limit=args.limit,
        budget_tokens=args.budget_tokens, min_tasks=args.min_tasks,
        workers=args.workers)
    paths = write_report(args.report_dir, "sg202_task_sufficiency",
                         report, sg202.render_markdown(report))
    print(f"[sg202] verdict={report['gate']['verdict']} "
          f"metric={report['gate']['metric']} "
          f"denominator={report['gate']['denominator']} "
          f"all_sampled={report['metrics']['task_sufficiency_all_sampled']}")
    print(f"[sg202] report: {paths['json']} | {paths['markdown']}")
    return _gate_exit_code(report) if args.gate else 0


def cmd_sg201(args) -> int:
    report = sg201.run_contamination(
        args.root, budgets=tuple(args.budgets), min_symbols=args.min_symbols,
        workers=args.workers)
    paths = write_report(args.report_dir, "sg201_map_contamination",
                         report, sg201.render_markdown(report))
    print(f"[sg201] verdict={report['gate']['verdict']} "
          f"metric={report['gate']['metric_percent']}% "
          f"(fraction {report['gate']['metric']} vs floor 0.02) "
          f"denominator={report['gate']['denominator']}")
    print(f"[sg201] report: {paths['json']} | {paths['markdown']}")
    return _gate_exit_code(report) if args.gate else 0


def cmd_landmark_materials(args) -> int:
    import hashlib

    db, tmp = build_temp_index(args.root, workers=args.workers)
    try:
        from sot_graph.repo_map import build_repo_map

        result = build_repo_map(db.conn, root=str(Path(args.root).resolve()),
                                max_tokens=args.budget_tokens)
    finally:
        close_temp_index(db, tmp)
    rendered = parse_rendered_map(result["rendered"])
    rows = []
    for i, path in enumerate(rendered.files[:LANDMARK_ROWS], 1):
        stubs = "; ".join(rendered.file_symbols[path][:3])
        rows.append({"rank": i, "path": path, "symbol_stub": stubs,
                     "verdict": "", "reviewer_note": "",
                     "reviewer_name": "", "attestation": "",
                     "reviewed_at": ""})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LANDMARK_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "budget_tokens": args.budget_tokens,
        "worksheet_sha256": hashlib.sha256(out.read_bytes()).hexdigest()[:16],
        "rows": [{"rank": r["rank"], "path": r["path"]} for r in rows],
        "note": "reviewer CSVs are validated against this manifest "
                "(rank set, unique paths); a filled CSV without a matching "
                "manifest is invalid",
    }
    (out.parent / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[landmark] worksheet with {len(rows)} rows (top of rendered map, "
          f"budget {args.budget_tokens}): {out}")
    print(f"[landmark] manifest: {out.parent / 'manifest.json'}")
    print("[landmark] protocol: plan/sg201-landmark-study-protocol.md "
          "(human evidence REQUIRED; the aggregator NEVER closes the human "
          "gate automatically — acceptance stays PENDING_MANUAL_VERIFICATION)")
    return 0


def _validate_reviewer_csv(ws: Path, manifest_rows) -> tuple:
    """Return (rows, problem) — problem is None when structurally valid."""
    with ws.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != LANDMARK_ROWS:
        return rows, f"expected {LANDMARK_ROWS} rows, got {len(rows)}"
    for r in rows:
        if r.get("verdict") not in VALID_VERDICTS:
            return rows, f"invalid/blank verdict at rank {r.get('rank')}"
        if not str(r.get("reviewer_name", "")).strip():
            return rows, f"missing reviewer_name at rank {r.get('rank')}"
        attest = str(r.get("attestation", "")).strip()
        if not attest.startswith(ATTESTATION_PREFIX):
            return rows, (f"attestation must start with {ATTESTATION_PREFIX!r} "
                          f"at rank {r.get('rank')}")
        if not str(r.get("reviewed_at", "")).strip():
            return rows, f"missing reviewed_at at rank {r.get('rank')}"
    ranks = [int(r["rank"]) for r in rows]
    if sorted(ranks) != list(range(1, LANDMARK_ROWS + 1)):
        return rows, "ranks must be exactly 1..20 without duplicates"
    paths = [r["path"] for r in rows]
    if len(set(paths)) != LANDMARK_ROWS:
        return rows, "duplicate paths across rows"
    expected = {m["rank"]: m["path"] for m in manifest_rows}
    if {int(r["rank"]): r["path"] for r in rows} != expected:
        return rows, "rows do not match the generated worksheet manifest"
    return rows, None


def cmd_landmark_aggregate(args) -> int:
    """Aggregate reviewer CSVs. STRICT + FAIL-CLOSED, and it NEVER closes
    the human gate by itself: scores are informational and
    ``acceptance_status`` stays PENDING_MANUAL_VERIFICATION until a
    maintainer explicitly adjudicates (CSVs alone are
    supplied-not-verified evidence)."""
    ws_dir = Path(args.dir)
    manifest_path = ws_dir / "manifest.json"
    worksheets = sorted(ws_dir.glob("reviewer-*.csv"))
    if not worksheets or not manifest_path.exists():
        print("[landmark] status=PENDING_HUMAN_EVIDENCE "
              "(no reviewer-*.csv / manifest.json found; human study not performed)")
        return 2
    manifest = json.loads(manifest_path.read_text())
    manifest_rows = manifest.get("rows", [])
    per_reviewer = []
    problems = []
    for ws in worksheets:
        rows, problem = _validate_reviewer_csv(ws, manifest_rows)
        if problem:
            problems.append(f"{ws.name}: {problem}")
            continue
        unsure = sum(1 for r in rows if r["verdict"] == "unsure")
        if unsure > LANDMARK_ROWS * 0.2:
            problems.append(f"{ws.name}: {unsure} unsure rows (>20%) — review invalid")
            continue
        landmarks = sum(1 for r in rows if r["verdict"] == "landmark")
        # precision@20 uses the FULL denominator: unsure rows are explicit
        # non-positives until adjudicated (no landmarks/scored inflation).
        per_reviewer.append({
            "reviewer": ws.stem.removeprefix("reviewer-"),
            "precision@20": round(landmarks / LANDMARK_ROWS, 4),
            "landmarks": landmarks, "denominator": LANDMARK_ROWS,
            "unsure": unsure,
        })
    if problems:
        print("[landmark] status=INVALID_RESULTS (strict validation failed):")
        for p in problems:
            print(f"  - {p}")
        return 1
    mean = round(sum(r["precision@20"] for r in per_reviewer) / len(per_reviewer), 4)
    score_verdict = "PASS" if mean >= 0.90 else "FAIL"
    enough_reviewers = len(per_reviewer) >= MIN_REVIEWERS
    # The human gate is NEVER closed automatically from CSVs.
    acceptance_status = "PENDING_MANUAL_VERIFICATION"
    report = {
        "status": "COMPLETE",
        "acceptance_status": acceptance_status,
        "human_evidence": "supplied_not_verified",
        "score_informational_only": True,
        "per_reviewer": per_reviewer,
        "mean_precision@20": mean,
        "floor": 0.90,
        "informational_verdict": score_verdict,
        "reviewers": len(per_reviewer),
        "min_reviewers": MIN_REVIEWERS,
        "min_reviewers_met": enough_reviewers,
        "manifest_worksheet_sha256": manifest.get("worksheet_sha256"),
    }
    paths = write_report(args.report_dir, "sg201_landmark_study", report,
                         "# SG-201 landmark study (human)\n\n"
                         f"acceptance: **{acceptance_status}** (aggregator never "
                         "closes the human gate)\n"
                         f"reviewers: {len(per_reviewer)} "
                         f"(min {MIN_REVIEWERS}, met: {enough_reviewers}); "
                         f"mean precision@20 (landmarks/20): {mean}; "
                         f"informational verdict: {score_verdict}\n")
    print(f"[landmark] acceptance_status={acceptance_status} "
          f"informational_verdict={score_verdict} mean_precision@20={mean} "
          f"reviewers={len(per_reviewer)}/{MIN_REVIEWERS}")
    print(f"[landmark] report: {paths['json']}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--root", default=".", help="repo root to index (temp DB)")
        sp.add_argument("--workers", type=int, default=4)
        sp.add_argument("--report-dir", default="benchmarks/exit_gates")
        sp.add_argument("--gate", action="store_true",
                        help="exit nonzero unless the gate measured PASS")

    g202 = sub.add_parser("sg202", help="task-sufficiency measurement")
    common(g202)
    g202.add_argument("--seed", type=int, default=20260905)
    g202.add_argument("--limit", type=int, default=40)
    g202.add_argument("--budget-tokens", type=int, default=sg202.DEFAULT_BUDGET_TOKENS)
    g202.add_argument("--min-tasks", type=int, default=sg202.DEFAULT_MIN_TASKS)
    g202.set_defaults(func=cmd_sg202)

    g201 = sub.add_parser("sg201", help="rendered-map contamination measurement")
    common(g201)
    g201.add_argument("--budgets", type=int, nargs="+", default=list(sg201.DEFAULT_BUDGETS))
    g201.add_argument("--min-symbols", type=int, default=sg201.DEFAULT_MIN_SYMBOLS)
    g201.set_defaults(func=cmd_sg201)

    mat = sub.add_parser("landmark-materials", help="generate reviewer worksheet CSV")
    mat.add_argument("--root", default=".")
    mat.add_argument("--workers", type=int, default=4)
    mat.add_argument("--budget-tokens", type=int, default=1024)
    mat.add_argument("--out", default="benchmarks/exit_gates/landmark/worksheet.csv")
    mat.set_defaults(func=cmd_landmark_materials)

    agg = sub.add_parser("landmark-aggregate", help="aggregate filled reviewer CSVs")
    agg.add_argument("--dir", default="benchmarks/exit_gates/landmark")
    agg.add_argument("--report-dir", default="benchmarks/exit_gates")
    agg.set_defaults(func=cmd_landmark_aggregate)

    al = sub.add_parser("all", help="sg202 + sg201")
    common(al)
    al.add_argument("--seed", type=int, default=20260905)
    al.add_argument("--limit", type=int, default=40)
    al.add_argument("--budget-tokens", type=int, default=sg202.DEFAULT_BUDGET_TOKENS)
    al.add_argument("--min-tasks", type=int, default=sg202.DEFAULT_MIN_TASKS)
    al.add_argument("--budgets", type=int, nargs="+", default=list(sg201.DEFAULT_BUDGETS))
    al.add_argument("--min-symbols", type=int, default=sg201.DEFAULT_MIN_SYMBOLS)

    def cmd_all(args):
        rc1, rc2 = cmd_sg202(args), cmd_sg201(args)
        return max(rc1, rc2)

    al.set_defaults(func=cmd_all)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
