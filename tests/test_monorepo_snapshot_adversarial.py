"""Adversarial monorepo/worktree snapshot-binding gap tests (P3 preparation).

Open gaps not covered elsewhere: unborn-git repos (test_cbm_snapshot_p2 covers
NON-git dirs), provider index() failed-sync never superseding prior binding or
evidence (test_sg109 covers direct-ingest supersede), an evidence failure rolling
back a binding UPDATE to its PRIOR values via the public duplicate-id ValueError
(test_snapshot_content_binding covers fresh-db INSERT rollback), linked
worktrees sharing one HEAD as distinct repo identities, rename/delete between
capture and verify. Fake private-PATH exe; no native binary, no net.
"""
import os, stat, subprocess, sys  # noqa: E401
import pytest

from conftest import require_shebang_exec

from sot_graph.db import Database
from sot_graph.providers.base import IndexRequest, SymbolRequest
from sot_graph.providers.codebase_memory import (
    PROVIDER_NAME, CodebaseMemoryProvider,
)
from sot_graph.snapshot import (
    bind_snapshot, capture_worktree_snapshot, get_head_sha,
)


def git(repo: str, *args: str) -> None:
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)


def head_sha(repo: str) -> str:
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def make_repo(tmp_path, name: str = "repo") -> str:
    repo = tmp_path / name
    repo.mkdir()
    git(str(repo), "init", "-q")
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    git(str(repo), "add", ".")
    git(str(repo), "-c", "user.email=adv@test", "-c", "user.name=Adv Test",
        "commit", "-q", "-m", "init")
    return str(repo)


def make_unborn(tmp_path) -> str:
    """Git repo with zero commits (unborn HEAD) and one untracked file."""
    repo = tmp_path / "unborn"
    repo.mkdir()
    git(str(repo), "init", "-q")
    (repo / "x.py").write_text("def x():\n    return 0\n", encoding="utf-8")
    return str(repo)


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "sot.db"))
    yield database
    database.close()


def make_fake_cli(directory, name: str = "cbm-adv") -> str:
    # Real search wire shape is column-name-addressed; index head env-controlled.
    body = (
        "import json, os, sys\n"
        "tool = sys.argv[sys.argv.index('--json') + 1]\n"
        "if tool == 'index_repository':\n"
        "    sys.exit(int(os.environ.get('ADV_FAKE_INDEX_EXIT', '0')))\n"
        "head = os.environ.get('ADV_FAKE_HEAD_SHA', '') or None\n"
        "if tool == 'list_projects':\n"
        "    payload = {'projects': [{'name': 'proj-adv', 'root_path':\n"
        "        os.getcwd()}], 'has_more': False}\n"
        "elif tool == 'index_status':\n"
        "    payload = {'status': 'ok', 'head_sha': head, 'branch': 'main',\n"
        "        'coverage_report': {}}\n"
        "else:\n"
        "    payload = {'cols': ['qn', 'file', 'label'],\n"
        "        'rows': [['mod::foo', 'a.py', 'function']]}\n"
        "env = {'content': [{'type': 'text', 'text': json.dumps(payload)}],\n"
        "       'isError': False, 'structuredContent': {}}\n"
        "print(json.dumps(env))\n"
    )
    if os.name == "nt":
        # CreateProcess cannot exec shebang scripts; install a .cmd wrapper
        # that forwards to this interpreter (same pattern as P2 make_exe),
        # keeping a single spawnable argv[0]. No module-level skip: the
        # pure DB/snapshot cases run on every platform regardless.
        script = directory / f"{name}.py"
        script.write_text(body, encoding="utf-8")
        wrapper = directory / f"{name}.cmd"
        wrapper.write_text(
            f'@"{sys.executable}" "%~dp0{name}.py" %*\r\n', encoding="utf-8")
        return str(wrapper)
    require_shebang_exec()
    path = directory / name
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def provider_for(tmp_path, db) -> CodebaseMemoryProvider:
    return CodebaseMemoryProvider(command=[make_fake_cli(tmp_path)], db=db)


def search(provider: CodebaseMemoryProvider, repo: str):
    return provider.search_symbols(SymbolRequest(repo_root=repo, query="foo"))


class TestUnbornHead:
    def test_unborn_repo_captures_and_binds_fail_closed(self, tmp_path, db):
        repo = make_unborn(tmp_path)
        assert get_head_sha(repo) is None
        snap = capture_worktree_snapshot(repo)
        assert snap.commit_sha is None and snap.dirty is True
        assert snap.dirty_fingerprint and snap.descriptor_digest.startswith(
            "sha256:")
        bind_snapshot(db.conn, repo)
        row = db.conn.execute(
            "SELECT commit_sha, dirty, dirty_fingerprint FROM snapshots"
        ).fetchone()
        # No HEAD -> stored NULL, never a guess; dirty stored fail-closed.
        assert row[0] is None and row[1] == 1 and row[2] is not None

    def test_query_against_unborn_head_reports_unknown_freshness(
        self, tmp_path, db, monkeypatch
    ):
        repo = make_unborn(tmp_path)
        monkeypatch.setenv("ADV_FAKE_HEAD_SHA", "f" * 40)
        out = search(provider_for(tmp_path, db), repo)
        assert out.ok is True
        # Provider claims a head, SOT has none: bound but fail-closed UNKNOWN.
        assert out.metadata["freshness"] == "UNKNOWN"
        assert out.metadata["snapshot_bound"] is True


