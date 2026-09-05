"""Holdout denominator accounting (advisor P1-5).

Locks the P1-5 measurement-contract reporting added to the SG-204
holdout: every metric (presence, impact recall, test-selection,
abstention) must publish denominator / measured / excluded (with
reasons) and label its score as computed over the MEASURED denominator
only. A metric with NO measurable universe for a repo (e.g. jsonschema
test-selection: no test references the changed symbols; attribute-only
references are not modelable) must surface as ``unmeasurable: <reason>``
— never as a pass-by-default ``None``-that-looks-fine.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "scripts"))

from sot_graph.holdout import evaluator  # noqa: E402

import bench_holdout  # noqa: E402


# ---------------------------------------------------------------------------
# accounting() block contract
# ---------------------------------------------------------------------------


def test_accounting_block_shape_and_arithmetic():
    block = bench_holdout.accounting(
        "impact_recall",
        denominator=40,
        measured=25,
        excluded_reasons={"sample_cap_25": 15},
        out_of_scope={"ambiguous_callee_name": 3},
    )
    assert block["denominator"] == 40
    assert block["measured"] == 25
    assert block["excluded"] == 15
    assert block["excluded_reasons"] == {"sample_cap_25": 15}
    assert block["out_of_scope"] == {"ambiguous_callee_name": 3}
    assert "unmeasurable" not in block
    assert block["score_basis"] == "measured_denominator_only"


def test_unmeasurable_metric_is_zeroed_and_reasoned():
    block = bench_holdout.accounting(
        "test_selection_recall",
        denominator=0,
        measured=0,
        unmeasurable_reason="no tests reference changed symbols",
    )
    assert block["denominator"] == 0
    assert block["measured"] == 0
    assert block["excluded"] == 0
    assert block["unmeasurable"] == "no tests reference changed symbols"
    assert block["score_basis"] == "measured_denominator_only"


# ---------------------------------------------------------------------------
# Oracle helper: attribute-only references
# ---------------------------------------------------------------------------


def test_attribute_referenced_names_vs_bare():
    text = "import pkg\n\n\ndef test_x():\n    pkg.alpha2()\n    helper()\n"
    bare = evaluator.referenced_names(text)
    attrs = evaluator.attribute_referenced_names(text)
    assert "alpha2" not in bare, "attribute access is not a bare reference"
    assert "alpha2" in attrs
    assert "pkg" in bare and "pkg" not in attrs
    assert evaluator.attribute_referenced_names("\x00def broken(") == set(), (
        "parse failure under-counts out-of-scope, never obligations"
    )


# ---------------------------------------------------------------------------
# suite_test_selection on a real tiny git repo
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args}: {result.stderr.strip()[:200]}")
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message)


@pytest.fixture(scope="module")
def measured_repo(tmp_path_factory) -> Path:
    """base..head adds symbol beta; one bare-ref test added in the diff
    (measured obligation) + one PRE-EXISTING test whose only contact
    with beta is attribute access (out of scope, not diff-touched)."""
    repo = tmp_path_factory.mktemp("denom_measured")
    (repo / "pkg.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    # Pre-existing test file: references beta only via attribute access,
    # IDENTICAL in base..head (not diff-touched) so it is never a GT
    # obligation — exercising the out-of-scope accounting instead.
    (tests / "test_attr.py").write_text(
        "import pkg\n\n\ndef test_attr():\n    assert pkg.beta() == 2\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _commit(repo, "base")
    (repo / "pkg.py").write_text(
        "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n",
        encoding="utf-8",
    )
    (tests / "test_direct.py").write_text(
        "from pkg import beta\n\n\ndef test_direct():\n    assert beta() == 2\n",
        encoding="utf-8",
    )
    _commit(repo, "head: add beta + direct test")
    return repo


def _suite_for(repo: Path) -> dict:
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler

    base = _git(repo, "rev-parse", "HEAD~1")
    head = _git(repo, "rev-parse", "HEAD")
    db_path = repo / ".sot" / "sot.db"
    if db_path.exists():
        db_path.unlink()
    db = Database(str(db_path))
    try:
        Reconciler(db, str(repo)).reconcile(workers=1)
        return bench_holdout.suite_test_selection(db, repo, repo, base, head)
    finally:
        db.close()


def test_test_selection_denominator_measured_and_out_of_scope(measured_repo):
    record = _suite_for(measured_repo)
    metrics = record["metrics"]
    acct = record["accounting"]["test_selection_recall"]
    # Only the BARE-reference test is a measurable obligation.
    assert metrics["test_selection_recall"] is not None
    assert record["gt_tests"] == ["tests/test_direct.py"]
    assert acct["denominator"] == 1
    assert acct["measured"] == 1
    assert acct["excluded"] == 0
    assert acct["out_of_scope"] == {
        "attribute_only_reference_not_modelable": 1
    }, "attribute-only test published out-of-scope, not silently dropped"
    assert acct["score_basis"] == "measured_denominator_only"


def test_jsonschema_style_unmeasurable_is_not_a_pass(tmp_path_factory):
    """A diff whose changed symbols no test references (the jsonschema
    case) must surface as ``unmeasurable: <reason>`` with recall None —
    never as a pass-by-default 1.0."""
    repo = tmp_path_factory.mktemp("denom_unmeas")
    (repo / "pkg.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _commit(repo, "base")
    (repo / "pkg.py").write_text("def alpha2():\n    return 2\n", encoding="utf-8")
    _commit(repo, "head: rename, no tests")
    record = _suite_for(repo)
    assert record["metrics"]["test_selection_recall"] is None
    acct = record["accounting"]["test_selection_recall"]
    assert acct["unmeasurable"] == "no tests reference changed symbols"
    assert acct["denominator"] == 0
    assert acct["measured"] == 0
    assert acct["score_basis"] == "measured_denominator_only"


# ---------------------------------------------------------------------------
# Aggregate denominators folding
# ---------------------------------------------------------------------------


def _ts_record(name, acct=None, metrics=None, error=None,
               suite: str = "test_selection",
               key: str = "test_selection_recall"):
    record = {"name": name}
    if error:
        record["error"] = error
        return record
    record[suite] = {
        "metrics": metrics or {"test_selection_recall": 1.0},
        "accounting": {key: acct},
    }
    return record


def test_aggregate_denominators_fold_and_label():
    records = [
        _ts_record(
            "measured-ok",
            acct=bench_holdout.accounting("test_selection_recall", 5, 5),
        ),
        _ts_record(
            "jsonschema",
            acct=bench_holdout.accounting(
                "test_selection_recall",
                0,
                0,
                unmeasurable_reason="no tests reference changed symbols",
            ),
            metrics={"test_selection_recall": None},
        ),
        _ts_record("broken-run", error="RuntimeError: boom"),
    ]
    agg = bench_holdout.aggregate(records)
    # Macro values keep their existing semantics: mean over MEASURED repos.
    assert agg["metrics"]["test_selection_recall_macro"] == 1.0
    assert agg["metrics"]["test_selection_measured_repos"] == 1
    d = agg["denominators"]["test_selection_recall"]
    assert d["denominator_total"] == 5
    assert d["measured_total"] == 5
    assert d["excluded_total"] == 0
    assert d["repos_total"] == 3
    assert d["repos_measured"] == 1
    assert d["unmeasurable_repos"] == {
        "jsonschema": "no tests reference changed symbols",
        "broken-run": "run error: RuntimeError: boom",
    }
    assert d["score_basis"] == "measured_denominator_only"
    # The score is LABELED as measured-denominator-only.
    assert "measured denominator only" in (
        agg["metrics"]["test_selection_recall_macro_basis"]
    )
    assert "1/3 repos" in agg["metrics"]["test_selection_recall_macro_basis"]


def test_aggregate_denominators_merge_reason_counts():
    records = [
        _ts_record(
            "a",
            acct=bench_holdout.accounting(
                "impact_recall",
                40,
                25,
                excluded_reasons={"sample_cap_25": 15},
                out_of_scope={"ambiguous_callee_name": 3},
            ),
            metrics={"impact_recall": 1.0},
        ),
        _ts_record(
            "b",
            acct=bench_holdout.accounting(
                "impact_recall",
                30,
                25,
                excluded_reasons={"sample_cap_25": 5},
                out_of_scope={"ambiguous_callee_name": 1},
            ),
            metrics={"impact_recall": 0.5},
        ),
    ]
    # Route through the impact metric slot.
    for r in records:
        r["impact"] = r.pop("test_selection")
        r["impact"]["accounting"] = {"impact_recall": r["impact"]["accounting"].pop(
            "test_selection_recall")}
    agg = bench_holdout.aggregate(records)
    d = agg["denominators"]["impact_recall"]
    assert d["denominator_total"] == 70
    assert d["measured_total"] == 50
    assert d["excluded_total"] == 20
    assert d["excluded_reasons"] == {"sample_cap_25": 20}
    assert d["out_of_scope"] == {"ambiguous_callee_name": 4}
    assert agg["metrics"]["impact_recall_macro"] == 0.75, (
        "macro value must be unchanged by the denominators work"
    )


def test_markdown_publishes_denominators_and_unmeasurable():
    records = [
        _ts_record(
            "jsonschema",
            acct=bench_holdout.accounting(
                "test_selection_recall",
                0,
                0,
                unmeasurable_reason="no tests reference changed symbols",
            ),
            metrics={"test_selection_recall": None},
        ),
        _ts_record(
            "click",
            acct=bench_holdout.accounting("test_selection_recall", 3, 3),
        ),
    ]
    agg = bench_holdout.aggregate(records)
    report = {
        "aggregate": agg,
        "repos": records,
    }
    md = bench_holdout.markdown_summary(report)
    assert "unmeasurable: jsonschema (no tests reference changed symbols)" in md
    assert "unmeasurable (no tests reference changed symbols)" in md
    assert "| metric | universe | measured | excluded |" in md
    assert "MEASURED denominator" in md
