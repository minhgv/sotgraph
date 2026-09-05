"""Concurrent ``record_provider_outcome`` ledger publication (P3 regression).

Extends the single-threaded rollback coverage in
``tests/test_monorepo_snapshot_adversarial.py`` (TestBindingRollback /
TestFailedSyncSupersede) to THREAD-LEVEL concurrency: several worker threads
publish run + binding + evidence atomically against one SQLite file that
already holds user note rows (``graph_nodes.kind='note'``, same shape as
``cmd_insert``) plus a previously committed binding and evidence row.

Contract under test (db.py P0 Contract 4): each publication is one
``with self.conn:`` transaction — an injected failure anywhere (duplicate
run id, duplicate evidence id landing AFTER the binding upsert) must roll
back that worker's whole transaction (all-or-nothing) while concurrent
healthy publications, prior ledger history, and user notes all survive.
No sleeps: workers rely on WAL + per-connection ``busy_timeout``; the only
failure is a deterministic duplicate-id injection, never a race.
"""
import hashlib

import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed

from sot_graph.db import Database

DB_TIMEOUT_MS = 15_000
WORKERS = 8
REPO_ID = "/mono"
HEAD_SEED = "1" * 40
HEAD_LIVE = "2" * 40
NOTE_TITLES = ("ledger keep", "notes survive", "rollback safe")


def run(run_id):
    return {"provider_name": "cbm", "capability": "search_graph",
            "status": "ok", "run_id": run_id}


def bind(project_id, head):
    return {"sot_repo_id": REPO_ID, "provider_name": "cbm",
            "provider_project_id": project_id, "head_sha": head}


def ev(ev_id):
    return [{"id": ev_id, "path": "a.py", "src_symbol": "foo",
             "relation": "defines", "snapshot_hash": "s" * 40}]


def worker_publish(db_path, run_id, ev_id, head, project_id):
    """One worker, one owned connection (Database is single-thread by design)."""
    db = Database(db_path, timeout_ms=DB_TIMEOUT_MS, initialize=False)
    try:
        return db.record_provider_outcome(
            run(run_id), bind(project_id, head), ev(ev_id))
    finally:
        db.close()


def seed_notes(db):
    # Same row shape as cli.cmd_insert: kind='note', id note:<sha12>.
    ids = []
    with db.conn:
        for title in NOTE_TITLES:
            body = f"body of {title}"
            nid = f"note:{hashlib.sha256(title.encode()).hexdigest()[:12]}"
            db.conn.execute(
                "INSERT INTO graph_nodes (id, path, kind, symbol, label, "
                "body, keywords, line_start, updated_at) "
                "VALUES (?, '', 'note', NULL, ?, ?, '', 1, 0)",
                (nid, title, body),
            )
            ids.append((nid, title, body))
    return ids


@pytest.fixture
def ledger(tmp_path):
    """DB with prior history: 3 notes + run_seed/ev_seed + binding p1@HEAD_SEED."""
    db = Database(str(tmp_path / "sot.db"))
    notes = seed_notes(db)
    db.record_provider_outcome(run("run_seed"), bind("p1", HEAD_SEED),
                               ev("ev_seed"))
    yield db, str(tmp_path / "sot.db"), notes
    db.close()


def assert_notes_intact(db, notes):
    rows = db.conn.execute(
        "SELECT id, label, body FROM graph_nodes WHERE kind='note' "
        "ORDER BY id").fetchall()
    assert rows == sorted(notes)


def assert_binding(db, project_id, head):
    rows = db.conn.execute(
        "SELECT provider_project_id, head_sha FROM provider_project_bindings "
        "WHERE sot_repo_id=?", (REPO_ID,)).fetchall()
    assert rows == [(project_id, head)]


