"""G2 orphan-writer honesty tests for the P2 managed native executor.

HONESTY SCOPE: the "orphan writer" here is an OWNED, TEST-SPAWNED Python
subprocess (plain ``Popen``) that demonstrably stays ALIVE across the client
timeout result. It is a SIMULATED orphan — it proves the executor's timeout
bookkeeping under a live unknown writer, NOT a real native daemon surviving a
cancellation. ``sot_graph.proc.run_command`` stays FAKED (same seams as
``tests/test_managed_execution.py``); no actual CBM binary, no network, no
shell. Cleanup touches ONLY the Popen this module spawned (terminate + bounded
wait). Per the invariant: a native job surviving a client timeout must NOT
report success — and the opposite (zero surviving writers) is NOT asserted.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import importlib.util  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "_tme_helpers", Path(__file__).with_name("test_managed_execution.py"))
_helpers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_helpers)

from sot_graph.providers.managed import ManagedNativeRuntime  # noqa: E402
from sot_graph.providers.runtime import ManagedRuntimeProfile  # noqa: E402

# Owned simulated orphan worker: writes its own pid marker, then keeps
# OBSERVING and refreshing that marker (pid@heartbeat) until a stop file
# appears or its own 90 s self-deadline expires. It never exits on its own
# before the stop file, so liveness across the timeout result is observable.
_WORKER_SRC = """
import os, sys, time
marker, stop = sys.argv[1], sys.argv[2]
deadline = time.monotonic() + 90
while time.monotonic() < deadline and not os.path.exists(stop):
    with open(marker + ".tmp", "w") as fp:
        fp.write(f"{os.getpid()}@{time.monotonic()}")
    os.replace(marker + ".tmp", marker)
    time.sleep(0.05)
"""

_MARKER_WAIT_S = 10.0
_TERMINATE_WAIT_S = 10.0


@pytest.fixture
def make_root():
    """Same short-root factory as tests/test_managed_execution.py (native
    socket-path budget); cleanup only what this factory created."""
    import shutil
    import uuid
    created: list[Path] = []

    def _make() -> Path:
        root = Path(_helpers._short_base()) / f"ow{uuid.uuid4().hex[:10]}"
        created.append(root)
        return root

    yield _make
    for root in created:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def fake_native(monkeypatch):
    fake = _helpers.FakeNative()
    import sot_graph.providers.managed as managed
    monkeypatch.setattr(managed, "run_command", fake)
    return fake


def _manifest(profile: ManagedRuntimeProfile) -> dict:
    return json.loads((profile.namespace / "manifest.json").read_bytes())


def _spawn_worker(tmp_path: Path) -> tuple[subprocess.Popen, Path]:
    marker = tmp_path / "orphan-marker.txt"
    stop = tmp_path / "orphan-stop.txt"
    worker = subprocess.Popen(
        [sys.executable, "-c", _WORKER_SRC, str(marker), str(stop)])
    deadline = time.monotonic() + _MARKER_WAIT_S
    while time.monotonic() < deadline:  # bounded wait for the marker
        if marker.exists() and marker.read_text().strip():
            break
        time.sleep(0.02)
    return worker, stop


def test_sync_timeout_while_orphan_writer_alive_never_reports_success(
        tmp_path, fake_native, make_root) -> None:
    """A writer alive across the client timeout must never yield success."""
    worker, stop = _spawn_worker(tmp_path)
    try:
        root = make_root()
        runtime, profile, repo, exe = _helpers._runtime(
            root, tmp_path, fake_native)
        assert runtime.prepare().status == "ok"
        assert runtime.sync(str(repo)).status == "ok"
        fake_native.calls.clear()
        assert worker.poll() is None  # orphan demonstrably alive pre-dispatch
        first_beat = (tmp_path / "orphan-marker.txt").read_text().strip()

        fake_native._handler = lambda argv: (
            fake_native._receipts(argv)
            if argv[1:3] in (["config", "set"], ["config", "get"])
            else _helpers._timeout(tuple(argv)))
        fake_native.calls.clear()

        result = runtime.sync(str(repo))  # mocked runner: timed_out
        assert result.status == "timeout"
        assert result.status != "ok"
        assert result.cancellation_state == "cancellation_unknown"

        assert worker.poll() is None  # SURVIVED the client-timeout result
        deadline = time.monotonic() + _MARKER_WAIT_S
        while time.monotonic() < deadline:  # worker still observing its marker
            if (tmp_path / "orphan-marker.txt").read_text().strip() != first_beat:
                break
            time.sleep(0.02)
        assert (tmp_path / "orphan-marker.txt").read_text().strip() != first_beat
        assert worker.poll() is None  # alive after observing its own marker
        assert (tmp_path / "orphan-marker.txt").read_text().startswith(
            f"{worker.pid}@")

        manifest = _manifest(profile)
        assert manifest["state"] == "QUARANTINED"  # fresh quarantine, sticky
        assert manifest["quarantine_reason"] == (
            "sync ended without confirmed terminal success")
        last = manifest.get("last_complete") or {}
        assert last.get("success") is not True  # ledger records NO success
        assert last.get("terminal_confirmed") is not True

        # Reuse via a FRESH profile instance over the SAME namespace is denied
        # without any further spawn (the orphan may still be alive; that is
        # exactly the unknown-writer risk being refused, not zeroed).
        calls_after_timeout = len(fake_native.calls)
        exe_digest = hashlib.sha256(Path(exe).read_bytes()).hexdigest()
        profile2 = ManagedRuntimeProfile(str(root), str(repo),
                                         artifact_digest=exe_digest)
        runtime2 = ManagedNativeRuntime(profile2, str(repo), (exe,),
                                        _helpers._context(exe_digest))
        refused = runtime2.sync(str(repo))
        assert refused.status == "runtime_refused"
        assert refused.status != "ok"
        refused_q = runtime2.query("search_graph", {"query": "x"})
        assert refused_q.status == "runtime_refused"
        assert len(fake_native.calls) == calls_after_timeout  # no further spawn
        assert fake_native.calls[-1]["argv"][1:3] == ["cli", "index_repository"]
        assert fake_native.calls[-1]["timeout"] == 300.0
    finally:
        stop.touch()  # release the owned worker, then hard-stop + bounded wait
        worker.terminate()
        try:
            worker.wait(timeout=_TERMINATE_WAIT_S)
        except subprocess.TimeoutExpired:  # pragma: no cover
            worker.kill()
            worker.wait(timeout=_TERMINATE_WAIT_S)


def test_sync_clean_receipt_malformed_or_terminal_unconfirmed_never_success(
        tmp_path, fake_native, make_root) -> None:
    """rc=0 + non-empty stdout alone is never success: malformed JSON and a
    clean object without status=indexed both fail with a no-success ledger."""
    for stdout in ("junk { not json",  # clean bytes, malformed receipt
                   json.dumps({"status": "partial", "project": "proj"})):
        fake_native._handler = None  # observed receipts for prepare
        runtime, profile, repo, _exe = _helpers._runtime(
            make_root(), tmp_path, fake_native)
        assert runtime.prepare().status == "ok"
        fake_native.calls.clear()
        fake_native._handler = lambda argv, s=stdout: _helpers._rc0(s)
        result = runtime.sync(str(repo))
        assert result.status == "receipt_invalid"
        assert result.status != "ok"
        manifest = _manifest(profile)
        assert manifest["state"] == "QUARANTINED"
        last = manifest.get("last_complete") or {}
        assert last.get("success") is not True  # ledger never claims success
        assert last.get("terminal_confirmed") is not True
