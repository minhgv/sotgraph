"""Managed-runtime injection into CodebaseMemoryProvider (P2, programmatic).

Two layers, NO real native binary:
1. A minimal duck-protocol fake proves routing/refusal/zero-spawn rules.
2. The REAL ``ManagedNativeRuntime`` driven by a faked ``run_command``
   proves prepare -> provider.index -> ledger binding -> managed search,
   probe-without-writes, and receipt-failure quarantine end to end.

Zero-spawn is enforced by monkeypatching BOTH spawn sites: the provider's
``run_command`` (legacy path) and the runtime's ``run_command`` (native
one-shot) — any legacy fallback or probe dispatch fails the test loudly.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sot_graph.proc import RunResult
from sot_graph.provider_contract import (
    Capability,
    IntegrationMode,
    ProviderIdentity,
)
from sot_graph.providers import codebase_memory as cbm_mod
from sot_graph.providers import managed as managed_mod
from sot_graph.providers.base import (
    CoverageRequest,
    IndexRequest,
    SymbolRequest,
    TraceRequest,
)
from sot_graph.providers.codebase_memory import (
    NEXT_ACTION_SYNC,
    PROBE_OPERATION,
    CodebaseMemoryProvider,
    ExactCompatibilityContext,
)
from sot_graph.providers.compatibility import (
    CompatibilityRegistry,
    TestedCompatibilityRecord,
)
from sot_graph.providers.managed import ManagedNativeRuntime, ManagedResult
from sot_graph.providers.runtime import ManagedRuntimeProfile

_UNSET = object()

PROTOCOL = "cbm-cli-json-v1"
FIXTURE = "b" * 64
PROVIDER = "codebase-memory"
VERSION = "0.10.8"
PROJECT = "proj"
#: Every operation both sides gate or require at construction.
ALL_OPS = (
    "search_graph", "index_status", "list_projects",
    "config_set_auto_watch", "config_get_auto_watch", "index_repository",
    # Registered-and-tested but NOT managed reads: their gate passes, so the
    # explicit unsupported_managed refusal (not a gate refusal) is exercised.
    "trace_path", "check_index_coverage", PROBE_OPERATION,
)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_exe(directory: Path, body: str = "# fake native artifact\n",
             name: str = "cbm-fake-native") -> str:
    """Plain artifact file: managed dispatches never execute it (only the
    digest gate hashes it), so no exec bit or interpreter is needed."""
    path = Path(directory) / name
    path.write_text(body)
    return str(path)


def make_context(exe: str, ops: tuple[str, ...] = ALL_OPS) -> ExactCompatibilityContext:
    artifact = _sha256_file(exe)
    registry = CompatibilityRegistry()
    for operation in ops:
        registry.register(TestedCompatibilityRecord(
            provider_name=PROVIDER, operation=operation,
            artifact_sha256=artifact, fixture_digest=FIXTURE,
            protocol_compatibility_id=PROTOCOL, version=VERSION,
        ))
    return ExactCompatibilityContext(
        registry=registry,
        runtime_identity=ProviderIdentity(
            name=PROVIDER, version=VERSION,
            mode=IntegrationMode.FEDERATED_CLI,
            capability=Capability.SYMBOLS,
            artifact_sha256=artifact,
            protocol_compatibility_id=PROTOCOL,
        ),
        operation_fixture_digests={op: FIXTURE for op in ops},
        protocol_compatibility_id=PROTOCOL,
    )


def _boom_spawn(*_args, **_kwargs):
    raise AssertionError("unmanaged legacy spawn attempted on a managed path")


@pytest.fixture(autouse=True)
def _forbid_legacy_spawn(monkeypatch):
    """Every test: the provider's own run_command must never fire."""
    monkeypatch.setattr(cbm_mod, "run_command", _boom_spawn)


# ----------------------------------------------------------- protocol fake

def _default_payloads(repo: str) -> dict:
    return {
        "search_graph": {"rows": [{"path": "a.py", "qualified_name": "foo",
                                   "start_line": 1, "end_line": 1,
                                   "kind": "function"}], "has_more": False},
        "list_projects": {"projects": [{"name": PROJECT,
                                        "root_path": repo}],
                          "has_more": False},
        "index_status": {"status": "ready", "head_sha": "h" * 40},
    }


class _FakeProfile:
    def __init__(self, state: str) -> None:
        self._state = state

    def status(self) -> dict:
        return {"state": self._state}