class TestLinkedWorktrees:
    def test_same_head_worktrees_bind_as_distinct_repo_identities(
        self, tmp_path, db, monkeypatch
    ):
        repo = make_repo(tmp_path)
        wt2 = str(tmp_path / "wt2")
        git(repo, "worktree", "add", "--detach", wt2, "HEAD")
        sha = head_sha(repo)
        assert head_sha(wt2) == sha  # same commit, different worktrees
        monkeypatch.setenv("ADV_FAKE_HEAD_SHA", sha)
        provider = provider_for(tmp_path, db)
        assert search(provider, repo).ok and search(provider, wt2).ok
        b1 = db.get_provider_binding(repo, PROVIDER_NAME)
        b2 = db.get_provider_binding(wt2, PROVIDER_NAME)
        assert b1 and b2 and b1["head_sha"] == b2["head_sha"] == sha
        assert b1["id"] != b2["id"]  # separate rows, never merged
        roots = {r[0] for r in db.conn.execute(
            "SELECT DISTINCT project_root FROM provider_runs").fetchall()}
        assert roots == {os.path.realpath(repo), os.path.realpath(wt2)}


class TestMutationBetweenCaptures:
    def test_staged_rename_keeps_head_but_rotates_fingerprint(self, tmp_path):
        repo = make_repo(tmp_path)
        pre = capture_worktree_snapshot(repo)
        git(repo, "mv", "a.py", "b.py")
        post = capture_worktree_snapshot(repo)
        assert post.commit_sha == pre.commit_sha  # same committed tree
        assert post.dirty is True and post.dirty_fingerprint is not None
        assert post.dirty_fingerprint != pre.dirty_fingerprint
        assert post.descriptor_digest != pre.descriptor_digest

    def test_deleted_cited_path_fails_closed_on_recapture(self, tmp_path):
        repo = make_repo(tmp_path)
        before = capture_worktree_snapshot(repo, cited_paths=["a.py"])
        assert before.scope_digest is not None and before.unreadable == []
        os.unlink(os.path.join(repo, "a.py"))
        after = capture_worktree_snapshot(repo, cited_paths=["a.py"])
        assert after.scope_digest is None and "a.py" in after.unreadable
        assert after.descriptor_digest != before.descriptor_digest  # rotated


class TestFailedSyncSupersede:
    def test_failed_index_sync_preserves_prior_binding_and_evidence(
        self, tmp_path, db, monkeypatch
    ):
        repo = make_repo(tmp_path)
        sha1 = head_sha(repo)
        monkeypatch.setenv("ADV_FAKE_HEAD_SHA", sha1)
        provider = provider_for(tmp_path, db)
        assert search(provider, repo).ok is True
        # A committed change the failed sync will never capture.
        with open(os.path.join(repo, "a.py"), "a", encoding="utf-8") as fh:
            fh.write("def bar():\n    return 2\n")
        git(repo, "-c", "user.email=adv@test", "-c", "user.name=Adv Test",
            "commit", "-q", "-am", "second")
        monkeypatch.setenv("ADV_FAKE_HEAD_SHA", head_sha(repo))
        monkeypatch.setenv("ADV_FAKE_INDEX_EXIT", "3")
        assert provider.index(IndexRequest(repo_root=repo)).status \
            == "provider_error"
        assert db.get_provider_binding(repo, PROVIDER_NAME)["head_sha"] == sha1
        # Failed sync wrote no second binding.
        assert db.conn.execute(
            "SELECT COUNT(*) FROM provider_project_bindings").fetchone()[0] == 1
        failed = db.conn.execute(
            "SELECT snapshot_hash FROM provider_runs "
            "WHERE capability='index_repository'").fetchone()
        assert failed is not None and failed[0] is None
        live, dead = db.conn.execute(
            "SELECT COUNT(*), SUM(invalidated_at IS NOT NULL) "
            "FROM provider_evidence").fetchone()
        assert live >= 1 and dead == 0  # prior evidence never superseded


class TestBindingRollback:
    def test_evidence_failure_rolls_back_binding_update_to_prior_values(
        self, db
    ):
        ev = [{"id": "ev_rb", "path": "a.py", "src_symbol": "foo",
               "relation": "defines", "snapshot_hash": "s" * 40}]

        def bind(pid, h):
            return {"sot_repo_id": "/rb", "provider_name": "cbm",
                    "provider_project_id": pid, "head_sha": h}

        def run(rid):
            return {"provider_name": "cbm", "capability": "search_graph",
                    "status": "ok", "run_id": rid}

        db.record_provider_outcome(run("run_ok"), bind("p1", "1" * 40), ev)
        # Duplicate evidence id -> the evidence INSERT fails AFTER the run
        # INSERT and binding UPDATE; everything must roll back and the prior
        # binding values must survive untouched.
        with pytest.raises(ValueError):
            db.record_provider_outcome(run("run_rb2"), bind("p2", "2" * 40), ev)
        counts = db.conn.execute(
            "SELECT (SELECT COUNT(*) FROM provider_runs "
            "WHERE id='run_rb2'), (SELECT COUNT(*) FROM provider_evidence "
            "WHERE run_id='run_rb2')").fetchone()
        assert counts == (0, 0)
        row = db.conn.execute(
            "SELECT provider_project_id, head_sha FROM provider_project_bindings "
            "WHERE sot_repo_id='/rb'").fetchone()
        assert row == ("p1", "1" * 40)  # prior binding preserved
