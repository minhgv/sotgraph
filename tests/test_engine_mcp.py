"""Internal MCP stdio client against a stub engine (no network, no real binary)."""
import os
import sys
import textwrap

import pytest

from conftest import require_shebang_exec

from sot_graph.providers.engine_mcp import (
    EngineMcpClient,
    EngineMcpError,
    probe_engine_mcp,
)

from sot_graph.providers import bootstrap as bp

# Stub that surfaces its own CBM_* environment through serverInfo so tests can
# assert the namespaced spawn env without a real engine binary. It is always
# spawned via ``sys.executable`` (never by shebang path, which this harness
# cannot exec).
_ENV_STUB = textwrap.dedent("""
    import json, os, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("method") == "initialize":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "stub-engine", "version": "0.1",
                               "cbm_runtime_dir": os.environ.get("CBM_RUNTIME_DIR", ""),
                               "cbm_cache_dir": os.environ.get("CBM_CACHE_DIR", "")}}}
        elif "id" in msg:
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": []}}
        else:
            continue
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
""")

_STUB = textwrap.dedent("""
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "stub-engine", "version": "0.1"}}}
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [
                {"name": "index", "description": "index a repo"},
                {"name": "search"}]}}
        elif method == "tools/call":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {
                "content": [{"type": "text", "text": "ok"}], "isError": False}}
        else:
            if "id" not in msg:
                continue
            resp = {"jsonrpc": "2.0", "id": msg["id"],
                    "error": {"message": "unknown method"}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
""")


@pytest.fixture
def stub_server(tmp_path):
    script = tmp_path / "stub_engine.py"
    script.write_text(_STUB, encoding="utf-8")
    return sys.executable, (str(script),)


def test_handshake_list_tools_and_call(tmp_path, stub_server):
    executable, args = stub_server
    client = EngineMcpClient(executable, args=args, timeout_s=10.0)
    client.start()
    try:
        init = client.initialize()
        assert init["serverInfo"]["name"] == "stub-engine"
        tools = client.list_tools()
        assert [t.name for t in tools] == ["index", "search"]
        assert tools[0].description == "index a repo"
        result = client.call_tool("index", {"root": str(tmp_path)})
        assert result["isError"] is False
    finally:
        tail = client.close()
        assert "Traceback" not in tail


def test_probe_ok(tmp_path):
    require_shebang_exec()
    script = tmp_path / "stub_engine.py"
    script.write_text("#!/usr/bin/env python3\n" + _STUB, encoding="utf-8")
    script.chmod(0o755)
    probe = probe_engine_mcp(str(script), timeout_s=10.0)
    assert probe["status"] == "ok"
    assert probe["server_name"] == "stub-engine"
    assert probe["server_version"] == "0.1"
    assert "index" in probe["tools"]


def test_malformed_stream_fails_closed(tmp_path):
    bad = tmp_path / "bad_engine.py"
    bad.write_text("import sys\nsys.stdout.write('not-json\\n')\nsys.stdout.flush()\n"
                   "import time\ntime.sleep(30)\n", encoding="utf-8")
    client = EngineMcpClient(sys.executable, args=(str(bad),), timeout_s=10.0)
    client.start()
    with pytest.raises(EngineMcpError, match="malformed"):
        client.initialize()
    client.close()


def test_missing_executable_fails_closed(tmp_path):
    client = EngineMcpClient(str(tmp_path / "does-not-exist"))
    with pytest.raises(EngineMcpError, match="cannot start"):
        client.start()


def test_error_response_maps_to_exception(tmp_path, stub_server):
    executable, args = stub_server
    client = EngineMcpClient(executable, args=args, timeout_s=10.0)
    client.start()
    try:
        with pytest.raises(EngineMcpError, match="unknown method"):
            client._request("bogus/method", {})
    finally:
        client.close()


def test_store_root_namespaces_spawn_env(tmp_path, monkeypatch):
    """P1.1 §7.1: client spawn carries per-account CBM_RUNTIME_DIR/CBM_CACHE_DIR."""
    if not hasattr(os, "geteuid"):
        pytest.skip("unix-only rendezvous budget")
    monkeypatch.setattr(bp, "_engine_runtime_parent", lambda: tmp_path / "rt")
    store = tmp_path / "store"
    script = tmp_path / "env_stub_engine.py"
    script.write_text(_ENV_STUB, encoding="utf-8")
    client = EngineMcpClient(sys.executable, args=(str(script),), timeout_s=10.0,
                             store_root=str(store))
    client.start()
    try:
        server = client.initialize()["serverInfo"]
    finally:
        client.close()
    runtime = tmp_path / "rt" / f"sotgraph-engine-{os.geteuid()}"
    cache = store / "cache" / "codebase-memory"
    assert server["cbm_runtime_dir"] == str(runtime)
    assert server["cbm_cache_dir"] == str(cache)
    for path in (runtime, cache):
        assert path.is_dir()
        assert path.stat().st_mode & 0o777 == 0o700


def test_explicit_env_merges_namespace(tmp_path):
    script = tmp_path / "env_stub.py"
    script.write_text(_ENV_STUB, encoding="utf-8")
    store = tmp_path / "store"
    client = EngineMcpClient(
        sys.executable, args=(str(script),), timeout_s=10.0,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""),
             "SOT_MARK": "kept"},
        store_root=str(store))
    client.start()
    try:
        client.initialize()
    finally:
        client.close()
    assert (store / "cache" / "codebase-memory").is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="engine runtime env namespacing is POSIX-only")
def test_probe_engine_mcp_passes_store_root(tmp_path):
    store = tmp_path / "probe-store"
    script = tmp_path / "env_stub_probe.py"
    script.write_text(_ENV_STUB, encoding="utf-8")
    probe = probe_engine_mcp(sys.executable, timeout_s=10.0,
                             store_root=str(store), args=(str(script),))
    assert probe["status"] == "ok"
    assert (store / "cache" / "codebase-memory").is_dir()


def test_start_fail_closed_when_namespace_unavailable(tmp_path, monkeypatch):
    from sot_graph.providers.bootstrap import BootstrapError

    def broken(store_root, engine_name):
        raise BootstrapError("managed engine runtime namespace unavailable: nope")

    monkeypatch.setattr(bp, "engine_runtime_env", broken)
    script = tmp_path / "env_stub_broken.py"
    script.write_text(_ENV_STUB, encoding="utf-8")
    client = EngineMcpClient(sys.executable, args=(str(script),), timeout_s=10.0,
                             store_root=str(tmp_path / "store"))
    with pytest.raises(EngineMcpError, match="cannot start engine process"):
        client.start()
    assert client.process is None
