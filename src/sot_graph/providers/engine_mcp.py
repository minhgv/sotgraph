"""Minimal MCP stdio client for the internal engine subprocess (master plan D2).

sotgraph owns orchestration and verification; the engine is spoken to over
MCP JSON-RPC 2.0 on stdio and is NEVER registered as an agent-facing MCP
server. This client is deliberately tiny and fail-closed: bounded lines, one
outstanding request, deadline-enforced reads, minimal child environment (no
credential inheritance), and no interpretation of engine-side hints as
operational guidance.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from multiprocessing.connection import wait
from typing import Any

__all__ = ["EngineMcpError", "McpToolInfo", "EngineMcpClient", "probe_engine_mcp"]

_LINE_CAP_BYTES = 16 << 20
_PROTOCOL_VERSION = "2024-11-05"


class EngineMcpError(RuntimeError):
    """Fail-closed MCP transport/handshake error."""


@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str = ""


@dataclass
class EngineMcpClient:
    """One-request-at-a-time MCP stdio client over a spawned engine process.

    ``store_root`` opts the spawn into the per-account namespaced runtime
    layout (master plan §7.1): ``CBM_RUNTIME_DIR``/``CBM_CACHE_DIR`` are
    resolved against the engine store at :meth:`start` time and merged into
    the child environment (``os.environ`` is never touched). Namespace
    failures are fail-closed: :class:`EngineMcpError`, no fallback to the
    default rendezvous.
    """

    executable: str
    args: tuple[str, ...] = ()
    timeout_s: float = 20.0
    env: dict[str, str] | None = None
    store_root: str | None = None
    engine_name: str = "codebase-memory"
    process: subprocess.Popen | None = field(default=None, init=False, repr=False)
    _next_id: int = field(default=1, init=False, repr=False)
    _pending: bytes = field(default=b"", init=False, repr=False)

    def start(self) -> None:
        if self.process is not None:
            raise EngineMcpError("engine process already started")
        env = dict(self.env) if self.env is not None else {
            key: os.environ.get(key, "")
            for key in ("PATH", "HOME") if os.environ.get(key)
        }
        if self.store_root is not None:
            from .bootstrap import BootstrapError, engine_runtime_env
            try:
                env.update(engine_runtime_env(self.store_root, self.engine_name))
            except BootstrapError as exc:
                raise EngineMcpError(f"cannot start engine process: {exc}") from exc
        try:
            self.process = subprocess.Popen(
                [self.executable, *self.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, close_fds=True,
            )
        except OSError as exc:
            raise EngineMcpError(f"cannot start engine process: {exc}") from exc

    def _deadline(self) -> float:
        return time.monotonic() + self.timeout_s

    def _readline(self, deadline: float) -> bytes:
        assert self.process is not None and self.process.stdout is not None
        buffer = bytearray(self._pending)
        self._pending = b""
        fd = self.process.stdout.fileno()
        if sys.platform == "win32":
            import msvcrt
            waitable: object = msvcrt.get_osfhandle(fd)  # kernel handle, not CRT fd
        else:
            waitable = fd
        while True:
            newline = buffer.find(b"\n")
            if newline >= 0:
                line, self._pending = bytes(buffer[:newline]), bytes(buffer[newline + 1:])
                return line.strip(b"\r")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineMcpError("engine MCP response timed out")
            ready = wait([waitable], min(remaining, 1.0))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                raise EngineMcpError("engine MCP stream closed unexpectedly")
            buffer += chunk
            if len(buffer) > _LINE_CAP_BYTES:
                raise EngineMcpError("engine MCP line exceeds bounded cap")

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        try:
            self.process.stdin.write(
                (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
            self.process.stdin.flush()
        except OSError as exc:
            raise EngineMcpError(f"engine MCP write failed: {exc}") from exc

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method,
                    "params": params})
        deadline = self._deadline()
        while True:
            line = self._readline(deadline)
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError as exc:
                raise EngineMcpError(f"engine MCP sent malformed JSON: {exc}") from exc
            if not isinstance(message, dict):
                raise EngineMcpError("engine MCP message is not an object")
            if message.get("id") != request_id:
                continue  # notifications or unrelated traffic; never act on them
            if "error" in message:
                error = message["error"]
                detail = error.get("message") if isinstance(error, dict) else error
                raise EngineMcpError(f"engine MCP error response: {detail}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise EngineMcpError("engine MCP result is not an object")
            return result

    def initialize(self) -> dict[str, Any]:
        from sot_graph import __version__
        result = self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "sotgraph", "version": __version__},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def list_tools(self) -> list[McpToolInfo]:
        result = self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise EngineMcpError("engine MCP tools/list result has no tools array")
        infos: list[McpToolInfo] = []
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                raise EngineMcpError("engine MCP tool entry schema mismatch")
            description = tool.get("description")
            infos.append(McpToolInfo(tool["name"],
                                     description if isinstance(description, str) else ""))
        return infos

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> str:
        """Terminate the engine; return a bounded stderr tail for diagnostics."""
        assert self.process is not None
        stderr_tail = ""
        try:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=min(self.timeout_s, 5.0))
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5.0)
            if self.process.stderr:
                raw = self.process.stderr.read(4096)
                stderr_tail = raw.decode("utf-8", "replace").strip()
        except OSError:
            pass
        finally:
            for stream in (self.process.stdout, self.process.stderr):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
            self.process = None
        return stderr_tail


def probe_engine_mcp(executable: str, timeout_s: float = 20.0,
                     store_root: str | None = None,
                     engine_name: str = "codebase-memory",
                     args: tuple[str, ...] = ()) -> dict[str, Any]:
    """Handshake + tools/list against an engine executable; fail-closed.

    ``store_root`` namespaces the probe spawn under the engine store layout
    (master plan §7.1); a namespace failure surfaces as ``refused`` — never a
    fallback to the default rendezvous and never engine-operations guidance.
    """
    client = EngineMcpClient(executable, args=args, timeout_s=timeout_s,
                             store_root=store_root, engine_name=engine_name)
    try:
        client.start()
        init = client.initialize()
        raw_server = init.get("serverInfo")
        server: dict[str, Any] = raw_server if isinstance(raw_server, dict) else {}
        tools = client.list_tools()
        return {
            "schema_version": 1,
            "status": "ok",
            "protocol_version": str(init.get("protocolVersion", "unknown")),
            "server_name": str(server.get("name", "unknown")),
            "server_version": str(server.get("version", "unknown")),
            "tools": [tool.name for tool in tools],
        }
    except EngineMcpError as exc:
        tail = client.close() if client.process is not None else ""
        detail = f"{exc}" + (f"; stderr tail: {tail[:512]}" if tail else "")
        return {"schema_version": 1, "status": "refused", "error": detail[:1024]}
    finally:
        if client.process is not None:
            client.close()
