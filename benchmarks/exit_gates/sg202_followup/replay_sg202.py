#!/usr/bin/env python3
"""Independent SG202 reviewer replay: EXACT frozen task roster (default 90).

Read-only against the repo under test. Oracle helpers are used unmodified;
the pack under test is the CURRENT working tree of <root>/src/sot_graph.

Reproduce (from a sot-graph checkout with its environment):
    <python> replay_sg202.py --root . --output-dir /tmp/sg202-final-independent

The exact command, git HEAD, worktree digest, and all input SHA256s are
recorded inside the emitted replay.json under "provenance".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

BUDGET = 1500
CONTRACTS_CAP = 8
MAX_NODES = 50
MAX_BYTES = 65_536
GATE_FLOOR = 0.95
MIN_MEASURABLE = 30


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".",
                    help="repo root of the sot-graph checkout under test")
    ap.add_argument("--baseline", default=None,
                    help="frozen baseline report JSON (default: "
                         "<root>/benchmarks/exit_gates/sg202_task_sufficiency.json)")
    ap.add_argument("--output-dir", default=".",
                    help="directory for replay.json (default: cwd)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_dir = root / "src"
    for p in (str(root), str(src_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)

    from sot_graph.holdout.evaluator import (  # noqa: E402
        OracleConfig, extract_definitions, iter_python_files,
        resolve_direct_calls,
    )
    from evaluation.exit_gates.common import (  # noqa: E402
        build_temp_index, close_temp_index, normalize_rel, oracle_category,
        repo_provenance,
    )
    from evaluation.exit_gates.sg202_task_sufficiency import (  # noqa: E402
        _bare_names_from_fqn, _owner_chains, _relevant_test_files,
    )
    from sot_graph.pack import PackError, build_bundle, render_yaml  # noqa: E402
    from sot_graph.tokenizer import estimate_tokens  # noqa: E402
    try:
        import tiktoken
        ENC = tiktoken.get_encoding("cl100k_base")
    except Exception:
        ENC = None

    baseline_path = (Path(args.baseline) if args.baseline else
                     root / "benchmarks/exit_gates/sg202_task_sufficiency.json")
    baseline = json.loads(baseline_path.read_text())
    frozen_roster = [r["task"] for r in baseline["task_roster"]]
    baseline_outcome = {r["task"]: r["outcome"] for r in baseline["task_roster"]}
    print(f"frozen roster: {len(frozen_roster)} tasks; "
          f"baseline gate metric={baseline['gate']['metric']}")

    # --- provenance ---------------------------------------------------------
    try:
        git_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True,
            text=True, timeout=30).stdout.strip()
    except Exception:
        git_head = None
    fixture_path = root / "evaluation/exit_gates/fixtures/sg202_gt_subset.json"
    pack_path = root / "src/sot_graph/pack.py"
    command = (f"python replay_sg202.py --root {root} "
               f"--output-dir {Path(args.output_dir).resolve()}")
    provenance = {
        "command": command,
        "git_head": git_head,
        "repo_provenance": repo_provenance(str(root)),
        "baseline_report_sha256": sha256_file(baseline_path),
        "baseline_report_path": str(baseline_path),
        "pack_source_sha256": sha256_file(pack_path),
        "oracle_fixture_sha256": (sha256_file(fixture_path)
                                  if fixture_path.exists() else None),
        "params": {
            "budget_tokens": BUDGET, "contracts_cap": CONTRACTS_CAP,
            "max_nodes": MAX_NODES, "max_bytes": MAX_BYTES,
            "max_hops": 2, "workers": args.workers,
            "gate_floor": GATE_FLOOR, "min_measurable": MIN_MEASURABLE,
        },
        "roster_source": "frozen baseline report task_roster (exact keys, "
                         "no re-sampling)",
    }

    # --- oracle facts (unmodified helpers, current tree) ---------------------
    config = OracleConfig()
    defs, parse_failures = extract_definitions(root, config)
    production_defs = [
        d for d in defs
        if d.path.startswith("src/") and not d.path.endswith("__init__.py")
        and oracle_category(d.path) == "production"
    ]
    production_rels = sorted({d.path for d in production_defs})
    owner_chains = _owner_chains(root, production_rels)
    test_rels = [
        rel for rel in iter_python_files(root, config)
        if (Path(rel).name.startswith("test_")
            or Path(rel).name.endswith("_test.py"))
        and oracle_category(rel) == "test"
    ]
    edges, unresolved_calls = resolve_direct_calls(root, defs, config)
    contracts_by_task = {}
    all_out_edges_by_task = {}
    for e in edges:
        pair = (e.callee_path, e.callee_name)
        lst = contracts_by_task.setdefault((e.caller_path, e.caller_name), [])
        if pair not in lst:
            lst.append(pair)
        all_out_edges_by_task.setdefault(
            (e.caller_path, e.caller_name), set()).add(pair)

    print(f"universe: production_defs={len(production_defs)} "
          f"test_rels={len(test_rels)} oracle_edges={len(edges)} "
          f"parse_failures={len(parse_failures)}")

    # --- per-task replay -----------------------------------------------------
    db, tmp_dir = build_temp_index(str(root), workers=args.workers)
    results = []
    try:
        for key in frozen_roster:
            tpath, tname = key.split("::", 1)
            expected_pairs = sorted(set(contracts_by_task.get((tpath, tname), [])))
            unmeasured = len(expected_pairs) > CONTRACTS_CAP
            measured = expected_pairs[:CONTRACTS_CAP]
            relevant_tests = _relevant_test_files(root, test_rels, tname)
            rec = {
                "task": key,
                "contracts_expected": len(expected_pairs),
                "relevant_test_files": len(relevant_tests),
                "corpus_drift": not (root / tpath).exists(),
                "full_success": False,
            }
            if unmeasured or not relevant_tests:
                rec["outcome"] = "ORACLE_UNMEASURABLE"
                rec["reasons"] = (["contracts_overflow"] if unmeasured else []) + \
                                 ([] if relevant_tests
                                  else ["no_relevant_test_in_corpus"])
                results.append(rec)
                continue
            try:
                bundle = build_bundle(db, str(root), tname, max_hops=2,
                                      max_nodes=MAX_NODES, max_bytes=MAX_BYTES,
                                      max_tokens=BUDGET)
            except PackError as exc:
                rec["outcome"] = "PACK_ERROR"
                rec["reasons"] = [f"{getattr(exc, 'code', 'PACK_ERROR')}: {exc}"]
                results.append(rec)
                continue

            target = bundle.get("target", {})
            expected_module = tpath[:-3] if tpath.endswith(".py") else tpath
            expected_module = expected_module.replace("/", ".")
            if expected_module.startswith("src."):
                expected_module = expected_module[len("src."):]
            chains = owner_chains.get((tpath, tname)) or {()}
            expected_fqns = {expected_module + "." + ".".join(c + (tname,))
                             for c in chains}
            fqn = str(target.get("fqn") or "")
            sym = str(target.get("symbol") or "")
            identity_ok = ((sym == tname or sym.endswith("." + tname))
                           and fqn in expected_fqns)
            src_text = target.get("full_source") or ""
            source_ok = bool(src_text) or bundle.get("accounting", {}).get(
                "target_source", {}).get("returned") == 1
            rec["target_ok"] = identity_ok and source_ok
            rec["identity_ok"] = identity_ok
            rec["src_chars"] = len(src_text)
            rec["ambiguous"] = (bundle.get("resolution", {}).get("status")
                                == "AMBIGUOUS_AUTO_RESOLVED")
            warnings = bundle.get("limits", {}).get("warnings", [])
            rec["src_truncated"] = any(
                "full_source truncated" in w or "target_source_oversize" in w
                or "source_read_bounded" in w for w in warnings)

            outbound = bundle.get("outbound_callees") or []
            out_ids = [(normalize_rel(str(e.get("relative_path", "")), str(root)),
                        _bare_names_from_fqn(str(e.get("fqn", ""))))
                       for e in outbound]
            missing, extra = [], 0
            oracle_all = all_out_edges_by_task.get((tpath, tname), set())
            for cpath, cname in measured:
                if not any(p == cpath and cname in names
                           for p, names in out_ids):
                    missing.append(f"{cpath}::{cname}")
            for p, names in out_ids:
                if not any(p == cp and cn in names for cp, cn in oracle_all):
                    extra += 1
            rec["contracts_returned"] = len(measured) - len(missing)
            rec["contracts_missing"] = missing
            rec["contracts_extra_unverified"] = extra
            contracts_ok = not missing

            relevant_set = set(relevant_tests)
            recv = [normalize_rel(str(e.get("relative_path", "")), str(root))
                    for e in (bundle.get("inbound_callers") or [])
                    if normalize_rel(str(e.get("relative_path", "")), str(root))
                    in relevant_set]
            rec["test_received"] = bool(recv)
            rec["test_receipt_files"] = sorted(set(recv))

            reported = int(bundle.get("limits", {}).get("tokens_estimate") or 0)
            rendered = render_yaml(bundle)
            recomputed = estimate_tokens(rendered)
            rec["tokens_reported"] = reported
            rec["tokens_recomputed"] = recomputed
            rec["render_bytes"] = len(rendered.encode("utf-8"))
            if ENC is not None:
                tik_raw = len(ENC.encode(rendered, disallowed_special=()))
                rec["tokens_tiktoken_raw"] = tik_raw
                rec["budget_gap_raw"] = tik_raw - recomputed
            rec["over_budget"] = max(reported, recomputed) > BUDGET

            rec["full_success"] = bool(rec["target_ok"] and contracts_ok
                                       and rec["test_received"]
                                       and not rec["over_budget"])
            if rec["full_success"]:
                rec["outcome"] = "FULL_SUCCESS"
            elif not rec["target_ok"]:
                rec["outcome"] = "MISSING_TARGET"
            elif not contracts_ok:
                rec["outcome"] = "MISSING_CONTRACTS"
            elif not rec["test_received"]:
                rec["outcome"] = "MISSING_TEST"
            else:
                rec["outcome"] = "OVER_BUDGET"
            results.append(rec)
    finally:
        close_temp_index(db, tmp_dir)

    # --- metrics, cohorts, counters -----------------------------------------
    attempted = len(results)
    measurable = [r for r in results if r["outcome"] != "ORACLE_UNMEASURABLE"]
    full = [r for r in measurable if r.get("full_success")]
    base_meas = {r["task"] for r in baseline["task_roster"]
                 if r["outcome"] != "ORACLE_UNMEASURABLE"}
    cur_meas = {r["task"] for r in results
                if r["outcome"] != "ORACLE_UNMEASURABLE"}
    by_task = {r["task"]: r for r in results}
    cohort_a = {t: by_task[t] for t in base_meas if t in by_task}
    full_a = sum(1 for r in cohort_a.values() if r.get("full_success"))

    gate_metric = round(len(full) / len(measurable), 4) if measurable else None
    gate = {
        "gate": f"sg202_task_sufficiency>={GATE_FLOOR}",
        "metric": gate_metric,
        "denominator": len(measurable),
        "min_denominator": MIN_MEASURABLE,
        "floor": GATE_FLOOR,
        "direction": "metric>=floor",
        "passed": bool(gate_metric is not None
                       and len(measurable) >= MIN_MEASURABLE
                       and gate_metric >= GATE_FLOOR),
        "verdict": ("PASS" if (gate_metric is not None
                               and len(measurable) >= MIN_MEASURABLE
                               and gate_metric >= GATE_FLOOR)
                    else ("INSUFFICIENT_SAMPLING" if len(measurable) < MIN_MEASURABLE
                          else "FAIL")),
    }

    summary = {
        "roster": len(frozen_roster),
        "attempted": attempted,
        "measurable": len(measurable),
        "full_success": len(full),
        "remaining_failures": len(measurable) - len(full),
        "sufficiency_measurable": gate_metric,
        "sufficiency_all": round(len(full) / attempted, 4) if attempted else None,
        "gate": gate,
        "outcome_counts": {},
        "corpus_drift": sum(1 for r in results if r.get("corpus_drift")),
        "over_budget": sum(1 for r in results if r.get("over_budget")),
        "tiktoken_gt_estimate": sum(1 for r in results
                                    if r.get("budget_gap_raw", 0) > 0),
        "max_tokens_recomputed": max((r.get("tokens_recomputed") or 0)
                                     for r in results),
        # HEURISTIC size labels only (chars are a proxy for tokens; a small
        # def is legitimately small). NOT definitive evidence of unusable
        # source; truncation disclosure flags are the definitive signals.
        "heuristic_full_success_thin_source_lt400chars": sum(
            1 for r in full if r.get("src_chars", 0) < 400),
        "full_success_src_truncated_flagged": sum(
            1 for r in full if r.get("src_truncated")),
        "heuristic_full_success_truncated_and_lt200chars": sum(
            1 for r in full if r.get("src_truncated")
            and r.get("src_chars", 0) < 200),
        "ambiguous_resolved": sum(1 for r in results if r.get("ambiguous")),
        "extra_unverified_contracts": sum(
            r.get("contracts_extra_unverified", 0) for r in results),
        "cohorts": {
            "baseline_measurable_cohort": {
                "n": len(cohort_a), "full_success": full_a,
                "sufficiency": (round(full_a / len(cohort_a), 4)
                                if cohort_a else None),
                "note": "exact baseline-measurable cohort, scored with "
                        "CURRENT pack+oracle on the current tree",
            },
            "current_measurable_cohort": {
                "n": len(cur_meas), "full_success": len(full),
                "sufficiency": gate_metric,
            },
        },
        "measurability_changes": (
            [{"task": t, "direction": "became_measurable",
              "current_relevant_test_files": by_task[t].get("relevant_test_files"),
              "attribution": "new test-file references in working tree"}
             for t in sorted(cur_meas - base_meas)] +
            [{"task": t, "direction": "became_unmeasurable",
              "reasons": by_task[t].get("reasons")}
             for t in sorted(base_meas - cur_meas)]),
    }
    for r in results:
        summary["outcome_counts"][r["outcome"]] = \
            summary["outcome_counts"].get(r["outcome"], 0) + 1

    diff = [{"task": r["task"], "baseline": baseline_outcome.get(r["task"]),
             "replay": r["outcome"], "src_chars": r.get("src_chars"),
             "tokens_recomputed": r.get("tokens_recomputed")}
            for r in results if baseline_outcome.get(r["task"]) != r["outcome"]]
    summary["outcome_changes_vs_baseline"] = len(diff)

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {"provenance": provenance, "summary": summary, "results": results,
           "outcome_diff_vs_baseline": diff}
    (out_dir / "replay.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(summary, indent=1))
    print("wrote", out_dir / "replay.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
