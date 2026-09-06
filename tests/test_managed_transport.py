"""P1.2 (master plan §7.2) — MCP stdio as the DEFAULT managed read transport.

Hermetic: the engine MCP side is a stub python process spawned via
``sys.executable`` (never a shebang path); the plain-CLI fallback wire is a
faked ``run_command`` (no real binary, no network, no shell). Covers: auto
(mcp ok / handshake fail / missing tool -> cli fallback), strict ``mcp``
(no silent fallback), ``cli`` (MCP never spawned), invalid env value, and the
additive transport provenance in the managed run receipt.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.proc import RunResult  # noqa: E402
from sot_graph.provider_contract import (  # noqa: E402
    Capability,
    IntegrationMode,
    ProviderIdentity,
)
from sot_graph.providers.codebase_memory import (  # noqa: E402
    CodebaseMemoryProvider,
    ExactCompatibilityContext,
)
from sot_graph.providers.compatibility import (  # noqa: E402
    CompatibilityRegistry,
    TestedCompatibilityRecord,
)
from sot_graph.providers.managed import ManagedNativeRuntime  # noqa: E402
from sot_graph.providers.managed import QUERY_OPERATIONS  # noqa: E402
from sot_graph.providers.runtime import ManagedRuntimeProfile  # noqa: E402

_SHORT_BASES = ("/private/tmp", "/tmp")
FIXTURE = "b" * 64
PROTOCOL = "cbm-cli-json-v1"
VERSION = "0.10.8"
PROVIDER = "codebase-memory"
ALL_OPS = sorted(QUERY_OPERATIONS | {"config_set_auto_watch",
                                     "config_get_auto_watch", "index_repository"})
SEARCH_PAYLOAD = {"rows": [{"qualified_name": "mod.func", "path": "src/mod.py",
                            "start_line": 1, "end_line": 1, "kind": "function"}],
                  "has_more": False}


@pytest.fixture
def make_root():
    created: list[Path] = []

    def _make() -> Path:
        for base in _SHORT_BASES:  # native socket-path byte budget
            if Path(base).is_dir():
                root = Path(base) / f"mt{uuid.uuid4().hex[:10]}"
                created.append(root)
                return root
        pytest.skip("no short symlink-free temp base available")

    yield _make
    for root in created:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_transport_env(monkeypatch):
    monkeypatch.delenv("SOT_ENGINE_TRANSPORT", raising=False)


# ------------------------------------------------------- fake CLI native wire

class FakeNative:
    """Stands in for sot_graph.proc.run_command; records every CLI dispatch."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._env: dict[str, str] = {}
        self.repo: str | None = None

    def __call__(self, argv, cwd=None, env=None, timeout_seconds=None,
                 max_output_bytes=None, **_kw):
        args_content = None
        if "--args-file" in argv:
            path = Path(argv[argv.index("--args-file") + 1])
            args_content = path.read_text(encoding="utf-8") if path.exists() else None
        self.calls.append({"argv": list(argv), "cwd": cwd,
                           "env": dict(env or {}), "args_content": args_content})
        self._env = dict(env or {})
        return self._receipts(list(argv))

    def _receipts(self, argv: list[str]) -> RunResult:
        if argv[1:3] == ["config", "set"]:
            self._persist_config_db()
            return _rc0("auto_watch=false\n")
        if argv[1:3] == ["config", "get"]:
            return _rc0("false\n")
        if argv[1:3] == ["cli", "index_repository"]:
            return _rc0(json.dumps({"project": "proj", "nodes": 1, "edges": 2,
                                    "status": "indexed"}) + "\n")
        if argv[1:3] == ["cli", "list_projects"]:
            args = json.loads(self.calls[-1]["args_content"] or "{}")
            assert "project" not in args, "list_projects received a project key"
            return _rc0(json.dumps(
                {"projects": [{"name": "proj", "root_path": self.repo}],
                 "has_more": False}) + "\n")
        return _rc0(json.dumps(SEARCH_PAYLOAD) + "\n")

    def _persist_config_db(self) -> None:
        cache = self._env.get("CBM_CACHE_DIR")
        if not cache:
            return
        db = Path(cache) / "_config.db"
        for sidecar in ("-wal", "-shm"):
            Path(str(db) + sidecar).unlink(missing_ok=True)
        db.unlink(missing_ok=True)
        conn = sqlite3.connect(db)
        try:
            conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO config VALUES ('auto_watch', 'false')")
            conn.commit()
        finally:
            conn.close()


def _rc0(stdout: str) -> RunResult:
    return RunResult(argv=(), returncode=0, stdout=stdout, stderr="",
                     timed_out=False, truncated=False, error=None)


@pytest.fixture()
def native(monkeypatch):
    fake = FakeNative()
    import sot_graph.providers.managed as managed
    monkeypatch.setattr(managed, "run_command", fake)
    return fake


# ------------------------------------------------------------ fixture builders

def _mk_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "mod.py").write_text("x = 1\n", encoding="utf-8")
    return repo


