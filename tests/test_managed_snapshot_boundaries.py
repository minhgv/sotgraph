"""Managed snapshot-boundary tests: a source mutation that lands INSIDE
the native dispatch window — after the provider's capture point but
before its verification — is deterministically caught, and prior ledger
state survives untouched.

Seams reused from test_cbm_managed_provider.py: a real git repo, the real
ManagedNativeRuntime + ManagedRuntimeProfile, the faked native wire
(FakeNativeRunner) and a real SQLite ledger. The mutation fires inside
the fake native handler itself, so neither test is a generic
dirty-before-dispatch scenario: at the provider's pre-capture the tree is
provably clean (test 1's HEAD even provably equals the fixture head) and
only the handler mutates it mid-flight. Fully synchronous: no threads,
no sleeps, no real native binary.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sot_graph.db import Database
from sot_graph.providers import codebase_memory as cbm_mod
from sot_graph.providers import managed as managed_mod
from sot_graph.providers.base import IndexRequest, SymbolRequest

from test_cbm_managed_provider import (  # noqa: E402  (tests/ is not a package)
    PROVIDER,
    FakeNativeRunner,
    ManagedFixture,
    _git,
)


def _boom_spawn(*_args, **_kwargs):
    raise AssertionError("unmanaged legacy spawn attempted on a managed path")


@pytest.fixture(autouse=True)
def _forbid_legacy_spawn(monkeypatch):
    """The provider's own (legacy) run_command must never fire."""
    monkeypatch.setattr(cbm_mod, "run_command", _boom_spawn)


class MidFlightMutator(FakeNativeRunner):
    """Fake native wire that mutates the repo INSIDE one CLI dispatch.

    The hook fires after the provider's pre-capture and before its
    post-capture/verification — exactly where a real native sits.
    ``commit=True`` commits a new HEAD (adds b.py); otherwise the edit
    stays an untracked worktree change.
    """

    def __init__(self, repo: str, head: str, *, tool: str, commit: bool) -> None:
        super().__init__(repo, head)
        self._tool, self._commit = tool, commit
        self.mutations: list[str] = []

    def __call__(
        self, argv, cwd=None, env=None, timeout_seconds=None, max_output_bytes=None
    ):
        if len(argv) > 2 and argv[1] == "cli" and argv[2] == self._tool:
            Path(self.repo, "b.py").write_text("def bar():\n    return 2\n")
            _git(self.repo, "add", ".")
            if self._commit:
                _git(self.repo, "commit", "-q", "-m", "mid-flight mutation")
                self.mutations.append(_git(self.repo, "rev-parse", "HEAD"))
            else:
                self.mutations.append("dirty")
        return super().__call__(
            argv,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )


def _real_db_provider(fx, tmp_path):
    """ManagedFixture over a real SQLite ledger behind the SAME provider."""
    db = Database(str(tmp_path / "ledger.db"))
    provider = cbm_mod.CodebaseMemoryProvider(
        command=(fx.exe,), exact_context=fx.context, managed_runtime=fx.runtime, db=db
    )
    return db, provider


