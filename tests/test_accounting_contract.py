"""SG-107 accounting contract — structured, line-independent (P1-4).

WHY A NEW FILE (instead of extending test_sg107_stress.py): the stress
suite is a behavioral suite at issue-#2 scale (real repos, verdicts,
payload parity); the accounting contract is a DIFFERENT shape — a
static AST lint + a production registry + fail-closed validation.
Keeping the contract here lets the stress suite assert behavior while
this module owns the mechanism, and gives the registry one home whose
docstring is the contract documentation. The stress suite's
``TestLimitTripwire`` delegates to the same production sweep so the
SG-107 exit gate stays self-contained there.

WHAT THIS LOCKS (replacing the old line-bound
``_ACCOUNTED_LIMITS: Dict[Tuple[str, int], str]`` tripwire, which broke
whenever innocent lines moved in receipts.py):

1. Registry honesty — ids unique, cap value encoded in the id, every
   registered (module, collector) still importable, every SQL-backed
   site still owns a LIMIT (stale-entry drift detection, line-free).
2. Static sweep — an AST scan of src/sot_graph/assurance/ maps every
   SQL ``LIMIT`` literal to its enclosing collector; anything not in
   ``ACCOUNTED_SITES`` or ``NON_TRUNCATING_COLLECTORS`` FAILS. A new
   unregistered cap cannot land unnoticed.
3. Fail-closed runtime — the production gate ``ensure_accounted``
   refuses any truncation source outside the registry; a poisoned
   receipt builder emitting an unknown reason RAISES instead of
   emitting an unrecognizable diagnostic.
4. Trigger coverage — every registry id is exercised by a real receipt
   whose cap actually fires and surfaces the id in
   ``facts.truncation_sources`` / ``collection_truncated:<id>``.
5. Boundaries — cap-1 / cap / cap+1 behave correctly (no cut at cap,
   cut + named source above it, fully drained below it).
6. Line-independence proofs — the sweep result is invariant under
   inserted innocent lines, and neither this contract nor the registry
   references any source line number.

Exception-path diagnostics (``collection_error:<source>:...``) are
pinned here too; transport-side trimming (``response_too_large``) is a
different mechanism, already pinned field-by-field by
``test_sg107_stress.py`` — referenced, not duplicated.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, Set, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sot_graph.assurance import accounting
from sot_graph.assurance.accounting import (
    ACCOUNTED_SITES,
    CHANGED_FILES_SOURCE,
    DEBT_MARKERS_SOURCE,
    EDGES_SOURCE,
    EVIDENCE_SOURCE,
    LEDGER_RUNS_SOURCE,
    LOGICAL_COLLECTION_SOURCES,
    NON_TRUNCATING_COLLECTORS,
    TRANSITIVE_SOURCE,
    UnaccountedSource,
    assurance_package_dir,
    ensure_accounted,
    is_accounted_source,
    is_ledger_union_source,
    iter_sql_limit_sites,
    ledger_union_source,
    reason_code_for,
    registry_source_ids,
    unbacked_registry_sites,
    unregistered_limit_sites,
)
from sot_graph.assurance.receipts import diff_impact_receipt, scope_receipt
from sot_graph.assurance.state import STATUS_SEVERITY
from test_impact_pipeline import (
    _FaultyConn,
    _commit_all,
    _db_of,
    _make_repo,
)
from test_sg107_stress import _seed_evidence, _seed_edges, _write_mods

_EDGES_CAP = 500
_EVIDENCE_PATH_CAP = 50
_LEDGER_RUNS_CAP = 200
_TRANSITIVE_CAP = 200
_UNION_CAP = 5000

#: ids exercised by the trigger tests below; the coverage meta-test
#: demands this set EQUALS the registry, so a NEW registry entry without
#: a triggering scenario cannot land (and an orphan trigger cannot
#: outlive its registry entry).
EXERCISED_SOURCE_IDS: Set[str] = set()


def _severe(status: str) -> int:
    return STATUS_SEVERITY[status]


def _count_edges(db: Any, node_id: str, direction: str) -> int:
    col, op = ("dst", "=") if direction == "in" else ("src", "=")
    return int(db.conn.execute(
        f"SELECT COUNT(*) FROM graph_edges WHERE {col} {op} ?",
        (node_id,),
    ).fetchone()[0])


# ---------------------------------------------------------------------------
# Fixtures (module-scoped; batched inserts, mirroring the stress suite)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def edges_repo(tmp_path_factory) -> Path:
    """501 in-edges (one past the per-direction cap 500) + 60 out."""
    repo = _make_repo(tmp_path_factory.mktemp("ac_edges"))
    db = _db_of(repo)
    try:
        _seed_edges(db, "e", n_in=501, n_out=60)
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def transitive_repo(tmp_path_factory) -> Path:
    """250 direct callees of 'run': the BFS walk must pass cap 200."""
    repo = _make_repo(tmp_path_factory.mktemp("ac_trans"))
    db = _db_of(repo)
    try:
        _seed_edges(db, "t", n_in=0, n_out=250)
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def ledger_runs_repo(tmp_path_factory) -> Path:
    """201 provider_runs for this project: the recent-runs window cuts."""
    repo = _make_repo(tmp_path_factory.mktemp("ac_runs"))
    db = _db_of(repo)
    try:
        db.conn.executemany(
            "INSERT INTO provider_runs "
            "(id, provider_name, provider_version, capability, snapshot_hash,"
            " project_root, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            [
                (f"run_{i}", "prov", "1.0", "AST_HEURISTIC_PARSER", None,
                 str(repo.resolve()), "ok", 1_700_000_000 + i)
                for i in range(_LEDGER_RUNS_CAP + 1)
            ],
        )
        db.conn.commit()
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def ledger_union_repo(tmp_path_factory) -> Path:
    """5001 evidence rows across distinct paths: the union cap fires."""
    repo = _make_repo(tmp_path_factory.mktemp("ac_union"))
    db = _db_of(repo)
    try:
        _seed_evidence(
            db, repo, "run_union",
            (f"led/saturate_{i:05d}.py" for i in range(_UNION_CAP + 1)),
        )
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def files201_repo(tmp_path_factory) -> Path:
    """201-file commit: the post-change receipt cites only the first 200."""
    repo = _make_repo(tmp_path_factory.mktemp("ac_files201"))
    _write_mods(repo, 201)
    _commit_all(repo, "c2: 201 new modules")
    return repo


def _boundary_repos(tmp_path_factory, prefix: str, cap: int,
                    targets: Tuple[int, ...], kind: str):
    """Repos parked exactly at target/cap/cap+1 for one cap family."""
    repos: Dict[int, Path] = {}
    for target in targets:
        repo = _make_repo(tmp_path_factory.mktemp(f"{prefix}_{target}"))
        db = _db_of(repo)
        try:
            if kind == "edges":
                node_id = db.get_node_by_symbol("run")["id"]
                baseline_in = _count_edges(db, node_id, "in")
                assert baseline_in < target  # fixture premise
                _seed_edges(db, f"b{target}", n_in=target - baseline_in,
                            n_out=0)
            else:
                _seed_evidence(db, repo, f"run_b{target}", ["app.py"],
                               per_path=target)
        finally:
            db.close()
        repos[target] = repo
    return repos


@pytest.fixture(scope="module")
def edge_boundary_repos(tmp_path_factory) -> Dict[int, Path]:
    return _boundary_repos(
        tmp_path_factory, "ac_bnd_e", _EDGES_CAP,
        (_EDGES_CAP - 1, _EDGES_CAP, _EDGES_CAP + 1), "edges")


@pytest.fixture(scope="module")
def evidence_boundary_repos(tmp_path_factory) -> Dict[int, Path]:
    return _boundary_repos(
        tmp_path_factory, "ac_bnd_v", _EVIDENCE_PATH_CAP,
        (_EVIDENCE_PATH_CAP - 1, _EVIDENCE_PATH_CAP, _EVIDENCE_PATH_CAP + 1),
        "evidence")


# ---------------------------------------------------------------------------
# 1. Registry honesty
# ---------------------------------------------------------------------------


class TestRegistryHonesty:
    def test_source_ids_unique(self):
        ids = [site.source_id for site in ACCOUNTED_SITES]
        assert len(ids) == len(set(ids)), "duplicate registry ids"

    def test_cap_value_encoded_in_id(self):
        for site in ACCOUNTED_SITES:
            if site.cap is not None:
                assert site.source_id.endswith(f"_{site.cap}"), (
                    f"{site.source_id}: id must encode its cap "
                    f"{site.cap} (ids are operator-facing diagnostics)"
                )

    def test_union_family_pattern_well_formed(self):
        union = [s for s in ACCOUNTED_SITES if s.cap is None]
        assert len(union) == 1
        assert union[0].source_id == "ledger_union_cap_<limit>"
        assert is_ledger_union_source(ledger_union_source(5000))
        assert is_ledger_union_source(ledger_union_source(1))
        assert not is_ledger_union_source("ledger_union_cap_")
        assert not is_ledger_union_source("ledger_union_cap_abc")

    def test_registered_collectors_exist(self):
        for site in ACCOUNTED_SITES:
            mod = importlib.import_module(
                f"sot_graph.assurance.{site.module}")
            owner = getattr(mod, site.collector, None)
            assert callable(owner), (
                f"registry entry {site.source_id} points at "
                f"{site.module}.{site.collector}, which does not exist "
                "(renamed/moved? update ACCOUNTED_SITES)"
            )

    def test_sql_backed_sites_own_a_limit(self):
        """Stale-entry drift detection — the line-free successor of the
        old 'stale tripwire registry entries' check."""
        unbacked = unbacked_registry_sites(assurance_package_dir())
        assert not unbacked, (
            f"{[s.source_id for s in unbacked]}: SQL-backed registry "
            "sites whose collector no longer owns a LIMIT — update the "
            "registry, never ignore the drift"
        )

    def test_logical_collections_map_to_registered_ids(self):
        known = registry_source_ids() | {"ledger_union_cap_<limit>"}
        for logical, source_id in LOGICAL_COLLECTION_SOURCES.items():
            assert source_id in known, (
                f"collection_stats['{logical}'] maps to unregistered "
                f"source {source_id!r}"
            )

    def test_non_truncating_allowlist_has_justifications(self):
        for key, why in NON_TRUNCATING_COLLECTORS.items():
            assert len(key) == 2 and len(why) > 20, (
                f"allowlist entry {key} needs (module, collector) + a "
                "real justification"
            )


# ---------------------------------------------------------------------------
# 2. Static sweep (AST, line-independent)
# ---------------------------------------------------------------------------


class TestStaticSweep:
    def test_every_sql_limit_in_assurance_is_registered(self):
        offenders = unregistered_limit_sites(assurance_package_dir())
        assert not offenders, (
            "NEW UNACCOUNTED CAP SITE(S): "
            + "; ".join(
                f"{s.module}.{s.collector} -> {s.sql!r}" for s in offenders
            )
            + ". A collection-bounding LIMIT must report CollectionStats "
            "(twin COUNT) + a named truncation source and be registered "
            "in accounting.ACCOUNTED_SITES — or be justified in "
            "NON_TRUNCATING_COLLECTORS."
        )

    def test_sweep_finds_the_registered_sql_cap_collectors(self):
        sites = iter_sql_limit_sites(assurance_package_dir())
        collectors = {(s.module, s.collector) for s in sites}
        assert ("receipts", "_edges_of") in collectors
        assert ("receipts", "_ledger_cross_check") in collectors
        assert ("receipts", "diff_impact_receipt") in collectors
        assert ("ledger", "union_evidence") in collectors
        # The known non-truncating lookups must still be VISIBLE to the
        # sweep (allowlisted, not invisible).
        assert ("engine", "resolve_symbol") in collectors

    def test_new_unregistered_cap_fails_the_sweep(self, tmp_path):
        """Advisor acceptance: a NEW cap type introduced WITHOUT
        registration must FAIL the contract — simulated on a scratch
        package dir so no production file is touched."""
        (tmp_path / "ledger.py").write_text(
            "def union_evidence(db, repo_root):\n"
            "    return db.conn.execute('SELECT 1').fetchall()\n",
            encoding="utf-8",
        )
        (tmp_path / "sneaky.py").write_text(
            "def _sneaky_cap(db):\n"
            "    return db.conn.execute(\n"
            "        'SELECT * FROM graph_edges LIMIT 25'\n"
            "    ).fetchall()\n",
            encoding="utf-8",
        )
        offenders = unregistered_limit_sites(tmp_path)
        assert [(s.module, s.collector) for s in offenders] == [
            ("sneaky", "_sneaky_cap")
        ], "an unregistered SQL cap must fail the sweep"
        # And the registered-but-innocent module stays clean.
        assert all(s.module != "ledger" for s in offenders)

    def test_sweep_maps_limits_to_enclosing_collector_not_line(self):
        for site in iter_sql_limit_sites(assurance_package_dir()):
            assert site.collector and site.collector != "", site
            assert hasattr(site, "module") and not hasattr(site, "lineno")


# ---------------------------------------------------------------------------
# 3. Fail-closed runtime gate
# ---------------------------------------------------------------------------


class TestFailClosedRuntime:
    def test_unknown_source_raises(self):
        with pytest.raises(UnaccountedSource) as excinfo:
            ensure_accounted(
                [EDGES_SOURCE, "sneaky_new_cap_42"], where="unit")
        assert "sneaky_new_cap_42" in str(excinfo.value)
        assert EDGES_SOURCE not in str(excinfo.value)

    @pytest.mark.parametrize(
        "source_id",
        sorted(s for s in registry_source_ids() if "<" not in s)
        + [ledger_union_source(5000), ledger_union_source(7)],
    )
    def test_registered_sources_pass(self, source_id):
        ensure_accounted([source_id])  # must not raise
        assert is_accounted_source(source_id)

    def test_simulated_unregistered_reason_cannot_enter_receipt(
            self, edges_repo, monkeypatch):
        """A NEW unregistered cap reason emitted by a receipt builder is
        CAUGHT (raises) instead of landing in a receipt — the fail-closed
        end of the SG-107 accounting contract."""
        import sot_graph.assurance.receipts as receipts_mod

        real_map = receipts_mod._ledger_truncation_sources

        def poisoned(stats):
            return real_map(stats) + ["unregistered_new_cap_999"]

        monkeypatch.setattr(
            receipts_mod, "_ledger_truncation_sources", poisoned)
        db = _db_of(edges_repo)
        try:
            with pytest.raises(UnaccountedSource) as excinfo:
                scope_receipt(db, str(edges_repo), "run")
        finally:
            db.close()
        assert "unregistered_new_cap_999" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Trigger coverage: every registry id surfaces in a real receipt
# ---------------------------------------------------------------------------


class TestRegistryIdsSurfaceInReceipts:
    """Each registry id must be exercisable: a scenario where the cap
    FIRES and the id appears in facts.truncation_sources and in the
    ``collection_truncated:<id>`` reason code. Every scenario also pins
    that receipt ``collection_stats`` keys stay within the registry's
    logical-collection map."""

    @staticmethod
    def _assert_reason(payload: Dict[str, Any], source_id: str) -> None:
        facts = payload["assurance_facts"]
        assert source_id in facts["truncation_sources"]
        # The expected reason code is DERIVED from the registry (the
        # transitive source keeps its historical ``transitive_truncated``
        # code; every other source emits collection_truncated:<id>).
        assert reason_code_for(source_id) in (
            payload["assurance"]["reason_codes"])
        assert facts["truncated"] is True
        unknown = [s for s in facts["truncation_sources"]
                   if not is_accounted_source(s)]
        assert not unknown, f"unaccounted sources leaked: {unknown}"

    def test_edges_cap(self, edges_repo):
        db = _db_of(edges_repo)
        try:
            payload = scope_receipt(db, str(edges_repo), "run")
        finally:
            db.close()
        self._assert_reason(payload, EDGES_SOURCE)
        assert set(payload["collection_stats"]) <= set(
            LOGICAL_COLLECTION_SOURCES)
        EXERCISED_SOURCE_IDS.add(EDGES_SOURCE)

    def test_transitive_cap(self, transitive_repo):
        db = _db_of(transitive_repo)
        try:
            payload = scope_receipt(db, str(transitive_repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["transitive"]
        assert stats["truncated"] is True
        assert stats["cap"] == _TRANSITIVE_CAP
        self._assert_reason(payload, TRANSITIVE_SOURCE)
        EXERCISED_SOURCE_IDS.add(TRANSITIVE_SOURCE)

    def test_ledger_runs_cap(self, ledger_runs_repo):
        db = _db_of(ledger_runs_repo)
        try:
            payload = scope_receipt(db, str(ledger_runs_repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["ledger_runs"]
        assert stats["truncated"] is True
        assert stats["enumerated_count"] == _LEDGER_RUNS_CAP + 1
        assert stats["returned_count"] == _LEDGER_RUNS_CAP
        self._assert_reason(payload, LEDGER_RUNS_SOURCE)
        EXERCISED_SOURCE_IDS.add(LEDGER_RUNS_SOURCE)

    def test_ledger_union_cap(self, ledger_union_repo):
        db = _db_of(ledger_union_repo)
        try:
            payload = scope_receipt(db, str(ledger_union_repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["ledger_union"]
        assert stats["truncated"] is True
        assert stats["cap"] == _UNION_CAP
        seen = payload["assurance_facts"]["truncation_sources"]
        union_ids = [s for s in seen if is_ledger_union_source(s)]
        assert union_ids, f"union family missing from sources: {seen}"
        self._assert_reason(payload, union_ids[0])
        EXERCISED_SOURCE_IDS.add("ledger_union_cap_<limit>")

    def test_changed_files_cap(self, files201_repo):
        db = _db_of(files201_repo)
        try:
            payload = diff_impact_receipt(db, str(files201_repo))
        finally:
            db.close()
        assert payload["changed_files_total"] == 201
        assert payload["changed_files_truncated"] is True
        stats = payload["collection_stats"]["changed_files"]
        assert stats["returned_count"] == 200
        self._assert_reason(payload, CHANGED_FILES_SOURCE)
        EXERCISED_SOURCE_IDS.add(CHANGED_FILES_SOURCE)

    def test_evidence_cap(self, evidence_boundary_repos):
        repo = evidence_boundary_repos[_EVIDENCE_PATH_CAP + 1]
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        stats = payload["collection_stats"]["invalidated_evidence"]
        assert stats["truncated"] is True
        self._assert_reason(payload, EVIDENCE_SOURCE)
        EXERCISED_SOURCE_IDS.add(EVIDENCE_SOURCE)

    def test_debt_markers_cap(self, tmp_path):
        """P7.3: 51 TODO lines in one commit — one past the debt-marker
        report cap; the enumeration stays exact (total 51) while the
        reported list cuts at 50 and names DEBT_MARKERS_SOURCE."""
        from test_impact_pipeline import _git, _make_repo

        repo = _make_repo(tmp_path / "ac_debt")
        lines = ["x = 1"]
        lines += [f"v{i} = {i}  # TODO(p73): marker {i}" for i in range(51)]
        (repo / "app.py").write_text("\n".join(lines) + "\n",
                                     encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "debt")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        debt = payload["resolution_ledger"]["debt_markers"]
        assert debt["total"] == 51
        assert len(debt["introduced"]) == 50
        assert debt["truncated"] is True
        stats = payload["collection_stats"]["debt_markers"]
        assert stats["enumerated_count"] == 51
        assert stats["returned_count"] == 50
        self._assert_reason(payload, DEBT_MARKERS_SOURCE)
        EXERCISED_SOURCE_IDS.add(DEBT_MARKERS_SOURCE)

    def test_coverage_complete(self):
        """Registry ⇆ triggers bijection: a NEW registry entry without a
        trigger scenario fails here (and an orphan trigger cannot
        outlive its registry entry)."""
        assert EXERCISED_SOURCE_IDS == registry_source_ids(), (
            f"registry/trigger drift: missing triggers for "
            f"{registry_source_ids() - EXERCISED_SOURCE_IDS}, orphan "
            f"triggers {EXERCISED_SOURCE_IDS - registry_source_ids()}"
        )


# ---------------------------------------------------------------------------
# 5. Boundaries: cap-1 / cap / cap+1
# ---------------------------------------------------------------------------


class TestEdgesCapBoundaries:
    @pytest.mark.parametrize(
        "target", [_EDGES_CAP - 1, _EDGES_CAP, _EDGES_CAP + 1])
    def test_in_direction_boundary(
            self, edge_boundary_repos, target):
        repo = edge_boundary_repos[target]
        db = _db_of(repo)
        try:
            node_id = db.get_node_by_symbol("run")["id"]
            in_total = _count_edges(db, node_id, "in")
            out_total = _count_edges(db, node_id, "out")
            payload = scope_receipt(db, str(repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["direct_edges"]
        facts = payload["assurance_facts"]
        cut = target > _EDGES_CAP
        assert stats["enumerated_count"] == in_total + out_total
        assert stats["returned_count"] == (
            min(in_total, _EDGES_CAP) + min(out_total, _EDGES_CAP))
        assert stats["truncated"] is cut
        assert stats["cursor_exhausted"] is not cut
        assert (EDGES_SOURCE in facts["truncation_sources"]) is cut
        assert (reason_code_for(EDGES_SOURCE)
                in payload["assurance"]["reason_codes"]) is cut
        if cut:
            assert _severe(payload["assurance"]["status"]) >= _severe(
                "PARTIAL")
        else:
            # The EDGES cap did not cut. (Other caps, e.g. the transitive
            # BFS walk over 500 seeded callers, may still fire on this
            # fixture — they are separate, individually named sources.)
            assert EDGES_SOURCE not in facts["truncation_sources"]


class TestEvidenceCapBoundaries:
    @pytest.mark.parametrize(
        "target", [_EVIDENCE_PATH_CAP - 1, _EVIDENCE_PATH_CAP,
                   _EVIDENCE_PATH_CAP + 1])
    def test_per_path_boundary(self, evidence_boundary_repos, target):
        repo = evidence_boundary_repos[target]
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        stats = payload["collection_stats"]["invalidated_evidence"]
        cut = target > _EVIDENCE_PATH_CAP
        assert stats["enumerated_count"] == target
        assert stats["returned_count"] == min(target, _EVIDENCE_PATH_CAP)
        assert stats["cap"] == _EVIDENCE_PATH_CAP
        assert stats["truncated"] is cut
        assert (EVIDENCE_SOURCE
                in payload["assurance_facts"]["truncation_sources"]) is cut
        if cut:
            assert _severe(payload["assurance"]["status"]) >= _severe(
                "PARTIAL")


# ---------------------------------------------------------------------------
# 6. Diagnostics: exception vs truncation are different, both named
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_storage_fault_surfaces_collection_error_not_truncation(
            self, edges_repo):
        """An exception is a DIFFERENT diagnostic from a cap cut: it must
        name the collector via ``collection_error:<source>:...`` and
        degrade the verdict — never read as 'no more callers'."""
        db = _db_of(edges_repo)
        real = db.conn
        db.conn = _FaultyConn(
            real,
            lambda sql: sql.startswith("SELECT e.relation, e.line"),
        )
        try:
            payload = scope_receipt(db, str(edges_repo), "run")
        finally:
            db.conn = real
            db.close()
        assert any(
            w.startswith("collection_error:edges_of:")
            for w in payload["warnings"])
        assert "collection_error" in payload["assurance"]["reason_codes"]
        assert payload["assurance_facts"]["collection_error"] is True
        # The edges cap did NOT cut (the query failed outright): no
        # truncation source may borrow the cut's diagnostic.
        assert EDGES_SOURCE not in (
            payload["assurance_facts"]["truncation_sources"])

    def test_truncation_surfaces_named_reason_code(self, edges_repo):
        db = _db_of(edges_repo)
        try:
            payload = scope_receipt(db, str(edges_repo), "run")
        finally:
            db.close()
        assert reason_code_for(EDGES_SOURCE) in (
            payload["assurance"]["reason_codes"])
        assert _severe(payload["assurance"]["status"]) >= _severe("PARTIAL")


# ---------------------------------------------------------------------------
# 7. Line-independence proofs
# ---------------------------------------------------------------------------


class TestLineIndependence:
    def test_sweep_invariant_to_innocent_line_insertions(self, tmp_path):
        """Copy the real assurance package, pad receipts.py with 40
        innocent lines (comments, blanks, prose strings — the kind of
        edit that used to break the line-number tripwire), and prove the
        swept (module, collector, sql) result is IDENTICAL."""
        pkg = assurance_package_dir()
        for path in pkg.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if path.name == "receipts.py":
                # Innocent edits only: comments, blanks, a harmless
                # module-level string. (Prose actually mentioning LIMIT
                # in CODE position would rightly trip the sweep.)
                padding = (
                    "# innocent review comment\n\n"
                    'PROSE = "no collection happens in this file header"\n'
                    "# another innocent line\n\n"
                ) * 10
                text = padding + text
            (tmp_path / path.name).write_text(text, encoding="utf-8")
        before = iter_sql_limit_sites(pkg)
        after = iter_sql_limit_sites(tmp_path)
        assert {(s.module, s.collector, s.sql) for s in before} == {
            (s.module, s.collector, s.sql) for s in after
        }
        # And the padded copy still passes the full contract sweep.
        assert unregistered_limit_sites(tmp_path) == []

    def test_contract_references_no_source_line_numbers(self):
        """Neither this contract nor the registry may bind anything to
        (file, LINE NUMBER) pairs — the debt that made the old tripwire
        break on innocent edits."""
        pattern = re.compile(r"\.py\",\s*\d+")
        for label, path in (
            ("test_accounting_contract.py", Path(__file__)),
            ("accounting.py",
             Path(accounting.__file__)),
        ):
            assert not pattern.search(path.read_text(encoding="utf-8")), (
                f"{label} binds a registry to source line numbers — "
                "that is the P1-4 debt this contract exists to prevent"
            )