def _make_exe(directory: Path) -> tuple[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cbm-fake"
    body = b"#!/bin/fake-cbm\n"  # never executed; hashed only
    path.write_bytes(body)
    return str(path), hashlib.sha256(body).hexdigest()


def _context(artifact: str) -> ExactCompatibilityContext:
    registry = CompatibilityRegistry()
    for operation in ALL_OPS:
        registry.register(TestedCompatibilityRecord(
            provider_name=PROVIDER, operation=operation,
            artifact_sha256=artifact, fixture_digest=FIXTURE,
            protocol_compatibility_id=PROTOCOL, version=VERSION))
    return ExactCompatibilityContext(
        registry=registry,
        runtime_identity=ProviderIdentity(
            name=PROVIDER, version=VERSION, mode=IntegrationMode.FEDERATED_CLI,
            capability=Capability.SYMBOLS, artifact_sha256=artifact,
            protocol_compatibility_id=PROTOCOL),
        operation_fixture_digests={op: FIXTURE for op in ALL_OPS},
        protocol_compatibility_id=PROTOCOL)


def _prepared(root_factory, tmp_path, native):
    """Runtime through prepare + sync (verified binding), CLI calls cleared."""
    root = root_factory()
    repo = _mk_repo(tmp_path / "w")
    exe, digest = _make_exe(tmp_path / "bin")
    context = _context(digest)
    profile = ManagedRuntimeProfile(str(root), str(repo), artifact_digest=digest)
    runtime = ManagedNativeRuntime(profile, str(repo), (exe,), context)
    native.repo = str(repo)
    assert runtime.prepare().status == "ok"
    assert runtime.sync(str(repo)).status == "ok"
    native.calls.clear()
    return runtime, profile, repo, exe, context


# ------------------------------------------------------------------ MCP stubs

_OK_STUB = textwrap.dedent("""
    import json, sys
    log = open(sys.argv[1], "a", encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        log.write(json.dumps(msg) + "\\n")
        log.flush()
        method = msg.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {},
                      "serverInfo": {"name": "stub-engine", "version": "0.1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "search_graph"}, {"name": "index_status"},
                                {"name": "list_projects"}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": PAYLOAD_JSON}],
                      "isError": False}
        else:
            if "id" not in msg:
                continue
            result = {}
        sys.stdout.write(json.dumps(
            {"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\\n")
        sys.stdout.flush()
""").replace("PAYLOAD_JSON", json.dumps(json.dumps(SEARCH_PAYLOAD)))

_DEAD_STUB = "import time\ntime.sleep(60)\n"

_NOTOOL_STUB = _OK_STUB.replace('{"name": "search_graph"}, ', "")


def _wrap_mcp(monkeypatch, tmp_path, body: str, timeout: float = 5.0):
    """Route managed.py's EngineMcpClient at a stub script; never a shebang."""
    import sot_graph.providers.engine_mcp as em
    script = tmp_path / "stub_engine.py"
    script.write_text(body, encoding="utf-8")
    log = tmp_path / "rpc.log"
    state = {"spawned": False}

    class Wrapped(em.EngineMcpClient):
        def __init__(self, executable, args=(), env=None, timeout_s=20.0, **kw):
            state["spawned"] = True
            super().__init__(sys.executable, args=(str(script), str(log)),
                             env=env, timeout_s=timeout, **kw)

    monkeypatch.setattr(em, "EngineMcpClient", Wrapped)
    return state, log


def _rpc_log(log: Path) -> list[dict]:
    return [json.loads(line) for line in
            log.read_text(encoding="utf-8").splitlines() if line.strip()]


# ----------------------------------------------------------------- the tests

def test_auto_mcp_ok_serves_search_without_cli(tmp_path, make_root, native,
                                               monkeypatch):
    runtime, _profile, repo, _exe, _ctx = _prepared(make_root, tmp_path, native)
    state, log = _wrap_mcp(monkeypatch, tmp_path, _OK_STUB)
    result = runtime.query("search_graph", {"query": "func"})
    assert result.status == "ok"
    assert result.transport == "mcp"
    assert result.fallback_reason is None
    assert result.payload == SEARCH_PAYLOAD
    assert state["spawned"] is True
    assert native.calls == []  # the CLI wire was never taken
    requests = _rpc_log(log)
    methods = [m.get("method") for m in requests]
    assert methods[0] == "initialize"
    assert "notifications/initialized" in methods
    assert methods.count("tools/list") == 1
    calls = [m for m in requests if m.get("method") == "tools/call"]
    assert len(calls) == 1
    assert calls[0]["params"]["name"] == "search_graph"
    args = calls[0]["params"]["arguments"]
    assert args["query"] == "func"
    assert args["project"] == "proj"  # verified binding injected, not caller args
    assert args["format"] == "json"
    assert args["limit"] == 20


def test_auto_mcp_handshake_fail_falls_back_to_cli(tmp_path, make_root, native,
                                                   monkeypatch):
    runtime, _profile, _repo, _exe, _ctx = _prepared(make_root, tmp_path, native)
    _state, _log = _wrap_mcp(monkeypatch, tmp_path, _DEAD_STUB, timeout=2.0)
    result = runtime.query("search_graph", {"query": "func"})
    assert result.status == "ok"
    assert result.transport == "cli"
    assert result.fallback_reason  # honest bounded reason for the fallback
    assert len(native.calls) == 1  # exactly one CLI fallback dispatch
    assert native.calls[0]["argv"][1:3] == ["cli", "search_graph"]


def test_auto_missing_tool_falls_back_to_cli(tmp_path, make_root, native,
                                             monkeypatch):
    runtime, _profile, _repo, _exe, _ctx = _prepared(make_root, tmp_path, native)
    _state, _log = _wrap_mcp(monkeypatch, tmp_path, _NOTOOL_STUB)
    result = runtime.query("search_graph", {"query": "func"})
    assert result.status == "ok"
    assert result.transport == "cli"
    assert "no search_graph tool" in result.fallback_reason
    assert len(native.calls) == 1


def test_auto_transport_contract_breach_falls_back_to_cli(tmp_path, make_root,
                                                          native, monkeypatch):
    """A transport raising outside EngineMcpError (e.g. an intercepted Popen
    surface, SUR-02/10/11 style) is still just a failed MCP attempt: the read
    falls back to the CLI wire instead of crashing the dispatch."""
    import sot_graph.providers.engine_mcp as em
    runtime, _profile, _repo, _exe, _ctx = _prepared(make_root, tmp_path, native)

    class Breached(em.EngineMcpClient):
        def start(self):
            raise RuntimeError("synthetic transport contract breach")

    monkeypatch.setattr(em, "EngineMcpClient", Breached)
    result = runtime.query("search_graph", {"query": "func"})
    assert result.status == "ok"
    assert result.transport == "cli"
    assert "contract breach" in result.fallback_reason
    assert len(native.calls) == 1
    assert native.calls[0]["argv"][1:3] == ["cli", "search_graph"]


def test_cli_env_never_spawns_mcp(tmp_path, make_root, native, monkeypatch):
    runtime, _profile, _repo, _exe, _ctx = _prepared(make_root, tmp_path, native)
    monkeypatch.setenv("SOT_ENGINE_TRANSPORT", "cli")
    state, _log = _wrap_mcp(monkeypatch, tmp_path, _OK_STUB)
    result = runtime.query("search_graph", {"query": "func"})
    assert result.status == "ok"
    assert state["spawned"] is False  # old behaviour: CLI only, no MCP attempt
    assert result.transport is None  # transport selection never ran
    assert len(native.calls) == 1


def test_strict_mcp_fail_refuses_without_cli_fallback(tmp_path, make_root,
                                                      native, monkeypatch):
    runtime, _profile, _repo, _exe, _ctx = _prepared(make_root, tmp_path, native)
    monkeypatch.setenv("SOT_ENGINE_TRANSPORT", "mcp")
    _state, _log = _wrap_mcp(monkeypatch, tmp_path, _DEAD_STUB, timeout=2.0)
    result = runtime.query("search_graph", {"query": "func"})
    assert result.status == "runtime_refused"
    assert result.transport == "mcp"
    assert "no CLI fallback" in result.error
    assert "Traceback" not in result.error  # controlled clean message
    assert native.calls == []  # strict: the CLI wire is NEVER taken


def test_invalid_transport_env_refuses_before_any_spawn(tmp_path, make_root,
                                                        native, monkeypatch):
    runtime, _profile, _repo, _exe, _ctx = _prepared(make_root, tmp_path, native)
    monkeypatch.setenv("SOT_ENGINE_TRANSPORT", "grpc")
    state, _log = _wrap_mcp(monkeypatch, tmp_path, _OK_STUB)
    result = runtime.query("search_graph", {"query": "func"})
    assert result.status == "runtime_refused"
    assert "auto|mcp|cli" in result.error
    assert state["spawned"] is False
    assert native.calls == []


def test_receipt_records_transport_and_fallback(tmp_path, make_root, native,
                                                monkeypatch):
    runtime, _profile, repo, exe, context = _prepared(make_root, tmp_path,
                                                      native)
    provider = CodebaseMemoryProvider(command=(exe,), exact_context=context,
                                      managed_runtime=runtime)
    # MCP success path -> receipt says transport=mcp
    _wrap_mcp(monkeypatch, tmp_path, _OK_STUB)
    outcome = provider._managed_invoke(
        "search_graph", {"query": "func"}, repo_root=str(repo),
        project="proj", snapshot_bind=False, gate=None)
    assert outcome.ok
    assert "transport=mcp" in outcome.run.detail

    # Missing tool -> CLI fallback -> receipt says transport=cli + why
    _wrap_mcp(monkeypatch, tmp_path, _NOTOOL_STUB)
    outcome = provider._managed_invoke(
        "search_graph", {"query": "func"}, repo_root=str(repo),
        project="proj", snapshot_bind=False, gate=None)
    assert outcome.ok
    assert "transport=cli" in outcome.run.detail
    assert "(fallback: " in outcome.run.detail
