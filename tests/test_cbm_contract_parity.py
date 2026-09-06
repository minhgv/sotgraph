"""P1 CLI/MCP contract parity at the shared orchestrator boundaries (G1).

Deterministic and native-free: the provider command points at a FAKE
runner (reused from ``test_cbm_exact_compatibility.make_exe``) that
records every spawn in a marker file, so "no external spawn" claims are
measured, not assumed. Parity compares two DIFFERENT public surfaces on
the same policy input:

  - CLI surface: ``assurance.federation_plan`` / ``federated_extras``
    (the orchestrator every cli.py federation command routes through);
  - MCP surface: ``McpService.usages`` ``provider_policy`` handling
    (``_require_satisfiable_policy`` + ``_honest_policy_meta``).

Policies: failure (required-but-unavailable fails closed, never silent
partial), version (unhealthy/unknown version degrades explicitly),
builtin_only (zero external spawns, honest metadata). Strict
programmatic context only — no public CLI for managed defaults (P2).
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from sot_graph.assurance import federation_plan, federated_extras
from sot_graph.config import (
    ENV_PROVIDERS_ALLOW_EXTERNAL,
    ENV_PROVIDERS_MODE,
)
from sot_graph.mcp_service import McpService, McpServiceError

from conftest import require_shebang_exec
from test_cbm_exact_compatibility import VERSION, make_exe, spawns
from test_p2_orchestrator import repo as repo_fixture

repo = repo_fixture  # Register the reused fixture under its original name.

PROVIDER = "codebase-memory"


def _write_config(repo: Path, *, allow_external: bool, command) -> None:
    """Write ``<repo>/.sot/config.toml`` (same layer cli.py resolves)."""
    (repo / ".sot" / "config.toml").write_text(
        f"allow_external = {str(allow_external).lower()}\n"
        f"[providers.{PROVIDER}]\n"
        f"command = {json.dumps([str(command)])}\n",
        encoding="utf-8",
    )


def _mcp(repo: Path) -> McpService:
    return McpService(str(repo / ".sot" / "sot.db"), str(repo))


def _broken_version_exe(directory: Path, marker: Path) -> str:
    """Fake runner whose ``--version`` output does NOT match the native
    version pattern (drives the unknown-version policy branch)."""
    require_shebang_exec()
    path = directory / "cbm-broken"
    path.write_text(
        f"#!{sys.executable}\n"
        f"open({str(marker)!r}, 'a').write('spawn\\n')\n"
        "print('garbage-no-version-token')\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


@pytest.fixture()
def clean_provider_env(monkeypatch):
    monkeypatch.delenv(ENV_PROVIDERS_MODE, raising=False)
    monkeypatch.delenv(ENV_PROVIDERS_ALLOW_EXTERNAL, raising=False)


# Reviewer round 2, bug 2: skip ONLY fake-executable subprocess classes
# on Windows; failure policy and pure digest inventory stay cross-platform.
_fake_exec = pytest.mark.skipif(
    os.name == "nt",
    reason="fake runner needs a POSIX exec launcher (shebang script)",
)


@_fake_exec
class TestBuiltinOnlyPolicy:
    def test_builtin_spec_never_spawns_on_either_surface(
        self, repo, tmp_path, clean_provider_env
    ):
        marker = tmp_path / "spawn-marker"
        exe = make_exe(tmp_path, marker)  # wired but must never run
        _write_config(repo, allow_external=True, command=exe)
        plan = federation_plan("builtin", str(repo), "usages")
        assert plan["mode"] == "builtin"
        assert plan["provider"] is None
        assert plan["fail_message"] is None
        assert spawns(marker) == 0, "builtin spec must not spawn the runner"
        res = _mcp(repo).usages("target", provider_policy="builtin_only")
        assert res["policy"]["builtin_only"] is True
        assert res["policy"]["note"] is None
        assert spawns(marker) == 0, "MCP builtin_only path must not spawn either"


class TestFailurePolicyParity:
    def test_required_provider_fails_closed_on_both_surfaces(
        self, repo, tmp_path, clean_provider_env
    ):
        _write_config(repo, allow_external=True,
                      command=tmp_path / "no-such-cbm-binary")
        plan = federation_plan(f"require:{PROVIDER}", str(repo), "usages")
        assert plan["provider"] is None
        assert plan["fail_message"], "require must fail closed, not degrade"
        assert plan["fail_message"].endswith("failing closed")
        fed = federated_extras(
            f"require:{PROVIDER}", str(repo), "usages", "target"
        )
        assert fed["fail_message"]
        assert fed["candidates"] == []
        assert fed["providers_extra"] == []
        with pytest.raises(McpServiceError) as err:
            _mcp(repo).usages("target", provider_policy="require_external")
        assert err.value.code == "policy_unsatisfiable"


@_fake_exec
class TestVersionPolicyParity:
    def test_healthy_probe_reports_pinned_version_single_spawn(
        self, repo, tmp_path, clean_provider_env
    ):
        marker = tmp_path / "spawn-marker"
        exe = make_exe(tmp_path, marker)
        _write_config(repo, allow_external=True, command=exe)
        plan = federation_plan(f"prefer:{PROVIDER}", str(repo), "usages")
        assert plan["fail_message"] is None
        assert plan["provider"] is not None
        assert plan["statuses"][0]["healthy"] is True
        assert plan["statuses"][0]["version"] == VERSION
        assert spawns(marker) == 1, "exactly one probe spawn per CLI plan"

    def test_unknown_version_degrades_explicitly_never_silently(
        self, repo, tmp_path, clean_provider_env
    ):
        marker = tmp_path / "spawn-marker"
        exe = _broken_version_exe(tmp_path, marker)
        _write_config(repo, allow_external=True, command=exe)
        plan = federation_plan(f"prefer:{PROVIDER}", str(repo), "usages")
        assert plan["provider"] is None, "unhealthy provider must not be used"
        assert plan["statuses"][0]["healthy"] is False
        assert plan["statuses"][0]["version"] is None
        assert any(
            "unavailable" in w and "unparseable version" in w
            for w in plan["warnings"]
        ), "degrade must be explicit"
        res = _mcp(repo).usages("target", provider_policy="prefer_external")
        assert res["policy"]["builtin_only"] is False
        assert "builtin served" in res["policy"]["note"], (
            "MCP must admit it serves builtin only for prefer_external"
        )


class TestGoldenFixtureSuiteInventory:
    """Goldens untouched; digest recomputes with the P0 algorithm and
    must match the EMBEDDED constant. The historical untracked receipt
    ``plan/.../golden-fixture-manifest.json`` is NOT a clean-checkout
    dependency (reviewer round 2, bug 1)."""

    EXPECTED_ALGORITHM = (  # pinned for drift, informational
        "sha256 over sorted 'relpath\\0sha256\\n' lines, walk sorted"
    )
    #: Full-suite digest recorded 2026-09-05 (P0 manifest, verified twice).
    EXPECTED_SUITE_DIGEST = (
        "bd65c856ce16af5004109cd941c334a95446eff02d9dce6a98f5fd7eb0c40a64"
    )
    #: Canonical inventory: 7 native tool fixtures + _meta.json.
    EXPECTED_FILES = (
        "_meta.json",
        "check_index_coverage.json",
        "detect_changes.json",
        "get_architecture.json",
        "index_status.json",
        "list_projects.json",
        "search_graph.json",
        "trace_path.json",
    )

    def test_suite_digest_matches_recorded_constant(self):
        fixtures = (
            Path(__file__).resolve().parent / "fixtures" / "cbm_golden"
        )
        lines = []
        for path in sorted(fixtures.rglob("*")):
            if path.is_file():
                rel = path.relative_to(fixtures).as_posix()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                lines.append(f"{rel}\0{digest}\n")
        suite_digest = hashlib.sha256(
            "".join(lines).encode("utf-8")
        ).hexdigest()
        assert tuple(sorted(
            line.split("\0", 1)[0] for line in lines
        )) == self.EXPECTED_FILES
        assert len(lines) == 8  # 7 tools + _meta.json
        assert suite_digest == self.EXPECTED_SUITE_DIGEST