class _FakeInner:
    """The runtime's internal provider seam carrying the trusted context."""

    def __init__(self, exact_context) -> None:
        self._exact = exact_context


class FakeRuntime:
    """Minimal ManagedQueryRuntime duck: records dispatches, never spawns.

    The binding is EXPLICIT — ``_repo``, ``_exe`` and ``_provider._exact``
    are always supplied (the provider refuses injection when any is
    missing); nothing relies on skip-None behavior.
    """

    def __init__(self, repo: str, *, prepared: bool = True,
                 results: dict | None = None, raise_on: str | None = None,
                 exe: str | None = None,
                 exact_context: ExactCompatibilityContext | None = None,
                 fail_prepare: bool = False, fail_sync: bool = False) -> None:
        self._repo = repo
        if exe is None:
            raise ValueError("FakeRuntime requires an explicit exe binding")
        if not isinstance(exact_context, ExactCompatibilityContext):
            raise ValueError("FakeRuntime requires an explicit exact_context")
        self._exe = exe
        self._provider = _FakeInner(exact_context)
        self.calls: list[tuple] = []
        self.results = results or {}
        self.raise_on = raise_on
        self.fail_prepare = fail_prepare
        self.fail_sync = fail_sync
        self._profile = _FakeProfile("READY" if prepared else "UNINITIALIZED")
        self._marker_state = (
            (lambda: ("valid", {"project": PROJECT})) if prepared
            else (lambda: ("absent", None))
        )
        self._defaults = _default_payloads(repo)

    def prepare(self) -> ManagedResult:
        self.calls.append(("prepare",))
        if self.fail_prepare:
            raise RuntimeError("prepare exploded")
        return ManagedResult("ok")

    def query(self, operation: str, args) -> ManagedResult:
        self.calls.append(("query", operation, dict(args)))
        if self.raise_on == operation:
            raise RuntimeError("native failure withheld")
        if self._profile.status()["state"] != "READY":
            return ManagedResult(
                "not_prepared", error="prepare() has not run for this profile")
        return self.results.get(operation) or ManagedResult(
            "ok", self._defaults[operation])

    def sync(self, repo_path: str) -> ManagedResult:
        self.calls.append(("sync", repo_path))
        if self.fail_sync:
            raise RuntimeError("sync exploded")
        return self.results.get("sync") or ManagedResult(
            "ok", {"status": "indexed", "project": PROJECT})


class FakeLedger:
    """Sidecar ledger double capturing the atomic outcome API only."""

    def __init__(self) -> None:
        self.outcomes: list[tuple[dict, dict | None, list]] = []

    def record_provider_outcome(self, run, binding, evidence) -> None:
        self.outcomes.append((dict(run), dict(binding) if binding else None,
                              list(evidence)))

    def get_provider_binding(self, repo, provider):
        for _run, binding, _ev in self.outcomes:
            if binding and binding["sot_repo_id"] in (
                    repo, os.path.realpath(repo)):
                return binding
        return None


def make_env(tmp_path, *, ledger=True, **runtime_kw):
    """One explicit shared binding: the SAME exe + exact-context object is
    given to the fake runtime AND the provider (never skip-None)."""
    repo = str(tmp_path)
    exe = make_exe(tmp_path)
    context = make_context(exe)
    runtime = FakeRuntime(repo, exe=exe, exact_context=context, **runtime_kw)
    got_ledger = FakeLedger() if ledger else None
    provider = CodebaseMemoryProvider(
        command=(exe,), exact_context=context, managed_runtime=runtime,
        db=got_ledger,
    )
    return provider, runtime, got_ledger, repo


