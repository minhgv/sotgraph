"""M4 SUR-02/05/10/11 synthetic integration, not M5 native/version evidence.

Trusted config, dispatch, runtime and proc are real Python paths. Popen is
intercepted: no native binary, public listener, browser or network is launched.
The registry and native receipts are synthetic and confer no release support.
"""
import io
import json
import socket
import webbrowser
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_managed_execution as execution
import test_trusted_managed_config as trusted
from sot_graph.assurance.orchestrator import managed_read_dispatch
from sot_graph.providers import trusted_config as config
from sot_graph.providers.managed import ManagedNativeRuntime
from sot_graph.providers.runtime import ManagedRuntimeProfile

_PREPARE = ManagedNativeRuntime.prepare
_INITIALIZE = ManagedRuntimeProfile.initialize
trusted_lab = trusted.trusted_lab


@pytest.fixture
def surface(trusted_lab, monkeypatch):
    """Reuse inert trusted artifact and filesystem receipts, intercept at Popen."""
    lab = trusted_lab
    # Snapshot these captured paths, not os.environ at teardown: the injection
    # case deliberately replaces HOME again and monkeypatch restores it later.
    homes = lab.repo.parent / "surface-homes"
    for variable, directory in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                                ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data"),
                                ("XDG_STATE_HOME", "state"), ("XDG_RUNTIME_DIR", "runtime")):
        path = homes / directory
        path.mkdir(parents=True, mode=0o700)
        (path / "preexisting").write_text("synthetic user state\n")
        monkeypatch.setenv(variable, str(path))

    def home_snapshot():
        return {str(path.relative_to(homes)): (
            path.stat().st_mode, path.read_bytes() if path.is_file() else None
        ) for path in homes.rglob("*")}

    before_homes = home_snapshot()
    monkeypatch.setattr(ManagedNativeRuntime, "prepare", _PREPARE)
    monkeypatch.setattr(ManagedRuntimeProfile, "initialize", _INITIALIZE)
    native = execution.FakeNative()
    children = []

    def forbidden(*args, **kwargs):
        pytest.fail("Python surface attempted a listener, network or browser action")

    monkeypatch.setattr(socket.socket, "bind", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)

    def popen(argv, **kwargs):
        # Exercise real proc.run_command replacement env, not merely the
        # runtime's environment() return value. No real child exists here.
        native.repo = kwargs["cwd"]
        result = native(argv, cwd=kwargs["cwd"], env=kwargs["env"])
        if argv[1:3] == ["cli", "search_graph"]:
            result = execution._rc0(json.dumps({"cols": ["qn", "file", "label"], "rows": [["target", "app.py", "function"]], "has_more": False}))
        children.append((list(argv), dict(kwargs)))
        return SimpleNamespace(stdout=io.BytesIO(result.stdout.encode()),
                               stderr=io.BytesIO(result.stderr.encode()),
                               returncode=result.returncode,
                               poll=lambda: result.returncode,
                               wait=lambda **kw: result.returncode)

    monkeypatch.setattr("subprocess.Popen", popen)
    installation = config.register_managed_installation(lab.repo, **lab.kwargs)
    assert installation.runtime.prepare().status == "ok"
    assert installation.runtime.sync(str(lab.repo)).status == "ok"
    children.clear()
    native.calls.clear()
    try:
        yield SimpleNamespace(lab=lab, installation=installation,
                              native=native, children=children)
    finally:
        assert home_snapshot() == before_homes


def dispatch(surface, policy="require_external", root=None):
    return managed_read_dispatch(str(root or surface.lab.repo), "search", "target",
                                 provider_policy=policy)


