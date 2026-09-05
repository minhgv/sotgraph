"""Tests for run_command ``env`` semantics in sot_graph.proc.

Covers the optional explicit-environment keyword:

- ``env=None`` (default): child inherits ``os.environ`` (legacy behavior).
- ``env={}``: child gets NO inherited environment at all.
- ``env=mapping``: child gets exactly the mapping (copied, never mutated);
  ``env_extra`` still applies additively on top (deterministic merge).
- Bad mappings return a ``RunResult`` (no-raise contract preserved).

The "inherited by default" cases re-execute this file as a child process
with a sentinel in ITS environment, so the test suite never mutates the
parent ``os.environ``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from types import MappingProxyType

import pytest

from sot_graph.proc import RunResult, run_command

PY = sys.executable

_SECRET = "sot-secret-sentinel-42"
_SECRET_VAR = "SOT_PROC_ENV_TEST_SECRET"

#: Windows children cannot start without a minimal set of system variables
#: (``SystemRoot`` above all); explicit-env tests merge this floor in on nt.
_PLATFORM_REQUIRED = ("SystemRoot", "SystemDrive", "windir", "COMSPEC", "PATHEXT")


def _platform_floor_env() -> dict[str, str]:
    if os.name != "nt":
        return {}
    return {k: os.environ[k] for k in _PLATFORM_REQUIRED if k in os.environ}


def _reexec_child(mode: str) -> subprocess.CompletedProcess[str]:
    """Re-run this file as a child carrying the sentinel in its environ."""
    return subprocess.run(  # noqa: S603 - absolute sys.executable, fixed args
        [PY, os.path.abspath(__file__), "--child", mode],
        env={**os.environ, _SECRET_VAR: _SECRET},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _child_main(mode: str) -> int:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    from sot_graph.proc import run_command as rc

    argv = [PY, "-c", "import os; print(os.environ.get('SOT_PROC_ENV_TEST_SECRET', 'MISSING'))"]
    if mode == "inherit":
        result = rc(argv)
    elif mode == "explicit_empty":
        result = rc(argv, env={})
    else:  # pragma: no cover - guard against typo'd modes
        raise SystemExit(f"unknown mode {mode!r}")
    if result.error is not None:
        print(result.error, file=sys.stderr)  # noqa: T201 - child diagnostic
        return 2
    print(result.stdout.strip())  # noqa: T201 - parent asserts on this
    return 0


def test_secret_inherited_by_default_without_env() -> None:
    done = _reexec_child("inherit")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == _SECRET


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX-only: Windows children cannot start from a fully empty environment",
)
def test_explicit_empty_env_means_no_inheritance() -> None:
    done = _reexec_child("explicit_empty")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "MISSING"


def test_explicit_env_additions_only_no_inherited_vars() -> None:
    argv = [
        PY,
        "-c",
        "import os; print(os.environ.get('SOT_ONLY', 'MISSING'),"
        " 'PATH' in os.environ, 'HOME' in os.environ)",
    ]
    result = run_command(argv, env={**_platform_floor_env(), "SOT_ONLY": "present"})
    assert result.returncode == 0
    assert result.error is None
    assert result.stdout.split() == ["present", "False", "False"]


def test_env_extra_legacy_additive_over_inherited_environ() -> None:
    argv = [
        PY,
        "-c",
        "import os; print('PATH' in os.environ, os.environ.get('SOT_EXTRA', 'MISSING'))",
    ]
    result = run_command(argv, env_extra={"SOT_EXTRA": "legacy"})
    assert result.returncode == 0
    assert result.error is None
    assert result.stdout.split() == ["True", "legacy"]


def test_env_extra_overlays_explicit_env_deterministic_merge() -> None:
    argv = [
        PY,
        "-c",
        "import os; print(os.environ.get('A', 'MISSING'), os.environ.get('B', 'MISSING'))",
    ]
    result = run_command(argv, env={**_platform_floor_env(), "A": "base", "B": "base"}, env_extra={"B": "extra"})
    assert result.returncode == 0
    assert result.error is None
    assert result.stdout.split() == ["base", "extra"]


def test_caller_mapping_is_never_mutated() -> None:
    base = {"A": "1", "B": "base"}
    snapshot = dict(base)
    frozen_env = MappingProxyType({**_platform_floor_env(), **base})
    argv = [PY, "-c", "pass"]
    assert run_command(argv, env={**frozen_env}, env_extra={"B": "extra"}).returncode == 0
    assert base == snapshot  # env_extra overlay must not leak into caller mapping
    assert run_command(argv, env=frozen_env).returncode == 0
    assert base == snapshot


def test_timeout_with_explicit_env_still_kills_and_streams() -> None:
    argv = [
        PY,
        "-c",
        "import os, time; print(os.environ.get('SOT_TVAR', 'MISSING'), flush=True); time.sleep(30)",
    ]
    result = run_command(argv, env={**_platform_floor_env(), "SOT_TVAR": "sentinel-t"}, timeout_seconds=1.0)
    assert result.timed_out is True
    assert result.returncode is None
    assert result.error is None
    assert result.stdout.split() == ["sentinel-t"]  # env applied AND deadline enforced
    assert result.truncated is False


def test_bad_mapping_values_return_run_result_without_raising() -> None:
    argv = [PY, "-c", "pass"]
    result = run_command(argv, env={"OK": "1", "BAD": 123})  # non-str value
    assert isinstance(result, RunResult)
    assert result.returncode is None
    assert result.error is not None


def test_non_mapping_env_returns_run_result_without_raising() -> None:
    result = run_command([PY, "-c", "pass"], env="PATH=/usr/bin")  # type: ignore[arg-type]
    assert isinstance(result, RunResult)
    assert result.returncode is None
    assert result.error is not None


if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--child":
    raise SystemExit(_child_main(sys.argv[2]))
