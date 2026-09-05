"""SG-202 exit-gate evaluator: pack task sufficiency (PILOT, self-corpus).

Exit gate (issue #9): ">= 95% of benchmark tasks receive the target +
direct contracts + >= 1 relevant test within budget."

Measurement contract (post-review, tightened):
- Tasks are seeded samples of production definitions; ground truth is the
  stdlib-ast oracle in ``sot_graph.holdout.evaluator`` (never the pack's
  own accounting).
- Direct contracts are IDENTITY pairs ``(callee_path, callee_name)`` from
  the oracle. A contract is satisfied only by an ``outbound_callees``
  entry whose relative path AND bare name both match — inbound callers
  and 2-hop stubs never satisfy a direct-contract obligation (no
  same-name false credit).
- Relevant test (HEURISTIC, declared, conservative-for-direction
  reference superset): a test module referencing the target bare name via
  ``ast.Name`` id or ``ast.Attribute`` attr. Receipt requires an
  ``inbound_callers`` entry (a graph caller edge) whose path lies in the
  relevant set — i.e. the pack actually delivered a test module that
  calls the target, not merely any test-touched path. A hand-curated
  fixed subset is ALWAYS fully evaluated (checked count published;
  checked == 0 or any mismatch fails oracle validation and the gate).
- Both denominators are published: sufficiency over ALL sampled tasks
  (primary) and over the oracle-measurable subset (gate metric). Cap
  overflow / no-relevant-test exclusions never imply 95% of all tasks.
- Scores are PILOT scope (self-repo corpus) and do NOT close the global
  gate.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sot_graph.holdout.evaluator import (
    OracleConfig,
    extract_definitions,
    iter_python_files,
    resolve_direct_calls,
    sample_definitions,
)

from .common import (
    build_temp_index,
    close_temp_index,
    gate_verdict,
    normalize_rel,
    oracle_category,
    repo_provenance,
)

CONTRACTS_CAP = 8
DEFAULT_BUDGET_TOKENS = 1500          # documented recommendation (AGENTS §4)
GATE_FLOOR = 0.95
DEFAULT_MIN_TASKS = 30
GT_SUBSET_PATH = Path(__file__).parent / "fixtures" / "sg202_gt_subset.json"


@dataclass
class TaskResult:
    key: str
    name: str
    path: str
    outcome: str = ""
    reasons: List[str] = field(default_factory=list)
    contracts_expected: int = 0
    contracts_returned: int = 0
    contracts_unmeasured: bool = False
    relevant_test_files: int = 0
    test_received: bool = False
    target_ok: bool = False
    over_budget: bool = False
    tokens_reported: Optional[int] = None
    tokens_recomputed: Optional[int] = None
    full_success: bool = False


def _bare_names_from_fqn(fqn: str) -> Set[str]:
    parts = {fqn}
    parts.add(fqn.rsplit(".", 1)[-1])
    parts.add(fqn.rsplit(":", 1)[-1])
    parts.add(fqn.rsplit(".", 1)[-1].rsplit(":", 1)[-1])
    return parts


def _relevant_test_files(root: Path, test_rels: List[str],
                         target_name: str) -> List[str]:
    """HEURISTIC reference-superset oracle: test modules referencing the
    target bare name via ast.Name id OR ast.Attribute attr. Superset on
    purpose: it can only over-approximate test obligations (conservative
    direction for a >=95% gate). Validated against a curated subset."""
    hits: List[str] = []
    for rel in test_rels:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == target_name:
                found = True
            elif isinstance(node, ast.Attribute) and node.attr == target_name:
                found = True
            if found:
                break
        if found:
            hits.append(rel)
    return hits


def load_gt_subset() -> Dict[str, List[str]]:
    if not GT_SUBSET_PATH.exists():
        return {}
    return json.loads(GT_SUBSET_PATH.read_text())


def validate_oracle_against_gt_subset(root: Path, test_rels: List[str],
                                      gt_subset: Dict[str, List[str]],
                                      ) -> Tuple[int, List[str]]:
    """Evaluate EVERY curated case (independent of the sampled tasks).

    Entries whose source file does not exist in THIS corpus are not
    applicable and are skipped (the curated subset is per-corpus); on the
    self-repo all entries apply. Metadata keys (``_``-prefixed) are
    skipped.
    """
    mismatches: List[str] = []
    checked = 0
    for key, curated in sorted(gt_subset.items()):
        if key.startswith("_"):        # metadata keys of the fixture
            continue
        rel = key.split("::", 1)[0]
        if not (root / rel).exists():
            continue                   # curated entry not applicable here
        checked += 1
        target_name = key.rsplit("::", 1)[-1]
        heuristic = sorted(_relevant_test_files(root, test_rels, target_name))
        if heuristic != sorted(curated):
            mismatches.append(f"{key}: heuristic={heuristic} curated={sorted(curated)}")
    return checked, mismatches


def _owner_chains(root: Path, rels: List[str]) -> Dict[Tuple[str, str], Set[Tuple[str, ...]]]:
    """AST lexical owner chains per (relpath, defname): ``()`` for
    module-level defs, ``("Class",)`` / ``("Outer", "Inner")`` for nested
    or method defs. Collision-safe identity basis (path + owner chain)."""
    chains: Dict[Tuple[str, str], Set[Tuple[str, ...]]] = {}

    def walk(node: ast.AST, stack: Tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chains.setdefault((cur, child.name), set()).add(stack)
                walk(child, stack + (child.name,))
            elif isinstance(child, ast.ClassDef):
                chains.setdefault((cur, child.name), set()).add(stack)
                walk(child, stack + (child.name,))
            else:
                walk(child, stack)

    for rel in rels:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        cur = rel
        walk(tree, ())
    return chains


def run_task_sufficiency(
    repo_root: str,
    *,
    seed: int = 20260905,
    limit: int = 40,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    min_tasks: int = DEFAULT_MIN_TASKS,
    workers: int = 4,
    db: Any = None,
    close_db: bool = True,
) -> Dict[str, Any]:
    root = Path(repo_root).resolve()

    # --- independent oracle -------------------------------------------------
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
        if (Path(rel).name.startswith("test_") or Path(rel).name.endswith("_test.py"))
        and oracle_category(rel) == "test"
    ]
    edges, unresolved_calls = resolve_direct_calls(root, defs, config)
    contracts_by_task: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
    for e in edges:
        pairs = contracts_by_task.setdefault((e.caller_path, e.caller_name), [])
        pair = (e.callee_path, e.callee_name)
        if pair not in pairs:
            pairs.append(pair)

    tasks = sample_definitions(production_defs, seed, limit)

    # Curated GT-subset validation covers ALL curated cases, always.
    gt_subset = load_gt_subset()
    gt_checked, gt_mismatches = validate_oracle_against_gt_subset(
        root, test_rels, gt_subset)

    # --- index once (temp DB; never the shared .sot) -------------------------
    owned_db = db is None
    tmp_dir: Optional[str] = None
    if db is None:
        db, tmp_dir = build_temp_index(str(root), workers=workers)
    from sot_graph.pack import PackError, build_bundle, render_yaml
    from sot_graph.tokenizer import estimate_tokens

    results: List[TaskResult] = []

    try:
        for t in tasks:
            key = f"{t.path}::{t.name}"
            expected_pairs = sorted(set(contracts_by_task.get((t.path, t.name), [])))
            unmeasured = len(expected_pairs) > CONTRACTS_CAP
            measured = expected_pairs[:CONTRACTS_CAP]
            relevant_tests = _relevant_test_files(root, test_rels, t.name)

            res = TaskResult(key=key, name=t.name, path=t.path,
                             contracts_expected=len(expected_pairs),
                             contracts_unmeasured=unmeasured,
                             relevant_test_files=len(relevant_tests))
            if unmeasured or not relevant_tests:
                res.outcome = "ORACLE_UNMEASURABLE"
                if unmeasured:
                    res.reasons.append(
                        f"contracts_overflow ({len(expected_pairs)} > cap {CONTRACTS_CAP})")
                if not relevant_tests:
                    res.reasons.append("no_relevant_test_in_corpus")
                results.append(res)
                continue

            try:
                bundle = build_bundle(
                    db, str(root), t.name,
                    max_hops=2, max_nodes=50,
                    max_bytes=65_536, max_tokens=budget_tokens)
            except PackError as exc:
                res.outcome = "PACK_ERROR"
                res.reasons.append(f"{getattr(exc, 'code', 'PACK_ERROR')}: {exc}")
                results.append(res)
                continue

            target = bundle.get("target", {})
            # Identity rule (declared, collision-safe): the oracle knows
            # the def's lexical owner chain from the task's own file. The
            # bundle must present an fqn equal to
            # ``module(.Owner)*.name`` for one of the oracle chains, and
            # a symbol that is ``name`` or ends with ``.name``.
            expected_module = t.path[:-len(".py")] if t.path.endswith(".py") else t.path
            expected_module = expected_module.replace("/", ".")
            if expected_module.startswith("src."):
                expected_module = expected_module[len("src."):]
            chains = owner_chains.get((t.path, t.name)) or {()}
            expected_fqns = {
                expected_module + "." + ".".join(chain + (t.name,))
                for chain in chains}
            fqn = str(target.get("fqn") or "")
            sym = str(target.get("symbol") or "")
            identity_ok = (
                (sym == t.name or sym.endswith("." + t.name))
                and fqn in expected_fqns
            )
            source_ok = bool(
                target.get("full_source")
                or bundle.get("accounting", {})
                .get("target_source", {}).get("returned") == 1
            )
            res.target_ok = identity_ok and source_ok
            if not res.target_ok:
                res.reasons.append(
                    "missing_target_identity_or_source "
                    f"(symbol={sym!r} fqn={fqn!r} "
                    f"expected_fqns={sorted(expected_fqns)} "
                    f"source_returned={source_ok})")

            # Direct contracts: identity match on (callee_path, callee_name),
            # outbound_callees entries ONLY.
            outbound = bundle.get("outbound_callees") or []
            outbound_identities = [
                (normalize_rel(str(e.get("relative_path", "")), str(root)),
                 _bare_names_from_fqn(str(e.get("fqn", ""))))
                for e in outbound
            ]
            missing: List[str] = []
            for cpath, cname in measured:
                ok = any(p == cpath and cname in names
                         for p, names in outbound_identities)
                if ok:
                    res.contracts_returned += 1
                else:
                    missing.append(f"{cpath}::{cname}")
            contracts_ok = not missing
            if missing:
                res.reasons.append("missing_direct_contracts: " + ",".join(missing))

            # Relevant test RECEIPT: an inbound caller edge (graph fact)
            # from a test module in the oracle-relevant set.
            relevant_set = set(relevant_tests)
            res.test_received = any(
                normalize_rel(str(e.get("relative_path", "")), str(root))
                in relevant_set
                for e in (bundle.get("inbound_callers") or []))
            if not res.test_received:
                res.reasons.append("missing_relevant_test_caller")

            reported = int(bundle.get("limits", {}).get("tokens_estimate") or 0)
            recomputed = estimate_tokens(render_yaml(bundle))
            res.tokens_reported = reported
            res.tokens_recomputed = recomputed
            res.over_budget = max(reported, recomputed) > budget_tokens
            if res.over_budget:
                res.reasons.append(
                    f"over_budget (reported={reported} recomputed={recomputed} "
                    f"budget={budget_tokens})")

            res.full_success = bool(res.target_ok and contracts_ok
                                    and res.test_received and not res.over_budget)
            if res.full_success:
                res.outcome = "FULL_SUCCESS"
            elif not res.target_ok:
                res.outcome = "MISSING_TARGET"
            elif not contracts_ok:
                res.outcome = "MISSING_CONTRACTS"
            elif not res.test_received:
                res.outcome = "MISSING_TEST"
            else:
                res.outcome = "OVER_BUDGET"
            results.append(res)
    finally:
        if owned_db and close_db:
            close_temp_index(db, tmp_dir)

    # --- denominators (defined by the ORACLE, not by pack success) ----------
    attempted = len(results)
    measurable = [r for r in results if r.outcome != "ORACLE_UNMEASURABLE"]
    full = [r for r in measurable if r.full_success]
    sufficiency_measurable = (len(full) / len(measurable)) if measurable else None
    sufficiency_all = (len(full) / attempted) if attempted else None

    outcome_counts: Dict[str, int] = {}
    for r in results:
        outcome_counts[r.outcome] = outcome_counts.get(r.outcome, 0) + 1
    reason_counts: Dict[str, int] = {}
    for r in results:
        for reason in r.reasons:
            head = reason.split(":", 1)[0].split(" (", 1)[0]
            reason_counts[head] = reason_counts.get(head, 0) + 1

    failures = [
        {"task": r.key, "outcome": r.outcome, "reasons": r.reasons,
         "contracts_expected": r.contracts_expected,
         "contracts_returned": r.contracts_returned,
         "relevant_test_files": r.relevant_test_files}
        for r in results if r.outcome not in ("FULL_SUCCESS",)
    ]

    oracle_validation_passed = gt_checked > 0 and not gt_mismatches
    if len(measurable) < min_tasks:
        passed_flag = None             # insufficient sampling outranks all
    elif not oracle_validation_passed:
        passed_flag = False
    else:
        passed_flag = (sufficiency_measurable is not None
                       and sufficiency_measurable >= GATE_FLOOR)
    gate = gate_verdict(
        passed=passed_flag,
        min_denominator=min_tasks, denominator=len(measurable),
        metric=(round(sufficiency_measurable, 4)
                if sufficiency_measurable is not None else None),
        floor=GATE_FLOOR, gate_id="sg202_task_sufficiency>=0.95")
    if not oracle_validation_passed and len(measurable) >= min_tasks:
        gate["oracle_validation"] = (
            "MISSING_GT_SUBSET" if gt_checked == 0 else "FAILED")
        gate["verdict"] = "ORACLE_VALIDATION_FAILED"
        gate["passed"] = False
    else:
        gate["oracle_validation"] = (
            f"PASSED ({gt_checked} curated cases checked)"
            if oracle_validation_passed else
            ("MISSING_GT_SUBSET" if gt_checked == 0 else "FAILED"))

    # Provenance note must be CONDITIONAL on digest exactness.
    prov = repo_provenance(str(root))
    prov["note"] = (
        "snapshot binding: scores apply to exactly this HEAD+worktree "
        "(content-exact digest)" if not prov["digest_truncated"]
        else "snapshot binding PARTIAL: digest truncated (cap/unreadable) — "
             "treat as HEAD + declared dirty set, NOT content-exact")

    return {
        "benchmark": "sg202-task-sufficiency",
        "scope": "PILOT — self-repo corpus (sot-graph); does NOT close the global exit gate",
        "provenance": prov,
        "policy": {
            "task_sampling": "seeded sample_definitions over src/ source-tree defs "
                             "(oracle production category; vendor/fixture/test excluded)",
            "task_universe_label": "src source-tree defs (oracle production category)",
            "seed": seed, "requested_tasks": limit,
            "budget_tokens": budget_tokens,
            "contracts_cap": CONTRACTS_CAP,
            "contract_satisfaction": "identity (callee_path, callee_name) on "
                                     "outbound_callees entries only; inbound/stubs never credit",
            "contracts_overflow_handling": "task ORACLE_UNMEASURABLE, excluded from "
                                           "numerators, denominator published",
            "relevant_test_oracle": "HEURISTIC reference superset (ast Name/Attribute "
                                    "bare-name in test module); receipt = inbound caller "
                                    "edge from a relevant test module",
            "oracle_validation": "curated fixed subset, ALL cases always evaluated",
            "gate_floor": GATE_FLOOR, "min_measurable_tasks": min_tasks,
            "gate_metric_note": "gate metric is measured-subset sufficiency; "
                                "all-sampled sufficiency published alongside",
        },
        "denominators": {
            "production_defs_universe": len(production_defs),
            "parse_failures": len(parse_failures),
            "parse_failure_paths": parse_failures[:20],
            "parse_failure_note": "paths published; oracle-wide (includes "
                                  "non-universe trees such as .holdout-cache "
                                  "fixture corpora — outside the src/ task universe)",
            "attempted_tasks": attempted,
            "oracle_unmeasurable": attempted - len(measurable),
            "contracts_overflow": sum(1 for r in results if r.contracts_unmeasured),
            "no_relevant_test": sum(1 for r in results if r.relevant_test_files == 0),
            "measurable_tasks": len(measurable),
            "full_success": len(full),
            "gt_subset_cases_checked": gt_checked,
        },
        "metrics": {
            "task_sufficiency_all_sampled": (round(sufficiency_all, 4)
                                             if sufficiency_all is not None
                                             else None),
            "task_sufficiency_measurable": (round(sufficiency_measurable, 4)
                                            if sufficiency_measurable
                                            is not None else None),
            "target_receipt_rate": (round(sum(1 for r in measurable if r.target_ok)
                                          / len(measurable), 4) if measurable else None),
            "test_receipt_rate": (round(sum(1 for r in measurable if r.test_received)
                                        / len(measurable), 4) if measurable else None),
            "tokens_median_recomputed": _median([r.tokens_recomputed for r in results]),
        },
        "outcome_counts": outcome_counts,
        "reason_counts": reason_counts,
        "oracle_validation": {"checked": gt_checked, "mismatches": gt_mismatches},
        "failures": failures,
        "task_roster": [{"task": r.key, "outcome": r.outcome,
                         "full_success": r.full_success} for r in results],
        "gate": gate,
        "unresolved_oracle_calls": unresolved_calls,
    }


def _median(values: List[Optional[int]]) -> Optional[int]:
    nums = sorted(v for v in values if v is not None)
    if not nums:
        return None
    n = len(nums)
    return nums[n // 2] if n % 2 else (nums[n // 2 - 1] + nums[n // 2]) // 2


def render_markdown(report: Dict[str, Any]) -> str:
    d = report["denominators"]
    m = report["metrics"]
    g = report["gate"]
    lines = [
        "# SG-202 exit-gate measurement — task sufficiency (PILOT)",
        "",
        f"Scope: {report['scope']}",
        "",
        "## Provenance",
        f"- git HEAD: `{report['provenance']['git_head']}` "
        f"worktree digest: `{report['provenance']['worktree_digest']}` "
        f"(dirty entries: {report['provenance']['dirty_entries']}, "
        f"digest truncated: {report['provenance']['digest_truncated']})",
        f"- {report['provenance']['note']}",
        "",
        "## Policy (declared)",
    ]
    for k, v in report["policy"].items():
        lines.append(f"- {k}: {v}")
    lines += [
        "",
        "## Denominators",
        f"- production defs universe: {d['production_defs_universe']} "
        f"(oracle parse failures: {d['parse_failures']})",
        f"- attempted tasks: {d['attempted_tasks']}",
        f"- oracle-unmeasurable: {d['oracle_unmeasurable']} "
        f"(contracts overflow: {d['contracts_overflow']}, no relevant test: {d['no_relevant_test']})",
        f"- **measurable denominator: {d['measurable_tasks']}** "
        f"(gate metric denominator)",
        f"- full success: {d['full_success']}",
        f"- curated GT-subset cases checked: {d['gt_subset_cases_checked']}",
        "",
        "## Metrics",
        f"- task sufficiency over ALL sampled tasks: "
        f"**{m['task_sufficiency_all_sampled']}** (exclusions do NOT imply 95% of all tasks)",
        f"- task sufficiency over measurable subset (gate metric): "
        f"**{m['task_sufficiency_measurable']}** (floor 0.95)",
        f"- target receipt rate (measurable): {m['target_receipt_rate']}",
        f"- relevant-test receipt rate (measurable): {m['test_receipt_rate']}",
        f"- median recomputed tokens per bundle: {m['tokens_median_recomputed']}",
        "",
        "## Outcome counts",
    ]
    for k in sorted(report["outcome_counts"]):
        lines.append(f"- {k}: {report['outcome_counts'][k]}")
    lines += ["", "## Failure reasons (heads)"]
    for k in sorted(report["reason_counts"]):
        lines.append(f"- {k}: {report['reason_counts'][k]}")
    lines += [
        "",
        "## Gate",
        f"- verdict: **{g['verdict']}** (metric {g['metric']} vs floor {g['floor']}, "
        f"denominator {g['denominator']} / min {g['min_denominator']}, "
        f"oracle validation: {g.get('oracle_validation')})",
        "",
        "## Failures",
    ]
    for f in report["failures"][:20]:
        lines.append(f"- `{f['task']}` → {f['outcome']}: {'; '.join(f['reasons'])}")
    if not report["failures"]:
        lines.append("- none")
    return "\n".join(lines) + "\n"
