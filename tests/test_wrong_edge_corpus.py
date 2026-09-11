"""W4 counter-corpus — receiver-collision wrong edges must not be
fabricated (Danh_gia priority 1: get/update family).

Five planted cases over the get/update high-collision names:

  * ``cfg.get(...)`` / ``obj.get(...)`` — unknowable receiver type
  * ``self.get(...)`` in a class whose MRO lacks the method
  * ``self.s.get(...)`` — attribute-chain receiver
  * a nested ``def get`` shadowing the module-level decoy

Every receiver-bearing call that cannot be type-resolved must stay in
pending_edges (UNRESOLVED), never bare-matched onto the module-level
decoys in ``api.py``. The real calls (``api.get(k)``, ``s.get``,
``st.update``, ``self.get`` inside Session, the nested shadow) must
still resolve.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CORPUS = Path(__file__).parent / "fault" / "wrong_edge_corpus"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture()
def corpus_repo(tmp_path) -> Path:
    repo = tmp_path / "corpus"
    shutil.copytree(CORPUS, repo)
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "corpus")
    proc = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "reconcile"], cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-400:]
    return repo


def _edges(repo: Path):
    import sqlite3
    conn = sqlite3.connect(str(repo / ".sot" / "sot.db"))
    try:
        calls = conn.execute(
            "SELECT src, dst FROM graph_edges WHERE relation = 'calls'"
        ).fetchall()
        pending = conn.execute(
            "SELECT src, dst_symbol FROM pending_edges "
            "WHERE relation = 'calls' AND resolution_state = 'UNRESOLVED'"
        ).fetchall()
        nodes = dict(conn.execute(
            "SELECT id, symbol FROM graph_nodes").fetchall())
    finally:
        conn.close()
    return calls, pending, nodes


class TestWrongEdgeCorpus:
    """The bar: 0 wrong edges onto the api.py decoys; real calls intact."""

    def test_no_edge_lands_on_api_decoys(self, corpus_repo):
        calls, _, _ = _edges(corpus_repo)
        api_get_hits = [
            (s, d) for s, d in calls
            if d.endswith(":get") and "caller" in s
        ]
        # Only the genuine `api.get(k)` call may land on the decoy.
        assert all("qualified_api_get" in s for s, _ in api_get_hits), (
            f"wrong edges onto api.get: {api_get_hits}")

    def test_unresolvable_receiver_calls_stay_pending(self, corpus_repo):
        _, pending, _ = _edges(corpus_repo)
        pending_srcs = {s for s, _ in pending}
        for needle in (
            "case1_dict_get", "case3_unknown_receiver",
            "Service.run", "Holder.go",
        ):
            assert any(needle in s for s in pending_srcs), (
                f"{needle} must stay pending, not fabricate an edge")

    def test_real_calls_still_resolve(self, corpus_repo):
        calls, _, _ = _edges(corpus_repo)
        edge_set = set(calls)
        assert any(
            s.endswith(":Session.request") and d.endswith(":Session.get")
            for s, d in edge_set), "self.get() inside Session lost"
        assert any(
            s.endswith(":case2_session_get") and d.endswith(":Session.get")
            for s, d in edge_set), "typed s.get() lost"
        assert any(
            s.endswith(":case4_store_update") and d.endswith(":Store.update")
            for s, d in edge_set), "typed st.update() lost"

    def test_nested_shadow_resolves_to_nested_def(self, corpus_repo):
        calls, _, _ = _edges(corpus_repo)
        assert any(
            s.endswith(":case5_shadowed_local")
            and d.endswith(":case5_shadowed_local.get")
            for s, d in calls), (
            "nested `def get` must shadow the module-level decoy")