class TestIndexCompletionBoundary:
    """A COMMIT inside a SUCCESSFUL index_repository completion: the
    pre-capture saw (head=fixture head, clean); the post-capture sees a
    moved HEAD, so nothing fresh may bind and the prior binding survives."""

    def test_commit_inside_completion_publishes_no_fresh_binding(
        self, tmp_path, monkeypatch
    ):
        fx = ManagedFixture(tmp_path, monkeypatch)
        db, provider = _real_db_provider(fx, tmp_path)
        try:
            # Baseline: clean index publishes a binding at the fixture head.
            assert provider.index(IndexRequest(repo_root=fx.repo)).status == "ok"
            row = db.get_provider_binding(fx.repo, PROVIDER)
            assert row is not None and row["head_sha"] == fx.head

            # SECOND index: the fake native COMMITS a new HEAD inside its
            # own successful completion — after the provider pre-captured
            # and before its post-capture reads.
            mutator = MidFlightMutator(
                fx.repo, fx.head, tool="index_repository", commit=True
            )
            monkeypatch.setattr(managed_mod, "run_command", mutator)
            record = provider.index(IndexRequest(repo_root=fx.repo))
            # The native completion itself succeeded: honest ok receipt...
            assert record.status == "ok"
            # ...and the mutation really fired mid-dispatch: the HEAD moved
            # across the capture boundary while the tree stayed CLEAN at
            # both captures (the baseline publication proves pre/post
            # cleanliness rules; the commit keeps the tree clean).
            new_head = mutator.mutations[0]
            assert mutator.mutations == [new_head] and new_head != fx.head
            # So NO fresh binding is published for the new HEAD: the second
            # run row persists with a NULL snapshot_hash, and the prior
            # ledger binding stays exactly as it was.
            hashes = db.conn.execute(
                "SELECT snapshot_hash FROM provider_runs ORDER BY rowid"
            ).fetchall()
            assert [h[0] for h in hashes] == [fx.head, None]
            assert db.get_provider_binding(fx.repo, PROVIDER)["head_sha"] == fx.head
            # A query afterwards is honestly STALE (old binding vs the new
            # HEAD) — never FRESH.
            out = provider.search_symbols(SymbolRequest(repo_root=fx.repo, query="foo"))
            assert out.ok
            assert out.metadata["snapshot_bound"] is True
            assert out.metadata["freshness"] == "STALE"
            snap = out.metadata["snapshot"]
            assert snap["cbm_head_sha"] == fx.head
            assert snap["sot_head_sha"] == new_head
        finally:
            db.close()
            shutil.rmtree(fx.profile.namespace, ignore_errors=True)


class TestSearchCompletionBoundary:
    """A WORKTREE EDIT inside a SUCCESSFUL search_graph completion: the
    native payload predates the edit; the post-payload snapshot
    verification still runs and never reports FRESH."""

    def test_edit_inside_search_completion_stale_no_ledger_writes(
        self, tmp_path, monkeypatch
    ):
        fx = ManagedFixture(tmp_path, monkeypatch)
        db, provider = _real_db_provider(fx, tmp_path)
        try:
            # Baseline: a binding was published, so the worktree was CLEAN
            # and HEAD == fx.head right up to the search dispatch.
            assert provider.index(IndexRequest(repo_root=fx.repo)).status == "ok"
            runs_before = db.conn.execute(
                "SELECT COUNT(*) FROM provider_runs"
            ).fetchone()[0]

            # The fake native DIRTIES the worktree inside its successful
            # search_graph completion: the payload predates the edit; the
            # provider's post-payload verification does not.
            mutator = MidFlightMutator(
                fx.repo, fx.head, tool="search_graph", commit=False
            )
            monkeypatch.setattr(managed_mod, "run_command", mutator)
            out = provider.search_symbols(SymbolRequest(repo_root=fx.repo, query="foo"))
            assert mutator.mutations == ["dirty"]
            # The native payload still returned...
            assert out.ok
            assert out.payload["rows"][0]["qualified_name"] == "foo"
            # ...but the verdict is provably NOT FRESH: bound, STALE via
            # the unconditional dirty check (HEAD unchanged — edit only).
            assert out.metadata["snapshot_bound"] is True
            assert out.metadata["freshness"] == "STALE"
            assert out.metadata["source_changed"] is True
            snap = out.metadata["snapshot"]
            assert "dirty worktree" in snap["detail"]
            assert snap["sot_head_sha"] == fx.head
            # Managed reads never persist: zero new ledger rows and the
            # binding is untouched.
            assert (
                db.conn.execute("SELECT COUNT(*) FROM provider_runs").fetchone()[0]
                == runs_before
            )
            assert db.get_provider_binding(fx.repo, PROVIDER)["head_sha"] == fx.head
        finally:
            db.close()
            shutil.rmtree(fx.profile.namespace, ignore_errors=True)