class TestInjectionContract:
    def test_requires_exact_context(self, tmp_path):
        exe = make_exe(tmp_path)
        runtime = FakeRuntime(str(tmp_path), exe=exe,
                              exact_context=make_context(exe))
        with pytest.raises(ValueError, match="requires exact_context"):
            CodebaseMemoryProvider(command=(exe,), managed_runtime=runtime)

    def test_rejects_non_protocol_object(self, tmp_path):
        exe = make_exe(tmp_path)
        with pytest.raises(TypeError, match="ManagedQueryRuntime"):
            CodebaseMemoryProvider(
                command=(exe,), exact_context=make_context(exe),
                managed_runtime=object())

    def test_rejects_runtime_without_repo_binding(self, tmp_path):
        class Bare:
            def prepare(self): ...
            def query(self, op, args): ...
            def sync(self, repo): ...
        exe = make_exe(tmp_path)
        with pytest.raises(ValueError, match="bound repo"):
            CodebaseMemoryProvider(
                command=(exe,), exact_context=make_context(exe),
                managed_runtime=Bare())

    def test_rejects_runtime_without_exact_context(self, tmp_path):
        exe = make_exe(tmp_path)
        runtime = FakeRuntime(str(tmp_path), exe=exe,
                              exact_context=make_context(exe))
        runtime._provider = None  # binding seam withheld
        with pytest.raises(ValueError, match="exact-compatibility"):
            CodebaseMemoryProvider(
                command=(exe,), exact_context=make_context(exe),
                managed_runtime=runtime)

    def test_rejects_runtime_without_exe(self, tmp_path):
        exe = make_exe(tmp_path)
        runtime = FakeRuntime(str(tmp_path), exe=exe,
                              exact_context=make_context(exe))
        runtime._exe = None  # executable binding withheld
        with pytest.raises(ValueError, match="executable binding"):
            CodebaseMemoryProvider(
                command=(exe,), exact_context=make_context(exe),
                managed_runtime=runtime)

    def test_rejects_divergent_executable(self, tmp_path):
        exe = make_exe(tmp_path)
        other = make_exe(tmp_path, body="# other artifact\n",
                         name="cbm-other-native")
        # SAME trusted context object; only the runtime's exe binding
        # diverges, so the executable check (not the context check) fires.
        with pytest.raises(ValueError, match="differs from the provider"):
            CodebaseMemoryProvider(
                command=(exe,), exact_context=make_context(exe),
                managed_runtime=FakeRuntime(
                    str(tmp_path), exe=other,
                    exact_context=make_context(exe)))

    def test_rejects_non_equivalent_context(self, tmp_path):
        exe = make_exe(tmp_path)
        runtime_ctx = make_context(exe)  # full op set
        partial_ctx = make_context(exe, ops=("search_graph",))
        with pytest.raises(ValueError, match="not the trusted context"):
            CodebaseMemoryProvider(
                command=(exe,), exact_context=runtime_ctx,
                managed_runtime=FakeRuntime(
                    str(tmp_path), exe=exe, exact_context=partial_ctx))

    def test_accepts_equivalent_context(self, tmp_path):
        # A DIFFERENT registry object carrying byte-identical records and
        # identical identity/digests/protocol id is equivalent: accepted.
        exe = make_exe(tmp_path)
        provider, runtime, _ledger, repo = make_env(tmp_path)
        runtime._provider = _FakeInner(make_context(exe))
        out = provider.search_symbols(
            SymbolRequest(repo_root=repo, query="x", project=PROJECT))
        assert out.ok


