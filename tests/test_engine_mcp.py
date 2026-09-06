"""Internal MCP stdio client against a stub engine (no network, no real binary)."""
import sys
import textwrap

import pytest

from sot_graph.providers.engine_mcp import (
    EngineMcpClient,
    EngineMcpError,
    probe_engine_mcp,
)

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
