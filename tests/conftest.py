"""Global hermetic test policy.

The suite must never touch the network or spawn services. Engine auto-bootstrap
(``_maybe_bootstrap_engine`` on ``sotgraph setup``) is therefore disabled by
default for every test; tests that exercise bootstrap explicitly call
``sot_graph.providers.bootstrap`` functions directly, which ignore this policy.

Shebang-exec guard: some sandboxed agent shells hang on the DIRECT exec of a
``#!/usr/bin/env python3`` script while spawning the very same script through
an explicit interpreter works fine (binary exec is unaffected; the real managed
engine is a binary). Tests whose fake engines are shebang scripts must skip —
with a reason — instead of burning their whole spawn budget, otherwise dozens
of environmental timeouts drown real regressions. Detection is differential
(see :func:`shebang_exec_available`) so a merely slow environment is not
mislabelled; on Windows CreateProcess cannot exec shebang scripts at all
(same precedent as ``requires_path_spawned_cbm`` in test_cli_provider_wiring).
"""
import functools
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_engine_auto_bootstrap(monkeypatch):
    monkeypatch.setenv("SOT_ENGINE_BOOTSTRAP", "off")


@functools.lru_cache(maxsize=1)
def shebang_exec_available() -> bool:
    """True only when direct shebang-script exec verifiably works.

    Differential: if the explicit-interpreter spawn of the same probe script
    also fails, the environment is broken in some OTHER way and tests should
    fail loudly rather than skip — so only the (direct broken, explicit OK)
    combination reports False on POSIX.
    """
    if os.name == "nt":
        return False  # CreateProcess cannot exec shebang scripts (precedent)
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "shebang_probe.py"
        script.write_text(
            "#!/usr/bin/env python3\nimport sys\nsys.stdout.write(\"ok\\n\")\n",
            encoding="utf-8")
        script.chmod(0o755)
        try:
            direct = subprocess.run([str(script)], capture_output=True, timeout=10)
            direct_ok = direct.returncode == 0 and direct.stdout.strip() == b"ok"
        except subprocess.TimeoutExpired:
            direct_ok = False
        if direct_ok:
            return True
        try:
            explicit = subprocess.run(
                [sys.executable, str(script)], capture_output=True, timeout=10)
            explicit_ok = (explicit.returncode == 0
                           and explicit.stdout.strip() == b"ok")
        except subprocess.TimeoutExpired:
            explicit_ok = False
        # Broken shebang layer only when the script itself runs fine.
        return not explicit_ok


def require_shebang_exec() -> None:
    """Skip the current test when direct shebang exec is unavailable."""
    if not shebang_exec_available():
        pytest.skip("direct shebang-script exec unavailable in this environment "
                    "(sandboxed shell or Windows); see tests/conftest.py")