class TestManagedRoutingZeroSpawn:
    @pytest.fixture()
    def env(self, tmp_path):
        return make_env(tmp_path)

    def test_search_routes_allowlisted_args(self, env):
        provider, runtime, ledger, repo = env
        out = provider.search_symbols(
            SymbolRequest(repo_root=repo, query="foo", project=PROJECT))
        assert out.ok and out.payload["rows"][0]["qualified_name"] == "foo"
        # search + the snapshot_bind nested index_status; NEVER list/prepare.
        assert runtime.calls == [
            ("query", "search_graph", {"query": "foo"}),
            ("query", "index_status", {}),
        ]
        assert ledger.outcomes == []  # queries never write the ledger
        assert out.metadata["identity_basis"] == "artifact_verified"
        assert out.metadata["wire_status"] == "ok"

    def test_trace_explicit_unsupported_no_fallback(self, env):
        provider, runtime, _ledger, repo = env
        out = provider.trace(TraceRequest(repo_root=repo, symbol="foo"))
        assert not out.ok
        assert out.metadata["wire_status"] == "unsupported_managed"
        assert "legacy fallback" in (out.error or "")
        # Only the project-resolution read ran; no trace dispatch, no legacy
        # spawn (the autouse guard would fail the test on either).
        assert runtime.calls == [("query", "list_projects", {})]

    def test_coverage_explicit_unsupported_no_fallback(self, env):
        provider, runtime, _ledger, repo = env
        out = provider.coverage(
            CoverageRequest(repo_root=repo, paths=("a.py",)))
        assert not out.ok
        assert out.metadata["wire_status"] == "unsupported_managed"
        assert runtime.calls == [("query", "list_projects", {})]

    def test_probe_prepared_reads_state_only(self, env):
        provider, runtime, _ledger, repo = env
        status = provider.probe(repo)
        assert status.healthy and status.installed
        assert status.version is None  # --version stays an explicit diagnostic
        assert "no --version" in status.detail
        assert runtime.calls == []  # no dispatch of any kind

    def test_probe_unprepared_unhealthy(self, tmp_path):
        provider, runtime, _ledger, repo = make_env(tmp_path, prepared=False)
        status = provider.probe(repo)
        assert not status.healthy
        assert "not prepared" in status.detail
        assert runtime.calls == []

    def test_repo_mismatch_refuses_without_dispatch(self, env, tmp_path):
        provider, runtime, ledger, _repo = env
        out = provider.search_symbols(
            SymbolRequest(repo_root=str(tmp_path / "elsewhere"), query="x"))
        assert not out.ok
        assert ledger.outcomes == []
        assert runtime.calls == []

    def test_command_mutation_refused(self, env):
        provider, runtime, _ledger, repo = env
        provider.command = ("mutated",)
        out = provider.search_symbols(
            SymbolRequest(repo_root=repo, query="x", project=PROJECT))
        assert not out.ok
        assert runtime.calls == []

    def test_runtime_exception_honest(self, env):
        provider, _runtime, ledger, repo = env
        provider._managed.raise_on = "search_graph"
        out = provider.search_symbols(
            SymbolRequest(repo_root=repo, query="x", project=PROJECT))
        assert not out.ok
        assert out.metadata["wire_status"] == "runtime_refused"
        assert "RuntimeError" in (out.error or "")
        assert ledger.outcomes == []

    def test_runtime_gate_refusal_not_artifact_verified(self, env):
        provider, _runtime, _ledger, repo = env
        provider._managed.results["search_graph"] = ManagedResult(
            "gate_refused", error="refused before dispatch")
        out = provider.search_symbols(
            SymbolRequest(repo_root=repo, query="x", project=PROJECT))
        assert not out.ok
        assert out.metadata["wire_status"] == "compatibility_unknown"
        assert out.metadata["identity_basis"] == "unverified"

    def test_timeout_carries_cancellation_state(self, env):
        provider, _runtime, _ledger, repo = env
        provider._managed.results["search_graph"] = ManagedResult(
            "timeout", None, "search_graph deadline expired; "
            "native diagnostic withheld", "cancellation_unknown")
        out = provider.search_symbols(
            SymbolRequest(repo_root=repo, query="x", project=PROJECT))
        assert not out.ok
        assert out.metadata["wire_status"] == "timeout"
        assert "cancellation_unknown" in (out.error or "")

    def test_unprepared_query_points_to_sync_never_prepares(self, tmp_path):
        provider, runtime, _ledger, repo = make_env(tmp_path, prepared=False)
        out = provider.search_symbols(
            SymbolRequest(repo_root=repo, query="x"))
        assert not out.ok
        # Project resolution degrades the not_prepared read to an honest
        # abstention pointing at the explicit sync path.
        assert out.metadata["wire_status"] == "abstained"
        assert out.next_action == NEXT_ACTION_SYNC
        # Only the resolution read ran; no prepare, no search dispatch.
        assert runtime.calls == [("query", "list_projects", {})]


# ------------------------------------- real ManagedNativeRuntime integration

def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(("git", "-C", repo, *args), check=True,
                          capture_output=True, text=True)
    return proc.stdout.strip()


