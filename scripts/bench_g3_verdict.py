#!/usr/bin/env python3
"""bench_g3_verdict.py — G3 replay: commit-verdict precision vs truth.

For every collected commit the W3 verdict maps its labeled outcome to
``clear-fault | still-hot | unknown``. Ground truth for "still-hot"
precision comes from two sources:

  * the labeler's own adverse labels (``fixup`` + ``reverted``) — the
    upper bound, since the verdict consumes exactly those signals;
  * the W0 hand-labeled sample — the honest external check.

Pass bars (blueprint W3): still-hot precision ≥ 0.8 vs adverse labels;
every emitted verdict carries ≥1 reason_code; commits without enough
evidence yield ``unknown`` (never a guess).

Usage:
  python3 scripts/bench_g3_verdict.py [--limit 400]
      [--report benchmarks/three_gates/g3_report.json] [--gate]
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

REPORT_PATH = _REPO / "benchmarks" / "three_gates" / "g3_report.json"
HAND_LABELS = _REPO / "benchmarks" / "three_gates" / "hand_labels.json"
STILL_HOT_BAR = 0.8


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="G3 replay: commit-verdict precision")
    ap.add_argument("--limit", type=int, default=400)
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
    from sot_graph.outcome import (
        ADVERSE_OUTCOMES, collect_commit_records, commit_verdict,
        label_outcomes,
    )

    db = Database(str(db_file), read_only=True)
    try:
        records = collect_commit_records(args.root, limit=args.limit, db=db)
        outcomes = label_outcomes(records)
    finally:
        db.close()

    verdicts = [commit_verdict(o) for o in outcomes]

    # Precision vs the labeler's own adverse labels (upper bound).
    adverse_truth = {o.sha for o in outcomes if o.outcome in ADVERSE_OUTCOMES}
    still_hot = [v for v in verdicts if v["verdict"] == "still-hot"]
    tp = sum(1 for v in still_hot if v["sha"] in adverse_truth)
    precision_labeler = round(tp / len(still_hot), 4) if still_hot else None

    # Precision vs hand labels (external truth): map hand labels onto
    # adverse/non-adverse the same way the labeler does.
    hand_precision = None
    hand_rows: List[Dict[str, Any]] = []
    if HAND_LABELS.is_file():
        hand = json.loads(HAND_LABELS.read_text(encoding="utf-8"))
        # {"sotgraph": {"<short_sha>": "<outcome_label>"}, ...}
        by_sha = {
            short: lab
            for repo_map in (v for k, v in hand.items()
                             if isinstance(v, dict))
            for short, lab in repo_map.items()
        }
        v_by_short = {v["short_sha"]: v for v in verdicts}
        for short, lab in by_sha.items():
            v = v_by_short.get(short)
            if v is None:
                hand_rows.append({"sha": short, "expected": lab,
                                  "actual_verdict": None})
                continue
            expected_adverse = lab in ADVERSE_OUTCOMES
            predicted_adverse = v["verdict"] == "still-hot"
            hand_rows.append({
                "sha": short, "expected": lab,
                "actual_verdict": v["verdict"],
                "match": expected_adverse == predicted_adverse,
            })
        predicted = [r for r in hand_rows if r["actual_verdict"]
                     == "still-hot"]
        tp_h = sum(1 for r in predicted if r["expected"] in ADVERSE_OUTCOMES)
        hand_precision = (round(tp_h / len(predicted), 4)
                          if predicted else None)

    # Fail-closed contract: every verdict has ≥1 reason code.
    no_reason = sum(1 for v in verdicts if not v["reason_codes"])

    dist = {k: 0 for k in ("clear-fault", "still-hot", "unknown")}
    for v in verdicts:
        dist[v["verdict"]] = dist.get(v["verdict"], 0) + 1

    checks = {
        "still_hot_precision_vs_labels": {
            "passed": precision_labeler is not None
            and precision_labeler >= STILL_HOT_BAR,
            "detail": f"{precision_labeler} (bar {STILL_HOT_BAR})",
        },
        "still_hot_precision_vs_hand": {
            "passed": hand_precision is not None
            and hand_precision >= STILL_HOT_BAR,
            "detail": f"{hand_precision} on {len(hand_rows)} hand labels",
        },
        "every_verdict_has_reason": {
            "passed": no_reason == 0,
            "detail": f"{no_reason} verdicts without reason_codes",
        },
    }
    report = {
        "benchmark": "g3-commit-verdict",
        "environment": {"python": platform.python_version()},
        "params": {"limit": args.limit},
        "verdict_distribution": dist,
        "n": len(verdicts),
        "still_hot_precision_vs_labels": precision_labeler,
        "still_hot_precision_vs_hand": hand_precision,
        "hand_rows": hand_rows,
        "checks": checks,
    }
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n",
                   encoding="utf-8")
    print(f"G3 verdicts over {len(verdicts)} commits: {dist}")
    print(f"  still-hot precision vs labels: {precision_labeler}")
    print(f"  still-hot precision vs hand : {hand_precision}")
    for name, chk in checks.items():
        print(f"  {name}: {'PASS' if chk['passed'] else 'FAIL'} "
              f"({chk['detail']})")
    print(f"  report: {out}")
    if args.gate:
        return 0 if all(c["passed"] for c in checks.values()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