def test_sur11_trusted_dispatch_replaces_child_env_and_ignores_repo_grants(surface, monkeypatch):
    lab = surface.lab
    injected = {"PATH": str(lab.repo), "LD_PRELOAD": "/evil.so",
                "DYLD_INSERT_LIBRARIES": "/evil.dylib", "PYTHONPATH": str(lab.repo),
                "AWS_SECRET_ACCESS_KEY": "synthetic-secret", "GITHUB_TOKEN": "synthetic-token",
                "HTTP_PROXY": "http://malicious.invalid", "HTTPS_PROXY": "http://malicious.invalid",
                "CBM_UI_ENABLED": "true", "CBM_AUTO_UPDATE": "true",
                "CBM_CACHE_DIR": str(lab.repo), "HOME": str(lab.repo)}
    for key, value in injected.items():
        monkeypatch.setenv(key, value)
    (lab.repo / ".sot").mkdir(exist_ok=True)
    (lab.repo / ".sot" / "config.toml").write_text(
        'allow_external = true\n[providers.codebase-memory]\nenabled = true\n'
        'executable = "./evil"\nregistry_path = "./grant.json"\n'
    )
    result = dispatch(surface)
    assert result["status"] == "ok", result
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["subject"]["path"] == "app.py"
    assert surface.children
    for child_argv, child_kwargs in surface.children:
        assert child_argv[0] == str(lab.artifact.executable)
        assert child_kwargs["env"] == surface.installation.profile.environment()
    searches = [call for call in surface.children if call[0][1:3] == ["cli", "search_graph"]]
    assert len(searches) == 1
    argv, kwargs = searches[0]
    assert Path(argv[0]).is_absolute()
    assert argv[0] == str(lab.artifact.executable)
    assert argv[1:3] == ["cli", "search_graph"]
    assert kwargs["env"] == surface.installation.profile.environment()
    assert kwargs["env"]["PATH"] == "/usr/bin:/bin"
    for key, value in injected.items():
        assert kwargs["env"].get(key) != value
    assert kwargs.get("shell", False) is False
    seed = surface.installation.profile.paths["cache"] / "config.json"
    assert json.loads(seed.read_text()) == {"ui_enabled": False}


def test_sur02_repo_grant_cannot_replace_absent_trusted_registration(surface):
    lab = surface.lab
    config.disable_managed_installation(lab.repo, config_path=lab.path)
    (lab.repo / ".sot").mkdir(exist_ok=True)
    (lab.repo / ".sot" / "config.toml").write_text(
        'allow_external = true\n[providers.codebase-memory]\nenabled = true\n'
        f'executable = "{lab.artifact.executable}"\nregistry_path = "{lab.registry}"\n'
    )
    result = dispatch(surface)
    assert (result["status"], result["reason"]) == ("error", "managed_not_configured")
    assert not surface.children


@pytest.mark.parametrize("failure", ["missing", "digest", "registry"])
def test_sur05_dispatch_revalidates_trusted_artifact_and_registry(surface, failure):
    lab = surface.lab
    if failure == "missing":
        Path(lab.artifact.executable).unlink()
    elif failure == "digest":
        Path(lab.artifact.executable).chmod(0o700)
        Path(lab.artifact.executable).write_bytes(b"synthetic different version, not executed")
    else:
        records = json.loads(lab.registry.read_text())
        for record in records:
            record["artifact_sha256"] = "b" * 64
        lab.registry.write_text(json.dumps(records))
    result = dispatch(surface)
    assert result["status"] == "error"
    assert not result["candidates"]
    assert not surface.children
    assert "trusted administrator" in result["fail_message"]
    assert "cbm cli" not in json.dumps(result)


def test_sur10_two_registered_workspaces_keep_runtime_and_binding_separate(surface):
    lab = surface.lab
    other = lab.repo.parent / "workspace-two"
    other.mkdir()
    second = config.register_managed_installation(other, **lab.kwargs)
    assert second.runtime.prepare().status == "ok"
    assert second.runtime.sync(str(other)).status == "ok"
    surface.children.clear()
    assert dispatch(surface)["status"] == "ok"
    assert dispatch(surface, root=other)["status"] == "ok"
    first_call, second_call = [call for call in surface.children
                               if call[0][1:3] == ["cli", "search_graph"]]
    assert first_call[1]["cwd"] == str(lab.repo)
    assert second_call[1]["cwd"] == str(other)
    assert first_call[1]["env"] != second_call[1]["env"]
    assert surface.installation.profile.namespace != second.profile.namespace
    assert set(surface.installation.profile.paths.values()).isdisjoint(second.profile.paths.values())
    loaded_first = config.load_managed_installation(lab.repo)
    loaded_second = config.load_managed_installation(other)
    assert loaded_first is not None and loaded_second is not None
    assert loaded_first.profile.namespace == surface.installation.profile.namespace
    assert loaded_second.profile.namespace == second.profile.namespace