def make_git_repo(tmp_path: Path) -> tuple[str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(str(repo), "init", "-q")
    _git(str(repo), "config", "user.email", "p2@test")
    _git(str(repo), "config", "user.name", "P2 Test")
    (repo / "a.py").write_text("def foo():\n    return 1\n")
    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-q", "-m", "init")
    return str(repo), _git(str(repo), "rev-parse", "HEAD")


def runtime_root() -> str:
    """Short, symlink-free, ABSOLUTE profile root (native sun_path budget).

    TMPDIR on macOS lives under /var/folders (far over the budget), so the
    profile root uses the realpath of /tmp instead.
    """
    base = os.path.realpath("/tmp") if os.path.isdir("/tmp") \
        else os.path.realpath(tempfile.gettempdir())
    root = os.path.join(base, f"sot-p2-{os.getuid()}")
    if len(root) > 27:
        pytest.skip(f"temp path too long for managed IPC budget: {root}")
    os.makedirs(root, mode=0o700, exist_ok=True)
    return root


class FakeNativeRunner:
    """Stands in for ``managed.run_command``: emulates the plain-CLI wire.

    ``index_status_head=None`` emulates a native that reports NO head_sha
    (no-op fake index); any other value is the native-reported head.
    """

    def __init__(self, repo: str, head: str, *, index_receipt: dict | None = None,
                 index_status_head: Any = _UNSET) -> None:
        self.repo, self.head = repo, head
        self.index_receipt = index_receipt or {"status": "indexed",
                                               "project": PROJECT}
        # _UNSET -> report the repo head; None -> report NO head_sha at all.
        self.index_status_head = self.head if index_status_head is _UNSET \
            else index_status_head
        self.argvs: list[list[str]] = []

    def __call__(self, argv, cwd=None, env=None, timeout_seconds=None,
                 max_output_bytes=None) -> RunResult:
        self.argvs.append(list(argv))
        res = lambda rc=0, out="": RunResult(  # noqa: E731
            argv=tuple(argv), returncode=rc, stdout=out, stderr="",
            timed_out=False, truncated=False, error=None)
        if argv[1:4] == ["config", "set", "auto_watch"]:
            db = Path(env["CBM_CACHE_DIR"]) / "_config.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO config VALUES ('auto_watch', 'false')")
            conn.commit()
            conn.close()
            return res(0, "ok\n")
        if argv[1:4] == ["config", "get", "auto_watch"]:
            return res(0, "false")
        if argv[1] == "cli":
            tool = argv[2]
            if tool == "index_repository":
                assert argv[3] == "--repo-path" and argv[4] == self.repo
                return res(0, json.dumps(self.index_receipt))
            args_file = argv[argv.index("--args-file") + 1]
            args = json.loads(Path(args_file).read_text())
            if tool == "list_projects":
                return res(0, json.dumps(
                    {"projects": [{"name": PROJECT, "root_path": self.repo}],
                     "has_more": False, "next_cursor": None}))
            if tool == "index_status":
                payload: dict = {"status": "ready"}
                if self.index_status_head is not None:
                    payload["head_sha"] = self.index_status_head
                    payload["branch"] = "master"
                return res(0, json.dumps(payload))
            if tool == "search_graph":
                assert args["project"] == PROJECT and args["format"] == "json"
                return res(0, json.dumps(
                    {"rows": [{"path": "a.py", "qualified_name": "foo",
                               "start_line": 1, "end_line": 1,
                               "kind": "function"}], "has_more": False}))
        return res(1, "")


class ManagedFixture:
    """Real profile + real ManagedNativeRuntime over the faked native wire."""

    def __init__(self, tmp_path: Path, monkeypatch, *,
                 index_receipt: dict | None = None,
                 index_status_head: Any = _UNSET) -> None:
        self.repo, self.head = make_git_repo(tmp_path)
        self.exe = make_exe(tmp_path)
        context = make_context(self.exe)  # ONE trusted context object
        self.profile = ManagedRuntimeProfile(
            runtime_root(), self.repo, artifact_digest=_sha256_file(self.exe))
        self.runtime = ManagedNativeRuntime(
            self.profile, self.repo, (self.exe,), context)
        self.runner = FakeNativeRunner(self.repo, self.head,
                                       index_receipt=index_receipt,
                                       index_status_head=index_status_head)
        monkeypatch.setattr(managed_mod, "run_command", self.runner)
        self.ledger = FakeLedger()
        self.provider = CodebaseMemoryProvider(
            command=(self.exe,), exact_context=context,
            managed_runtime=self.runtime, db=self.ledger)


@pytest.fixture()
def real_env(tmp_path, monkeypatch):
    fx = ManagedFixture(tmp_path, monkeypatch)
    yield fx
    shutil.rmtree(fx.profile.namespace, ignore_errors=True)


