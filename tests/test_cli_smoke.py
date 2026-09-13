"""G0.2 smoke: importing the CLI dispatcher must never fail.

Baseline bdb2370 shipped ``cli.py`` using ``Any`` without importing it, so
every ``sotgraph`` invocation died with ``NameError`` before argparse ran and the
whole CI test matrix went red. These tests pin that regression.
"""

import importlib
import subprocess
import sys


def test_cli_module_imports() -> None:
    module = importlib.import_module("sot_graph.cli")
    assert callable(module.main)


def test_cli_version_via_subprocess() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "sotgraph" in proc.stdout.lower()


def test_cli_help_via_subprocess() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage" in proc.stdout.lower()


def test_root_flag_accepted_after_subcommand(tmp_path) -> None:
    """`sotgraph map --root X` must parse like `sotgraph --root X map` —
    global flags are shared via a common parent on every subparser."""
    proc = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "map",
         "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert "unrecognized arguments" not in proc.stderr
    assert proc.returncode != 2  # argparse failure exit code


def test_db_flag_accepted_after_subcommand(tmp_path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "doctor",
         "--root", str(tmp_path), "--db", str(tmp_path / "x.db")],
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert "unrecognized arguments" not in proc.stderr
    assert proc.returncode != 2
