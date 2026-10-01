"""Engine-daemon bridge: client behavior and fallback guarantees.

No real engine here — a stub unix-socket server plays the daemon role.
The contract under test: daemon_tool_call returns the MCP result on a
completed call, and returns None (cold-spawn fallback) on every
daemon-level failure mode.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

# The daemon bridge is a Unix-socket protocol; engine_daemon.py is a no-op
# without socket.AF_UNIX (Windows falls back to the cold spawn), so these
# stub-server tests cannot run there.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(socket, "AF_UNIX"),
    reason="engine daemon bridge requires socket.AF_UNIX (POSIX-only)",
)


def _stub_server(sock_path: str, responder, ready: threading.Event):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(2)
    ready.set()

    def loop():
        try:
            while True:
                conn, _ = srv.accept()
                with conn:
                    buf = b""
                    while b"\n" not in buf:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                    if not buf:
                        continue
                    responder(conn, json.loads(buf.split(b"\n", 1)[0]))
        except OSError:
            pass
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return srv


class DaemonClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, ".sot", "cbm"), exist_ok=True)
        self.sock = os.path.join(self.root, ".sot", "cbm", "daemon.sock")

    def tearDown(self):
        self.tmp.cleanup()

    def _serve(self, responder):
        ready = threading.Event()
        srv = _stub_server(self.sock, responder, ready)
        self.addCleanup(srv.close)
        self.assertTrue(ready.wait(5))
        return srv

    def test_ok_response_returns_result(self):
        from sot_graph.engine_daemon import daemon_tool_call

        def reply(conn, req):
            self.assertEqual(req["tool"], "index_repository")
            conn.sendall(b'{"ok": true, "result": {"structuredContent":'
                         b' {"status": "indexed", "nodes": 5}}}\n')

        self._serve(reply)
        out = daemon_tool_call(self.root, "index_repository",
                               {"repo_path": self.root}, 30)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["structuredContent"]["status"], "indexed")

    def test_engine_error_is_none_for_fallback(self):
        from sot_graph.engine_daemon import daemon_tool_call

        self._serve(lambda conn, req:
                    conn.sendall(b'{"ok": false, "error": "engine died"}\n'))
        self.assertIsNone(
            daemon_tool_call(self.root, "index_repository", {}, 30))

    def test_no_daemon_no_socket_returns_none(self):
        from sot_graph.engine_daemon import daemon_tool_call

        # Nothing listening, and _ensure_daemon will try to spawn — point
        # the spawn at a guaranteed-missing interpreter via a lock that
        # reports a dead pid, then refuse the wait by never creating the
        # socket. To keep it hermetic, stub _ensure_daemon off.
        import sot_graph.engine_daemon as ed
        orig = ed._ensure_daemon
        ed._ensure_daemon = lambda root, engine_argv=None: False
        try:
            self.assertIsNone(
                daemon_tool_call(self.root, "index_repository", {}, 30))
        finally:
            ed._ensure_daemon = orig

    def test_malformed_response_returns_none(self):
        from sot_graph.engine_daemon import daemon_tool_call

        self._serve(lambda conn, req: conn.sendall(b"not json\n"))
        self.assertIsNone(
            daemon_tool_call(self.root, "index_repository", {}, 30))


class DaemonGuardTests(unittest.TestCase):
    def test_tool_whitelist(self):
        from sot_graph.engine_daemon import _ALLOWED_TOOLS

        self.assertIn("index_repository", _ALLOWED_TOOLS)
        self.assertIn("detect_changes", _ALLOWED_TOOLS)
        self.assertNotIn("delete_project", _ALLOWED_TOOLS)


@pytest.fixture
def strict_engine(tmp_path):
    """A separate MCP process that enforces the initialization protocol."""
    script = tmp_path / "strict_engine.py"
    script.write_text('''import json, os, sys
from pathlib import Path
with Path("engine-pids").open("a") as pids:
    pids.write(str(os.getpid()) + "\\n")
initialized = False
for line in sys.stdin:
    req = json.loads(line)
    if req["method"] == "notifications/initialized":
        initialized = True
    if "id" not in req:
        continue
    if req["method"] == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}}
    elif initialized and req["method"] == "tools/call" and req["params"]["name"] != "initialize":
        args = req["params"]["arguments"]
        if args.get("partial_reply"):
            import time
            sys.stdout.write("{")
            sys.stdout.flush()
            time.sleep(2)
            continue
        if args.get("notification_burst"):
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"}), flush=True)
        if args.get("crash_always"):
            os._exit(7)
        if args.get("crash_once") and not Path("crashed-once").exists():
            Path("crashed-once").touch()
            os._exit(7)
        result = {"structuredContent": {"tool": req["params"]["name"]}}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": {"message": "initialization required"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}), flush=True)
''', encoding="utf-8")
    return [sys.executable, str(script)]


def test_session_uses_real_initialize_method_and_reaps_child(tmp_path, strict_engine):
    from sot_graph.engine_daemon import _EngineSession
    with (tmp_path / "log").open("wb") as log:
        session = _EngineSession(strict_engine, str(tmp_path), log)
        child = session._proc
        try:
            assert session.call("index_status", {}, 3)["structuredContent"]["tool"] == "index_status"
            assert session.call("detect_changes", {}, 3)["structuredContent"]["tool"] == "detect_changes"
        finally:
            session.stop()
        assert child.poll() is not None


def test_session_timeout_includes_partial_lines(tmp_path, strict_engine):
    from sot_graph.engine_daemon import _EngineSession
    with (tmp_path / "log").open("wb") as log:
        session = _EngineSession(strict_engine, str(tmp_path), log)
        try:
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                session.call("index_status", {"partial_reply": True}, 0.1)
            assert time.monotonic() - started < 1
        finally:
            session.stop()


def test_session_reads_response_after_burst_notifications(tmp_path, strict_engine):
    from sot_graph.engine_daemon import _EngineSession
    with (tmp_path / "log").open("wb") as log:
        session = _EngineSession(strict_engine, str(tmp_path), log)
        try:
            result = session.call("index_status", {"notification_burst": True}, 1)
            assert result["structuredContent"]["tool"] == "index_status"
        finally:
            session.stop()


@pytest.mark.parametrize("payload", [[], None, {"tool": "index_status", "args": []}])
def test_malformed_request_cannot_crash_daemon(payload):
    from sot_graph.engine_daemon import _handle
    client, server = socket.socketpair()
    try:
        client.sendall(json.dumps(payload).encode() + b"\n")
        _handle(server, None, None)
        reply = json.loads(client.recv(4096))
        assert reply["ok"] is False
        assert "bad request" in reply["error"]
    finally:
        client.close()
        server.close()


@pytest.fixture
def short_socket_root():
    # macOS sun_path is limited to 104 bytes; pytest's descriptive path
    # can exceed that even though the daemon behavior is otherwise valid.
    with TemporaryDirectory(prefix="sgd-", dir="/tmp") as root:
        yield Path(root)


def test_concurrent_start_launches_one_daemon(monkeypatch, short_socket_root, strict_engine):
    import sot_graph.engine_daemon as ed

    original_alive = ed._daemon_alive
    original_popen = subprocess.Popen
    launched = []
    barrier = threading.Barrier(2)

    def delayed_absence(root):
        alive = original_alive(root)
        if not alive:
            time.sleep(0.1)  # both ungated callers observe the same absence
        return alive

    def record_launch(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        launched.append(proc)
        return proc

    def start():
        barrier.wait(timeout=5)
        return ed._ensure_daemon(str(short_socket_root), strict_engine)

    monkeypatch.setattr(ed, "_daemon_alive", delayed_absence)
    monkeypatch.setattr(subprocess, "Popen", record_launch)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: start(), range(2)))
        assert len(launched) == 1
        assert results == [True, True]
    finally:
        for proc in launched:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@pytest.mark.parametrize("termination", ["idle", "sigterm"])
def test_daemon_process_restart_error_recovery_and_cleanup(short_socket_root, strict_engine, termination):
    from sot_graph.engine_daemon import _paths
    tmp_path = short_socket_root
    paths = _paths(str(tmp_path))
    wrapper = ("import sys; import sot_graph.engine_daemon as ed; "
               f"ed._IDLE_TTL_S = {0.2 if termination == 'idle' else 300}; "
               "raise SystemExit(ed.run_daemon(sys.argv[1], __import__('json').loads(sys.argv[2])))")
    proc = subprocess.Popen([sys.executable, "-c", wrapper, str(tmp_path), json.dumps(strict_engine)])

    def request(payload):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(paths["sock"])
            client.sendall(json.dumps(payload).encode() + b"\n")
            return json.loads(client.makefile("rb").readline())

    try:
        deadline = time.monotonic() + 8
        while True:
            assert proc.poll() is None
            assert time.monotonic() < deadline
            try:
                ping = request({"tool": "__ping__"})
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.01)
        assert ping["result"]["pong"] is True
        assert request({"tool": "delete_project"})["ok"] is False
        assert request([])["ok"] is False
        assert request({"tool": "index_status", "args": {"crash_once": True}})["ok"] is True
        assert request({"tool": "index_status", "args": {"crash_always": True}})["ok"] is False
        assert request({"tool": "detect_changes"})["result"]["structuredContent"]["tool"] == "detect_changes"
        if termination == "sigterm":
            proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=8) == 0
        assert not os.path.exists(paths["sock"])
        assert not os.path.exists(paths["pid"])
        for pid in (tmp_path / "engine-pids").read_text().splitlines():
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid), 0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_windows_uses_cold_fallback_even_when_af_unix_exists(monkeypatch, tmp_path):
    import sot_graph.engine_daemon as ed
    monkeypatch.setattr(sys, "platform", "win32")
    assert ed.daemon_tool_call(str(tmp_path), "index_status", {}, 1) is None
    assert not (tmp_path / ".sot").exists()


@pytest.mark.parametrize("pid_record", [[], None, "123", {"pid": "not-a-pid"}])
def test_corrupt_pid_record_is_treated_as_absent(tmp_path, pid_record):
    from sot_graph.engine_daemon import _daemon_alive, _paths
    paths = _paths(str(tmp_path))
    os.makedirs(os.path.dirname(paths["pid"]))
    with open(paths["pid"], "w") as record:
        json.dump(pid_record, record)
    assert _daemon_alive(str(tmp_path)) is False


if __name__ == "__main__":
    unittest.main()