class TestRealManagedRuntime:
    def test_prepare_index_publishes_ledger_binding(self, real_env):
        fx = real_env
        record = fx.provider.index(IndexRequest(repo_root=fx.repo))
        assert record.status == "ok"
        # The runner saw the exact managed wire: gate set/get, then the
        # bound-repo index dispatch.
        assert fx.runner.argvs[0][1:4] == ["config", "set", "auto_watch"]
        assert fx.runner.argvs[1][1:4] == ["config", "get", "auto_watch"]
        assert fx.runner.argvs[2][1:3] == ["cli", "index_repository"]
        assert fx.runner.argvs[2][3:5] == ["--repo-path", fx.repo]
        # Ledger got the run AND the verified project binding.
        assert len(fx.ledger.outcomes) == 1
        run, binding, _ev = fx.ledger.outcomes[0]
        assert run["status"] == "ok"
        assert binding["provider_project_id"] == PROJECT
        assert binding["head_sha"] == fx.head
        assert fx.profile.status()["state"] == "READY"
        assert fx.runtime._marker_state()[1].get("project") == PROJECT

    def test_search_after_index_is_snapshot_bound_fresh(self, real_env):
        fx = real_env
        assert fx.provider.index(IndexRequest(repo_root=fx.repo)).status == "ok"
        runs_before = len(fx.ledger.outcomes)
        out = fx.provider.search_symbols(
            SymbolRequest(repo_root=fx.repo, query="foo"))
        assert out.ok and out.payload["rows"][0]["qualified_name"] == "foo"
        assert out.metadata["snapshot_bound"] is True
        assert out.metadata["freshness"] == "FRESH"
        assert out.metadata["snapshot"]["cbm_head_sha"] == fx.head
        assert len(fx.ledger.outcomes) == runs_before  # queries write nothing

    def test_probe_after_prepare_dispatches_nothing(self, real_env):
        fx = real_env
        assert fx.provider.index(IndexRequest(repo_root=fx.repo)).status == "ok"
        spawns = len(fx.runner.argvs)
        status = fx.provider.probe(fx.repo)
        assert status.healthy and status.version is None
        assert len(fx.runner.argvs) == spawns  # probe performed zero dispatches

    def test_probe_before_prepare_never_writes(self, tmp_path, monkeypatch):
        fx = ManagedFixture(tmp_path, monkeypatch)
        try:
            status = fx.provider.probe(fx.repo)
            assert not status.healthy
            assert "not prepared" in status.detail
            assert fx.runner.argvs == []  # no native call on unprepared profile
            assert fx.profile.status()["initialized"] is False  # no write
        finally:
            shutil.rmtree(fx.profile.namespace, ignore_errors=True)

    def test_sync_receipt_failure_quarantines_and_persists(
            self, tmp_path, monkeypatch):
        fx = ManagedFixture(tmp_path, monkeypatch,
                            index_receipt={"status": "nope"})
        try:
            record = fx.provider.index(IndexRequest(repo_root=fx.repo))
            assert record.status == "provider_error"
            assert len(fx.ledger.outcomes) == 1
            run, binding, _ev = fx.ledger.outcomes[0]
            assert run["status"] == "provider_error"
            assert binding is None  # rc=0 alone never publishes a binding
            assert fx.profile.status()["state"] == "QUARANTINED"
        finally:
            shutil.rmtree(fx.profile.namespace, ignore_errors=True)

    def test_dirty_worktree_preserves_false_stale_binding(self, real_env):
        fx = real_env
        # Uncommitted edit BEFORE sync: the index cannot prove content
        # freshness, so the run persists ok but NO binding is published.
        Path(fx.repo, "a.py").write_text("def foo():\n    return 2\n")
        record = fx.provider.index(IndexRequest(repo_root=fx.repo))
        assert record.status == "ok"
        run, binding, _ev = fx.ledger.outcomes[0]
        assert run["status"] == "ok"
        assert binding is None  # false-stale binding stays absent