class TestConcurrentLedgerPublication:
    def test_all_concurrent_publications_land_and_notes_history_preserved(
        self, ledger
    ):
        db, db_path, notes = ledger
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {
                pool.submit(worker_publish, db_path, f"run_c{i}",
                            f"ev_c{i}", HEAD_LIVE, "p1"): f"run_c{i}"
                for i in range(WORKERS)
            }
            landed = {fut.result() for fut in as_completed(futures)}
        assert landed == {f"run_c{i}" for i in range(WORKERS)}
        counts = db.conn.execute(
            "SELECT (SELECT COUNT(*) FROM provider_runs), "
            "(SELECT COUNT(*) FROM provider_evidence), "
            "(SELECT COUNT(*) FROM provider_evidence "
            "WHERE run_id LIKE 'run_c%'), "
            "(SELECT COUNT(*) FROM provider_project_bindings)"
        ).fetchone()
        # 8 new runs + seed; 8 new evidence rows + seed; single binding row.
        assert counts == (WORKERS + 1, WORKERS + 1, WORKERS, 1)
        assert_binding(db, "p1", HEAD_LIVE)
        # Prior history untouched: seed run/evidence still live (not
        # invalidated, not superseded) by concurrent publication.
        assert db.conn.execute(
            "SELECT COUNT(*) FROM provider_evidence WHERE "
            "id='ev_seed' AND invalidated_at IS NULL").fetchone()[0] == 1
        assert_notes_intact(db, notes)

    def test_injected_run_id_failure_among_concurrent_writes_all_or_nothing(
        self, ledger
    ):
        db, db_path, notes = ledger
        # Poisoned worker re-records the already-committed run id: its run
        # INSERT fails BEFORE binding/evidence, so nothing of it may land.
        with ThreadPoolExecutor(max_workers=7) as pool:
            good = [pool.submit(worker_publish, db_path, f"run_ok{i}",
                                f"ev_ok{i}", HEAD_LIVE, "p1")
                    for i in range(6)]
            bad = pool.submit(worker_publish, db_path, "run_seed",
                              "ev_poison", "9" * 40, "p9")
            assert [g.result() for g in good] == [
                f"run_ok{i}" for i in range(6)]
            with pytest.raises(ValueError, match="run_seed"):
                bad.result()
        counts = db.conn.execute(
            "SELECT (SELECT COUNT(*) FROM provider_runs), "
            "(SELECT COUNT(*) FROM provider_runs WHERE id='run_seed'), "
            "(SELECT COUNT(*) FROM provider_evidence WHERE "
            "run_id='run_seed'), (SELECT COUNT(*) FROM provider_evidence "
            "WHERE id='ev_poison')"
        ).fetchone()
        # Seed run kept exactly once with its own single evidence row; the
        # poisoned transaction left zero partial rows (all-or-nothing).
        assert counts == (7, 1, 1, 0)
        # Concurrent healthy writers' binding upsert survived; poisoned p9
        # binding never persisted even if it serialized before them.
        assert_binding(db, "p1", HEAD_LIVE)
        assert_notes_intact(db, notes)

    def test_evidence_stage_failure_under_concurrency_restores_prior_binding(
        self, ledger
    ):
        db, db_path, notes = ledger
        # Poisoned worker: unique run id but evidence id colliding with the
        # committed 'ev_seed' — the INSERT fails AFTER run + binding UPDATE,
        # so the whole transaction must roll back (binding restores).
        with ThreadPoolExecutor(max_workers=6) as pool:
            good = [pool.submit(worker_publish, db_path, f"run_ev{i}",
                                f"ev_ev{i}", HEAD_LIVE, "p1")
                    for i in range(5)]
            bad = pool.submit(worker_publish, db_path, "run_ebf",
                              "ev_seed", "9" * 40, "p9")
            assert [g.result() for g in good] == [
                f"run_ev{i}" for i in range(5)]
            with pytest.raises(ValueError,
                               match="duplicate provider_evidence id"):
                bad.result()
        counts = db.conn.execute(
            "SELECT (SELECT COUNT(*) FROM provider_runs WHERE "
            "id IN ('run_ebf','run_seed')), (SELECT COUNT(*) FROM "
            "provider_evidence), (SELECT COUNT(*) FROM provider_evidence "
            "WHERE run_id='run_ebf')"
        ).fetchone()
        # run_ebf fully absent; ledger = seed + 5 healthy evidence rows.
        assert counts == (1, 6, 0)
        assert_binding(db, "p1", HEAD_LIVE)
        # Prior evidence still live: rollback never superseded/invalidated it.
        assert db.conn.execute(
            "SELECT COUNT(*) FROM provider_evidence WHERE id='ev_seed' "
            "AND run_id='run_seed' AND invalidated_at IS NULL"
        ).fetchone()[0] == 1
        assert_notes_intact(db, notes)
