"""Exact-compatibility context wiring for CodebaseMemoryProvider (P1).

Every executable is a FAKE script whose sha256 is registered in a trusted
``CompatibilityRegistry``. The real ``codebase-memory-mcp`` binary is never
invoked. Trust is digest-exact, so a fake binary that matches its registered
artifact digest is legitimately dispatchable — that is the point.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from conftest import require_shebang_exec

from sot_graph.config import ProviderConfig
from sot_graph.provider_contract import (
    Capability,
    IntegrationMode,
    ProviderIdentity,
)
from sot_graph.providers.base import (
    CoverageRequest,
    IndexRequest,
    SymbolRequest,
)
from sot_graph.providers.codebase_memory import (
    NEXT_ACTION_VERSION_PIN,
    PROBE_OPERATION,
    CodebaseMemoryProvider,
    ExactCompatibilityContext,
)
from sot_graph.providers.compatibility import (
    CompatibilityRecordError,
    CompatibilityRegistry,
    TestedCompatibilityRecord,
)

PROTOCOL = "cbm-cli-json-v1"
FIXTURE = "b" * 64
OTHER_FIXTURE = "c" * 64
VERSION = "0.10.8"
PROVIDER = "codebase-memory"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exe_body(marker: str, root: str | None = None) -> str:
    """Fake cbm CLI: marks every spawn, answers --version and JSON tools."""
    list_projects = (
        f"'list_projects': {{'projects': [{{'name': 'proj', 'root_path': {root!r}}}],"
        " 'has_more': False},\n            "
        if root else ""
    )
    return (
        "import json, sys\n"
        f"open({marker!r}, 'a').write('spawn\\n')\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] == '--version':\n"
        f"    print('codebase-memory-mcp {VERSION}')\n"
        "    sys.exit(0)\n"
        "tool = args[args.index('--json') + 1] if '--json' in args else '?'\n"
        "payloads = {\n            "
        + list_projects +
        "'search_graph': {'rows': [], 'has_more': False},\n"
        "            'index_status': {'status': 'ready'},\n"
        "            'index_repository': {'ok': True}}\n"
        "env = {'content': [{'type': 'text',\n"
        "                    'text': json.dumps(payloads.get(tool, {'tool': tool}))}],\n"
        "       'isError': False, 'structuredContent': {}}\n"
        "print(json.dumps(env))\n"
    )


def make_exe(directory: Path, marker: Path, root: str | None = None) -> str:
    """Write the fake binary and return its ABSOLUTE path (strict context
    forbids PATH discovery, so the adapter command is always this path)."""
    require_shebang_exec()
    if os.name == "nt":
        raise RuntimeError("these tests require a POSIX exec launcher")
    path = directory / "cbm-fake"
    path.write_text(f"#!{sys.executable}\n{_exe_body(str(marker), root)}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def rewrite_exe(path: str, marker: Path) -> str:
    """Swap the executable IN PLACE (same path, new bytes = new digest)."""
    with open(path, "w") as handle:
        handle.write(f"#!{sys.executable}\n# swapped\n{_exe_body(str(marker))}")
    return path


def spawns(marker: Path) -> int:
    return marker.read_text().count("spawn") if marker.exists() else 0


def make_record(artifact: str, operation: str, *, fixture: str = FIXTURE,
                protocol: str = PROTOCOL, version: str | None = VERSION):
    return TestedCompatibilityRecord(
        provider_name=PROVIDER, operation=operation,
        artifact_sha256=artifact, fixture_digest=fixture,
        protocol_compatibility_id=protocol, version=version,
    )


def make_provider(exe: str, artifact: str, operations, *, fixture=FIXTURE,
                  protocol=PROTOCOL, identity_version: str | None = VERSION,
                  record_artifact: str | None = None,
                  record_fixture: str | None = None,
                  record_protocol: str | None = None,
                  record_version: str | None = VERSION):
    """Build a strict provider. ``record_*`` overrides let the TESTED
    evidence (registry records) diverge from the RUNTIME claims (identity,
    fixture digests, protocol id) — that divergence is what the fail-closed
    gates must detect."""
    registry = CompatibilityRegistry()
    for operation in operations:
        registry.register(make_record(
            record_artifact or artifact, operation,
            fixture=record_fixture or fixture,
            protocol=record_protocol or protocol,
            version=record_version,
        ))
    return CodebaseMemoryProvider(
        command=(exe,),
        exact_context=ExactCompatibilityContext(
            registry=registry,
            runtime_identity=ProviderIdentity(
                name=PROVIDER, version=identity_version,
                mode=IntegrationMode.FEDERATED_CLI,
                capability=Capability.SYMBOLS,
                artifact_sha256=artifact,
                protocol_compatibility_id=protocol,
            ),
            operation_fixture_digests={op: fixture for op in operations},
            protocol_compatibility_id=protocol,
        ),
    )


FULL_OPS = ("search_graph", "index_status", PROBE_OPERATION)


def _search(tmp_path: Path):
    return SymbolRequest(repo_root=str(tmp_path), query="x", project="proj")


class TestExactMatchPermitsFakeBinary:
    def test_digest_exact_fake_binary_dispatches(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is True
        # search_graph + snapshot-binding index_status both gated and spawned.
        assert spawns(marker) == 2
        assert outcome.metadata["identity_basis"] == "artifact_verified"
        ec = outcome.metadata["exact_compatibility"]
        assert ec["verdict"] == "compatible"
        assert ec["operation"] == "search_graph"
        assert ec["matched_record"]["operation"] == "search_graph"
        assert ec["matched_record"]["artifact_sha256"] == _sha256(exe)

    def test_assessment_serialization_is_the_single_parser_shape(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        outcome = provider.search_symbols(_search(tmp_path))
        # CLI and MCP consume this same QueryOutcome metadata dict — the
        # CompatibilityAssessment.to_dict() shape, nothing adapter-specific.
        assert set(outcome.metadata["exact_compatibility"]) == {
            "schema_version", "verdict", "reasons", "operation",
            "artifact_sha256", "matched_record",
        }


class TestCallerCannotLie:
    def test_swapped_binary_same_version_refused_without_spawn(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        tested_digest = _sha256(exe)
        provider = make_provider(exe, tested_digest, FULL_OPS)
        assert provider.search_symbols(_search(tmp_path)).ok is True
        before = spawns(marker)
        rewrite_exe(exe, marker)  # same path, same claimed identity, new bytes
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_incompatible"
        assert spawns(marker) == before  # the swapped binary never ran
        assert outcome.metadata["exact_compatibility"]["verdict"] == "incompatible"
        assert outcome.next_action == NEXT_ACTION_VERSION_PIN
        assert outcome.run.next_action == NEXT_ACTION_VERSION_PIN

    def test_claiming_swapped_digest_under_tested_version_refused(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        old_digest = _sha256(exe)
        rewrite_exe(exe, marker)
        new_digest = _sha256(exe)
        # Identity claims the NEW artifact but the SAME tested version
        # string; registry only ever tested the OLD artifact.
        provider = make_provider(exe, new_digest, FULL_OPS,
                                 record_artifact=old_digest)
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_incompatible"
        assert spawns(marker) == 0
        assert "version string does not prove" in " ".join(
            outcome.metadata["exact_compatibility"]["reasons"]
        )

    def test_fresh_hash_each_dispatch_detects_replacement(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        assert provider.search_symbols(_search(tmp_path)).ok is True
        rewrite_exe(exe, marker)
        # No reconstruction, no re-probe: the SAME provider instance must
        # re-hash per dispatch and refuse the replaced binary next call.
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert spawns(marker) == 2


class TestMissingEvidence:
    def test_unsupported_operation_refused_without_spawn(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), ("search_graph",))
        outcome = provider.coverage(
            CoverageRequest(repo_root=str(tmp_path), paths=("a.py",),
                            project="proj")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_unknown"
        assert spawns(marker) == 0
        assert outcome.next_action == NEXT_ACTION_VERSION_PIN

    def test_fixture_digest_mismatch_unknown_no_spawn(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        # Records were tested against FIXTURE; the runtime supplies
        # OTHER_FIXTURE — no evidence covers this suite.
        provider = make_provider(exe, _sha256(exe), FULL_OPS,
                                 fixture=OTHER_FIXTURE, record_fixture=FIXTURE)
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_unknown"
        assert spawns(marker) == 0

    def test_protocol_mismatch_incompatible_no_spawn(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        # Records tested under PROTOCOL; the runtime claims a different wire.
        provider = make_provider(exe, _sha256(exe), FULL_OPS,
                                 protocol="other-protocol-v9",
                                 record_protocol=PROTOCOL)
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_incompatible"
        assert spawns(marker) == 0


class TestPartialContextNoDowngrade:
    def test_partial_contexts_fail_closed_never_legacy(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        artifact = _sha256(exe)
        identity = ProviderIdentity(
            name=PROVIDER, version=VERSION,
            mode=IntegrationMode.FEDERATED_CLI,
            capability=Capability.SYMBOLS,
            artifact_sha256=artifact,
            protocol_compatibility_id=PROTOCOL,
        )
        registry = CompatibilityRegistry()
        registry.register(make_record(artifact, "search_graph"))
        partial = [
            ExactCompatibilityContext(runtime_identity=identity),
            ExactCompatibilityContext(registry=registry),
            ExactCompatibilityContext(runtime_identity=identity,
                                      registry=registry),
            ExactCompatibilityContext(
                runtime_identity=identity,
                operation_fixture_digests={"search_graph": FIXTURE},
                protocol_compatibility_id=PROTOCOL,
            ),
        ]
        for ctx in partial:
            provider = CodebaseMemoryProvider(command=(exe,), exact_context=ctx)
            outcome = provider.search_symbols(_search(tmp_path))
            assert outcome.ok is False, type(ctx).__name__
            assert outcome.metadata["wire_status"] == "compatibility_unknown"
            assert spawns(marker) == 0
            assert outcome.metadata["identity_basis"] == "unverified"
            assert outcome.metadata["version_compatibility"] == "UNKNOWN"
            assert "exact_compatibility" in outcome.metadata


class TestProbeDistinction:
    def test_probe_gated_by_probe_operation_record(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), ("search_graph",))
        status = provider.probe(str(tmp_path))
        assert status.healthy is False
        assert status.version is None
        assert spawns(marker) == 0  # --version is a distinct gated operation

    def test_verified_digest_permits_probe_despite_unknown_version(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        # Records and identity carry version=None: identity is the digest;
        # the probe only fills descriptive metadata.
        provider = make_provider(exe, _sha256(exe), (PROBE_OPERATION,),
                                 identity_version=None)
        status = provider.probe(str(tmp_path))
        assert status.healthy is True
        assert status.version == VERSION
        assert spawns(marker) == 1

    def test_probe_with_record_runs_and_fills_version(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        status = provider.probe(str(tmp_path))
        assert status.healthy is True
        assert status.version == VERSION
        # Strict detail reports the actual gate verdict, not the
        # version-only classification (which is UNKNOWN in strict mode).
        assert status.detail == "ok; exact-compat=compatible"


class TestExplicitIndexGating:
    def test_index_without_record_explicitly_unavailable_no_spawn(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), (PROBE_OPERATION,))
        record = provider.index(IndexRequest(repo_root=str(tmp_path)))
        assert record.status == "compatibility_unknown"
        assert record.next_action == NEXT_ACTION_VERSION_PIN
        assert record.exit_code is None
        assert spawns(marker) == 0  # no mutating fallback

    def test_index_with_record_runs(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe),
                                 ("index_repository", PROBE_OPERATION))
        record = provider.index(IndexRequest(repo_root=str(tmp_path)))
        assert record.status == "ok"
        assert spawns(marker) == 1

    def test_ensure_index_still_abstains_under_strict_context(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), ("index_repository",))
        record = provider.ensure_index(IndexRequest(repo_root=str(tmp_path)))
        assert record.status == "abstained"
        assert spawns(marker) == 0


class TestStrictPathAndCtorValidation:
    def test_relative_command_refused_no_path_discovery(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        provider.command = ("cbm-fake",)  # relative: PATH discovery forbidden
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_unknown"
        assert spawns(marker) == 0
        assert "absolute" in " ".join(
            outcome.metadata["exact_compatibility"]["reasons"]
        )

    def test_missing_executable_unknown_no_spawn(self, tmp_path):
        provider = make_provider(str(tmp_path / "gone"), "a" * 64, FULL_OPS)
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_unknown"
        assert spawns(tmp_path / "marker") == 0

    def test_invalid_fixture_digest_fails_context_construction(self):
        with pytest.raises(CompatibilityRecordError):
            ExactCompatibilityContext(
                operation_fixture_digests={"search_graph": "not-a-digest"},
            )

    def test_non_context_object_rejected_at_construction(self):
        with pytest.raises(TypeError):
            CodebaseMemoryProvider(command=("x",), exact_context=object())


class TestLegacyUnchanged:
    def test_legacy_constructor_keeps_version_only_behavior(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = CodebaseMemoryProvider(command=(exe,))
        status = provider.probe(str(tmp_path))
        assert status.healthy is True
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is True
        assert outcome.metadata["identity_basis"] == "version_only"
        assert "exact_compatibility" not in outcome.metadata
        assert provider.version_compatibility() == "COMPATIBLE"
        assert spawns(marker) == 3  # probe + search + index_status, ungated


class TestStrictCtorCommandValidation:
    def test_interpreter_script_command_rejected_before_spawn(self, tmp_path):
        marker = tmp_path / "marker"
        make_exe(tmp_path, marker)
        script = tmp_path / "payload.py"
        script.write_text("print('pwned')")
        with pytest.raises(ValueError, match="single-element"):
            CodebaseMemoryProvider(
                command=[sys.executable, str(script)],
                exact_context=ExactCompatibilityContext(),
            )
        assert not marker.exists()  # rejected before any spawn

    def test_repo_config_command_rejected_under_strict(self, tmp_path):
        exe = make_exe(tmp_path, tmp_path / "marker")
        cfg = ProviderConfig(name="codebase-memory", command=[exe])
        with pytest.raises(ValueError, match="explicit command"):
            CodebaseMemoryProvider(config=cfg,
                                   exact_context=ExactCompatibilityContext())

    def test_relative_single_command_rejected_at_construction(self, tmp_path):
        make_exe(tmp_path, tmp_path / "marker")
        with pytest.raises(ValueError, match="absolute"):
            make_provider("cbm-fake", "a" * 64, FULL_OPS)

    def test_post_ctor_prefix_mutation_refused_no_spawn_unverified(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        script = tmp_path / "payload.py"
        script.write_text("import json,sys\nprint(json.dumps({'pwned': True}))\n")
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        # Ctor validation passed; the public attribute is reassigned anyway.
        provider.command = [sys.executable, str(script)]
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_unknown"
        assert outcome.metadata["identity_basis"] == "unverified"
        assert outcome.metadata["version_compatibility"] == "UNKNOWN"
        assert not marker.exists()  # the smuggled interpreter+script never ran


class TestTrustNormalizationSafety:
    def test_false_claimed_hash_refused_unverified(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        # Claims a well-formed digest that is neither on disk nor tested.
        provider = make_provider(exe, "e" * 64, FULL_OPS)
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "compatibility_incompatible"
        assert outcome.metadata["identity_basis"] == "unverified"
        assert outcome.metadata["version_compatibility"] == "UNKNOWN"
        assert spawns(marker) == 0

    def test_wrong_record_version_still_exact_supported(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        # Digest-exact match wins even though version strings disagree:
        # the legacy version veto must NOT fire and normalization metadata
        # is exact-backed, never version-only.
        provider = make_provider(exe, _sha256(exe), FULL_OPS,
                                 record_version="9.9.9")
        outcome = provider.search_symbols(_search(tmp_path))
        assert outcome.ok is True
        assert outcome.metadata["wire_status"] == "ok"
        assert outcome.metadata["identity_basis"] == "artifact_verified"
        assert outcome.metadata["version_compatibility"] == "COMPATIBLE"
        assert outcome.metadata["exact_compatibility"]["verdict"] == "compatible"


class TestRefusalRecovery:
    def test_project_refusal_not_cached_and_remediation_preserved(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker, root=str(tmp_path))
        artifact = _sha256(exe)
        operations = ("search_graph", "index_status", PROBE_OPERATION)
        digests = {op: FIXTURE for op in operations}
        registry = CompatibilityRegistry()
        for op in operations:
            registry.register(make_record(artifact, op))
        provider = CodebaseMemoryProvider(
            command=(exe,),
            exact_context=ExactCompatibilityContext(
                registry=registry,
                runtime_identity=ProviderIdentity(
                    name=PROVIDER, version=VERSION,
                    mode=IntegrationMode.FEDERATED_CLI,
                    capability=Capability.SYMBOLS,
                    artifact_sha256=artifact,
                    protocol_compatibility_id=PROTOCOL,
                ),
                operation_fixture_digests=digests,
                protocol_compatibility_id=PROTOCOL,
            ),
        )
        # No explicit project -> list_projects gate has no record: refusal
        # (no spawn), with the compatibility remediation, NOT sync.
        refused = provider.search_symbols(
            SymbolRequest(repo_root=str(tmp_path), query="x")
        )
        assert refused.ok is False
        assert refused.metadata["wire_status"] == "abstained"
        assert refused.next_action == NEXT_ACTION_VERSION_PIN
        assert spawns(marker) == 0
        # Same-instance repair: register the evidence, retry succeeds.
        registry.register(make_record(artifact, "list_projects"))
        digests["list_projects"] = FIXTURE
        recovered = provider.search_symbols(
            SymbolRequest(repo_root=str(tmp_path), query="x")
        )
        assert recovered.ok is True
        assert spawns(marker) == 3  # list_projects + search + index_status

    def test_binary_repair_recovers_same_instance(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        original = Path(exe).read_text()
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        assert provider.search_symbols(_search(tmp_path)).ok is True
        rewrite_exe(exe, marker)
        assert provider.search_symbols(_search(tmp_path)).ok is False
        assert spawns(marker) == 2
        Path(exe).write_text(original)  # binary repaired in place
        recovered = provider.search_symbols(_search(tmp_path))
        assert recovered.ok is True
        assert recovered.metadata["identity_basis"] == "artifact_verified"
        assert spawns(marker) == 4


class TestProbeConcurrency:
    def test_concurrent_probes_deterministic_bounded_spawns(self, tmp_path):
        marker = tmp_path / "marker"
        exe = make_exe(tmp_path, marker)
        provider = make_provider(exe, _sha256(exe), FULL_OPS)
        n = 8
        barrier = threading.Barrier(n)
        results: list = []
        errors: list = []

        def run():
            try:
                barrier.wait(timeout=20)
                results.append(provider.probe(str(tmp_path)))
            except Exception as exc:  # surfaced below, never swallowed
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert errors == []
        assert len(results) == n
        assert all(r.healthy and r.version == VERSION for r in results)
        assert spawns(marker) == n  # exactly one bounded spawn per probe