class TestNativeHeadProof:
    """Managed binding publication requires INDEPENDENT native proof: the
    SOT HEAD alone never publishes, and the ledger-stored head is never
    treated as native index_status output."""

    def test_index_persists_unknown_native_exit(self, real_env):
        fx = real_env
        record = fx.provider.index(IndexRequest(repo_root=fx.repo))
        assert record.status == "ok"
        run, _binding, _ev = fx.ledger.outcomes[0]
        assert run["exit_code"] is None  # never a fabricated 0/1
        assert record.exit_code is None

    def test_native_head_missing_publishes_no_binding_never_fresh(
            self, tmp_path, monkeypatch):
        fx = ManagedFixture(tmp_path, monkeypatch, index_status_head=None)
        try:
            # Receipt says indexed; the native reports NO head_sha at all.
            assert fx.provider.index(IndexRequest(repo_root=fx.repo)).status == "ok"
            _run, binding, _ev = fx.ledger.outcomes[0]
            assert binding is None  # no SOT-head-only publication
            out = fx.provider.search_symbols(
                SymbolRequest(repo_root=fx.repo, query="foo"))
            assert out.ok
            assert out.metadata["snapshot_bound"] is False
            assert out.metadata["freshness"] == "UNBOUND"  # not FRESH
        finally:
            shutil.rmtree(fx.profile.namespace, ignore_errors=True)

    def test_noop_index_stale_native_head_not_fresh(self, tmp_path,
                                                    monkeypatch):
        # A no-op fake index: receipt claims indexed, but the native
        # index_status head still points at an OLD commit.
        fx = ManagedFixture(tmp_path, monkeypatch,
                            index_status_head="0" * 40)
        try:
            assert fx.provider.index(IndexRequest(repo_root=fx.repo)).status == "ok"
            _run, binding, _ev = fx.ledger.outcomes[0]
            assert binding is None  # native head != SOT head: no publication
            out = fx.provider.search_symbols(
                SymbolRequest(repo_root=fx.repo, query="foo"))
            assert out.ok
            assert out.metadata["snapshot_bound"] is True
            assert out.metadata["freshness"] == "STALE"  # bound, NOT FRESH
        finally:
            shutil.rmtree(fx.profile.namespace, ignore_errors=True)

    def test_matching_native_head_still_publishes_fresh(self, real_env):
        # Conservative current behavior kept: when the independent native
        # index_status DOES report the same head, publication works.
        fx = real_env
        assert fx.provider.index(IndexRequest(repo_root=fx.repo)).status == "ok"
        _run, binding, _ev = fx.ledger.outcomes[0]
        assert binding is not None and binding["head_sha"] == fx.head


class TestManagedReceiptRobustness:
    """Runtime exceptions become safe non-ok receipts, persisted, never
    raised past the provider index() surface."""

    def test_prepare_exception_persists_nonok_receipt(self, tmp_path):
        provider, runtime, ledger, repo = make_env(tmp_path,
                                                   fail_prepare=True)
        record = provider.index(IndexRequest(repo_root=repo))
        assert record.status == "provider_error"
        assert "prepare raised" in record.detail
        assert len(ledger.outcomes) == 1
        run, binding, _ev = ledger.outcomes[0]
        assert run["status"] == "provider_error"
        assert run["exit_code"] is None
        assert binding is None
        assert runtime.calls == [("prepare",)]  # no query ever ran

    def test_sync_exception_persists_nonok_receipt(self, tmp_path):
        provider, runtime, ledger, repo = make_env(tmp_path, fail_sync=True)
        record = provider.index(IndexRequest(repo_root=repo))
        assert record.status == "provider_error"
        assert "sync raised" in record.detail
        assert len(ledger.outcomes) == 1
        _run, binding, _ev = ledger.outcomes[0]
        assert binding is None


class TestManagedProbeAdvertisement:
    def test_capabilities_intersected_with_managed_served(self, tmp_path):
        exe = make_exe(tmp_path)
        context = make_context(exe)
        config = SimpleNamespace(
            command=None, timeout_seconds=None,
            capabilities=["symbols", "trace", "pdg", "source-verification"],
        )
        runtime = FakeRuntime(str(tmp_path), exe=exe, exact_context=context)
        provider = CodebaseMemoryProvider(
            config, command=(exe,), exact_context=context,
            managed_runtime=runtime)
        status = provider.probe(str(tmp_path))
        assert status.healthy
        # Only the managed-served intersection is advertised: symbols
        # (search_graph) and source-verification (index_status binding).
        assert status.capabilities == ("symbols", "source-verification")

    def test_probe_requires_served_operation_evidence(self, tmp_path):
        # A --version-only evidence set can NEVER satisfy the managed
        # probe: the gate is assessed against the served index_status op.
        exe = make_exe(tmp_path)
        context = make_context(exe, ops=(PROBE_OPERATION,))
        runtime = FakeRuntime(str(tmp_path), exe=exe, exact_context=context)
        provider = CodebaseMemoryProvider(
            command=(exe,), exact_context=context, managed_runtime=runtime)
        status = provider.probe(str(tmp_path))
        assert not status.healthy
        assert "index_status exact-compatibility" in status.detail
        assert runtime.calls == []
