"""Persistent codebase-memory engine session — per-repo daemon bridge.

Why this exists: ``run_index`` spawns ``codebase-memory-mcp cli`` per
call — paying ~3.7s of process init plus cold in-session index work
(~12s) every reconcile (~15.7s total floor). The engine is an MCP
server: one long-lived stdio session keeps the allocator, project
bindings and parse caches warm — a measured spike showed a warm
``index_repository`` call at ~4.5s, a 3.5x cut.

The daemon owns one engine child and a unix socket at
``.sot/cbm/daemon.sock``. Clients send one newline-delimited JSON
request per connection (``{"tool", "args"}``) and receive one JSON line
back (``{"ok", "result"|"error"}``). It is an optimization, never a
dependency: every caller falls back to the cold spawn path on any
failure, and the daemon exits after an idle TTL so nothing lingers.

Lifecycle safety:
- bind the socket before spawning the engine (clients see readiness
  early; first request absorbs the ~4s init),
- serialize all calls — the engine session is not reentrant,
- restart the engine child once when it dies mid-call,
- remove socket + pid files on exit; a crashed daemon leaves both and
  the next client respawns cleanly (stale bind is replaced),
- tool whitelist — the bridge is for index/status tools only.
"""

from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

_DAEMON_DIR_REL = os.path.join(".sot", "cbm")
_SOCK_NAME = "daemon.sock"
_PID_NAME = "daemon.pid"
_LOG_NAME = "daemon.log"
_IDLE_TTL_S = 900.0          # exit after 15 min without a request
_CONNECT_WAIT_S = 12.0       # client budget for daemon auto-start
_LOG_MAX_BYTES = 1_000_000
_ALLOWED_TOOLS = frozenset({
    "index_repository", "detect_changes", "index_status",
    "check_index_coverage",
})


def _paths(root: str) -> Dict[str, str]:
    base = os.path.join(root, _DAEMON_DIR_REL)
    return {"sock": os.path.join(base, _SOCK_NAME),
            "pid": os.path.join(base, _PID_NAME),
            "log": os.path.join(base, _LOG_NAME)}


# ---------------------------------------------------------------------------
# client side
# ---------------------------------------------------------------------------

def daemon_tool_call(
    root: str,
    tool: str,
    args: Dict[str, Any],
    timeout_s: float,
    engine_argv: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """One request through the engine daemon.

    Returns the MCP ``result`` dict when the daemon completed the tool
    call (even when the tool reports an error — that is a real answer).
    Returns ``None`` on any daemon-level failure: absent, connect error,
    protocol mismatch, timeout — callers fall back to the cold spawn.

    ``engine_argv`` is the caller's resolved engine command; a freshly
    spawned daemon uses it so the warm session runs the same build the
    cold fallback would — a build mismatch would trip the engine's
    single-active-version guard. An already-running daemon keeps its
    own session regardless.
    """
    if not hasattr(socket, "AF_UNIX"):
        return None
    if os.environ.get("SOT_ENGINE_DAEMON", "").strip().lower() in (
            "off", "0", "false", "no"):
        return None
    paths = _paths(root)
    request = json.dumps({"tool": tool, "args": args,
                          "engine_argv": engine_argv or []}) + "\n"
    for attempt in range(2):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(max(timeout_s, 30.0))
                sock.connect(paths["sock"])
                sock.sendall(request.encode("utf-8"))
                buf = b""
                while b"\n" not in buf:
                    chunk = sock.recv(65536)
                    if not chunk:
                        return None
                    buf += chunk
                resp = json.loads(buf.split(b"\n", 1)[0])
        except (OSError, ValueError):
            resp = None
        if resp is not None:
            return resp.get("result") if resp.get("ok") else None
        if attempt == 0 and _ensure_daemon(root, engine_argv):
            continue
        return None
    return None


def _daemon_alive(root: str) -> bool:
    try:
        with open(_paths(root)["pid"], "r", encoding="utf-8") as fh:
            pid = int(json.load(fh).get("pid") or 0)
        if pid > 0:
            os.kill(pid, 0)
            return True
    except (OSError, ValueError):
        return False
    return False


def _ensure_daemon(
    root: str,
    engine_argv: Optional[List[str]] = None,
) -> bool:
    """Auto-start the daemon; wait briefly for the socket to appear."""
    paths = _paths(root)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            probe.connect(paths["sock"])
            return True
    except OSError:
        pass
    if _daemon_alive(root):
        return True  # another process is starting it — socket imminent
    try:
        os.makedirs(os.path.dirname(paths["sock"]), exist_ok=True)
        log_mode = "ab" if (
            os.path.exists(paths["log"])
            and os.path.getsize(paths["log"]) <= _LOG_MAX_BYTES
        ) else "wb"
        log = open(paths["log"], log_mode)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "sot_graph.engine_daemon", root,
                 json.dumps(list(engine_argv or []))],
                cwd=root, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        tmp = paths["pid"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"pid": proc.pid, "started": time.time()}, fh)
        os.replace(tmp, paths["pid"])
    except OSError:
        return False
    deadline = time.monotonic() + _CONNECT_WAIT_S
    while time.monotonic() < deadline:
        if os.path.exists(paths["sock"]):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect(paths["sock"])
                    return True
            except OSError:
                pass
        if proc.poll() is not None:
            return False  # daemon died during startup
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# daemon side — one engine child, serialized MCP calls
# ---------------------------------------------------------------------------