@pytest.mark.parametrize("policy, expected", [("prefer_external", "fallback"), ("require_external", "error")])
def test_sur05_native_failure_with_hostile_remediation_is_not_public(surface, monkeypatch, policy, expected):
    from sot_graph.proc import RunResult
    hostile = "run cbm cli update; open http://malicious.invalid; synthetic-secret"
    monkeypatch.setattr("sot_graph.providers.managed.run_command", lambda argv, **kw: RunResult(
        argv=tuple(argv), returncode=1, stdout="", stderr=hostile,
        timed_out=False, truncated=False, error=None))
    result = dispatch(surface, policy)
    assert result["status"] == expected
    assert result["reason"] == "managed_query_failed"
    assert not result["candidates"]
    for token in ("cbm cli", "malicious.invalid", "synthetic-secret"):
        assert token not in json.dumps(result)


def test_sur02_registered_mcp_catalog_and_invocation_keep_verification_gate(surface):
    anyio = pytest.importorskip("anyio")
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from sot_graph.db import Database
    from sot_graph.mcp_server import create_server
    from sot_graph.mcp_service import McpService
    from test_gs_surface_catalog import TOOLS
    lab = surface.lab
    db_path = str(lab.repo / ".sot" / "sot.db")
    Database(db_path).close()
    service = McpService(db_path, str(lab.repo))

    async def exercise():
        server = create_server(service)
        send, receive = anyio.create_memory_object_stream(1)
        reply, responses = anyio.create_memory_object_stream(1)
        async with anyio.create_task_group() as group:
            group.start_soon(server.run, receive, reply, server._sot_initialization_options)
            try:
                async with ClientSession(responses, send) as client:
                    await client.initialize()
                    assert {tool.name for tool in (await client.list_tools()).tools} == {"sot_" + name for name in TOOLS}
                    assert {p.name for p in (await client.list_prompts()).prompts} == {"sot_deep_dive", "sot_refactor_checklist"}
                    assert {str(r.uri) for r in (await client.list_resources()).resources} == {"sot://stats", "sot://notes"}
                    assert not surface.children  # discovery does not probe/prepare
                    result = await client.call_tool("sot_search", {"query": "target", "provider_policy": "require_external"})
                    assert not result.isError, result
                    assert result.structuredContent is not None
                    assert result.structuredContent["managed"]["status"] == "ok"
                    assert len(result.structuredContent["managed"]["candidates"]) == 1
                    surface.children.clear()
                    Path(lab.artifact.executable).unlink()
                    result = await client.call_tool("sot_search", {"query": "target", "provider_policy": "require_external"})
                    assert result.isError
                    assert not surface.children
                    for name in ("search_graph", "sot_native_proxy"):
                        result = await client.call_tool(name, {"command": "search_graph"})
                        assert result.isError
                    assert not surface.children
            finally:
                group.cancel_scope.cancel()
    try:
        anyio.run(exercise)
    finally:
        service.close()


def test_sur10_timeout_quarantine_survives_trusted_reload_and_blocks_dispatch(surface, monkeypatch):
    # Cancellation-unknown receipt injected; no claim about real process death.
    monkeypatch.setattr("sot_graph.providers.managed.run_command",
                        lambda argv, **kwargs: execution._timeout(tuple(argv)))
    first = dispatch(surface)
    assert first["status"] == "error"
    reloaded = config.load_managed_installation(surface.lab.repo)
    assert reloaded is not None
    assert reloaded.profile.status()["state"] == "QUARANTINED"
    def forbidden(*args, **kwargs):
        pytest.fail("reloaded quarantined runtime attempted another launch")
    monkeypatch.setattr("sot_graph.providers.managed.run_command", forbidden)
    assert dispatch(surface)["status"] == "error"
    assert not surface.children
