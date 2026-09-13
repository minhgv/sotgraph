"""Engine-daemon bridge: client behavior and fallback guarantees.

No real engine here — a stub unix-socket server plays the daemon role.
The contract under test: daemon_tool_call returns the MCP result on a
completed call, and returns None (cold-spawn fallback) on every
daemon-level failure mode.
"""
import json
import os
import socket
import threading
import unittest
from tempfile import TemporaryDirectory


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


if __name__ == "__main__":
    unittest.main()