class _EngineSession:
    """One ``codebase-memory-mcp`` stdio session (MCP JSON-RPC)."""

    def __init__(self, argv: List[str], root: str, log: Any) -> None:
        self._argv = argv
        self._root = root
        self._log = log
        self._proc: Optional[subprocess.Popen] = None
        self._next_id = 0
        self.start()

    def start(self) -> None:
        from sot_graph.cbm import cbm_env
        env = dict(os.environ)
        env.update(cbm_env(self._root))
        self._proc = subprocess.Popen(
            self._argv, cwd=self._root,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._log, text=True, bufsize=1, env=env,
        )
        self._next_id = 0
        self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "sotgraph-daemon", "version": "0"},
        }, timeout_s=120.0)
        self._send({"jsonrpc": "2.0",
                    "method": "notifications/initialized"})

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def restart(self) -> None:
        self.stop()
        self.start()

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc = None

    def _send(self, msg: Dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _read_response(self, want_id: int, deadline: float) -> Dict[str, Any]:
        assert self._proc is not None and self._proc.stdout is not None
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("engine process exited")
            remaining = max(0.05, deadline - time.monotonic())
            ready, _, _ = select.select(
                [self._proc.stdout], [], [], min(1.0, remaining))
            if not ready:
                continue
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("engine closed stdout")
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # non-JSON noise on stdout
            if msg.get("id") == want_id:
                return msg
        raise TimeoutError("engine call timed out")

    def call(self, tool: str, args: Dict[str, Any],
             timeout_s: float) -> Dict[str, Any]:
        self._next_id += 1
        req_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                    "params": {"name": tool, "arguments": args}})
        resp = self._read_response(req_id, time.monotonic() + timeout_s)
        if "error" in resp:
            raise RuntimeError(str(resp["error"])[:300])
        return resp.get("result") or {}


def _respond(conn: socket.socket, payload: Dict[str, Any]) -> None:
    try:
        conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        pass


def _resolve_engine_argv(root: str) -> Optional[List[str]]:
    from sot_graph.cbm import resolve_engine_command
    from sot_graph.config import load_config
    try:
        cfg = load_config(root)
    except Exception:
        cfg = None
    argv, source = resolve_engine_command(
        root, (cfg.providers.get("codebase-memory") if cfg else None),
        cbm_command=getattr(cfg, "cbm_command", None))
    return argv or None


def run_daemon(
    root: str,
    engine_argv: Optional[List[str]] = None,
) -> int:
    """Daemon entry point: bind socket, own one engine session, serve."""
    paths = _paths(root)
    os.makedirs(os.path.dirname(paths["sock"]), exist_ok=True)
    log_mode = "ab" if (
        os.path.exists(paths["log"])
        and os.path.getsize(paths["log"]) <= _LOG_MAX_BYTES
    ) else "wb"
    log = open(paths["log"], log_mode, buffering=0)
    try:
        argv = list(engine_argv or []) or _resolve_engine_argv(root)
        if not argv:
            log.write(b"engine_daemon: no engine command resolved\n")
            return 2
        try:
            os.unlink(paths["sock"])  # stale bind from a crashed daemon
        except OSError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(paths["sock"])
            server.listen(4)
            server.settimeout(2.0)
        except OSError:
            log.write(b"engine_daemon: socket bind failed\n")
            return 3
        engine = _EngineSession(argv, root, log)
        last_request = time.monotonic()
        try:
            while time.monotonic() - last_request < _IDLE_TTL_S:
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                last_request = time.monotonic()
                with conn:
                    _handle(conn, engine, log)
        finally:
            engine.stop()
    finally:
        for key in ("sock", "pid"):
            try:
                os.unlink(paths[key])
            except OSError:
                pass
        log.close()
    return 0


def _handle(conn: socket.socket, engine: _EngineSession, log: Any) -> None:
    conn.settimeout(10.0)
    try:
        buf = b""
        while b"\n" not in buf and len(buf) < 4_000_000:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
        req = json.loads(buf.split(b"\n", 1)[0])
        tool, args = req.get("tool"), req.get("args") or {}
    except (OSError, ValueError) as exc:
        _respond(conn, {"ok": False, "error": f"bad request: {exc}"})
        return
    if tool == "__ping__":
        _respond(conn, {"ok": True,
                        "result": {"pong": True, "pid": os.getpid()}})
        return
    if tool not in _ALLOWED_TOOLS:
        _respond(conn, {"ok": False, "error": f"tool not allowed: {tool}"})
        return
    try:
        if not engine.alive():
            engine.restart()
        result = engine.call(tool, args, timeout_s=600.0)
    except Exception:
        # One restart retry — the engine may have crashed mid-call.
        try:
            engine.restart()
            result = engine.call(tool, args, timeout_s=600.0)
        except Exception as exc2:
            log.write(f"engine_daemon: {tool} failed: {exc2}\n"
                      .encode("utf-8", "replace"))
            _respond(conn, {"ok": False,
                            "error": str(exc2)[:300]})
            return
    _respond(conn, {"ok": True, "result": result})


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m sot_graph.engine_daemon <root> "
              "[engine_argv_json]", file=sys.stderr)
        return 2
    engine_argv: Optional[List[str]] = None
    if len(args) > 1:
        try:
            parsed = json.loads(args[1])
            if isinstance(parsed, list) and all(
                    isinstance(x, str) for x in parsed):
                engine_argv = parsed or None
        except ValueError:
            pass
    return run_daemon(os.path.realpath(args[0]), engine_argv)


if __name__ == "__main__":
    raise SystemExit(main())
