"""Explicit admin-only assembly of a promoted artifact and managed provider.

No config discovery, installation, preparation, process launch, or ledger I/O.
Artifact schema protocol and tested native wire protocol are separate pins.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from sot_graph.provider_contract import Capability, IntegrationMode, ProviderIdentity

from .artifacts import ArtifactDescriptor, ArtifactRejected, ArtifactStore, host_platform
from .codebase_memory import CodebaseMemoryProvider, ExactCompatibilityContext
from .compatibility import CompatibilityRecordError, CompatibilityRegistry, CompatibilityVerdict
from .managed import ManagedNativeRuntime
from .runtime import ManagedRuntimeProfile


@dataclass(frozen=True)
class ManagedInstallation:
    """Bound objects; call ``runtime.prepare()`` explicitly before native use."""

    artifact: ArtifactDescriptor
    exact_context: ExactCompatibilityContext
    profile: ManagedRuntimeProfile
    runtime: ManagedNativeRuntime
    provider: CodebaseMemoryProvider


def _require_disjoint(left: str, right: str, label: str) -> None:
    """Reject lexical containment and existing filesystem identity aliases.

    Walk through missing tails to existing ancestors; realpath alone does not
    normalize case on case-insensitive filesystems. Only absence is ignored:
    permission and other unexpected filesystem errors must fail closed.
    """
    if os.path.commonpath((left, right)) in (left, right):
        raise ArtifactRejected(f"{label} must be disjoint in both directions")
    for root, candidate in ((left, right), (right, left)):
        missing: tuple[str, ...] = ()
        while True:
            try:
                os.stat(root)
                break
            except FileNotFoundError:
                missing = (os.path.basename(root), *missing)
                parent = os.path.dirname(root)
                if parent == root:
                    raise
                root = parent
        suffix: tuple[str, ...] = ()
        while True:
            try:
                if os.path.samefile(root, candidate) and suffix[:len(missing)] == missing:
                    raise ArtifactRejected(f"{label} must be disjoint in both directions")
            except FileNotFoundError:
                pass
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            suffix = (os.path.basename(candidate), *suffix)
            candidate = parent


def create_managed_installation(
    store: ArtifactStore,
    *,
    artifact_name: str,
    repo_path: str | os.PathLike[str],
    runtime_root: str | os.PathLike[str],
    registry: CompatibilityRegistry,
    operation_fixture_digests: Mapping[str, str],
    native_protocol_id: str,
    generation: str = "initial",
) -> ManagedInstallation:
    """Resolve ONLY an explicitly promoted artifact from a trusted store.

    ``native_protocol_id`` must identify tested native wire records, NOT the
    descriptor's artifact schema protocol. The registry and operation digests
    are administrator-supplied evidence, never read from repository config.
    Required managed operations are validated by ManagedNativeRuntime; every
    supplied operation must additionally have exact tested registry evidence.
    A new explicit ``generation`` selects a fresh profile namespace without
    deleting or preparing the old one. All failures propagate; no legacy path.
    """
    if not isinstance(store, ArtifactStore):
        raise TypeError("store must be a trusted ArtifactStore")
    if sys.platform not in {"darwin", "linux"}:
        raise ArtifactRejected("managed installation supports only Darwin and Linux")
    # Revalidate against the actual repo, not the repo used to build the store.
    # Shared stores are allowed; no pair may be equal or contain the other.
    repo = os.path.realpath(repo_path)
    canonical_runtime = os.path.realpath(runtime_root)
    artifact_root = os.path.realpath(store.root)
    for left, right, label in (
        (repo, artifact_root, "repository and artifact root"),
        (canonical_runtime, artifact_root, "runtime and artifact roots"),
        (canonical_runtime, repo, "runtime root and repository"),
    ):
        _require_disjoint(left, right, label)
    artifact = store.resolve(artifact_name)
    if artifact is None:
        raise ArtifactRejected("no explicitly promoted artifact")
    if artifact.platform != host_platform():
        raise ArtifactRejected("promoted artifact does not match the runtime host")
    if not isinstance(registry, CompatibilityRegistry):
        raise TypeError("registry must be a CompatibilityRegistry")
    if not isinstance(operation_fixture_digests, Mapping):
        raise TypeError("operation_fixture_digests must be a Mapping")
    if not isinstance(native_protocol_id, str) or not native_protocol_id.strip():
        raise CompatibilityRecordError("explicit native_protocol_id is required")
    identity = ProviderIdentity(
        name="codebase-memory", version=None,
        mode=IntegrationMode.FEDERATED_CLI, capability=Capability.SYMBOLS,
        engine_commit=artifact.engine_commit, artifact_sha256=artifact.digest,
        protocol_compatibility_id=native_protocol_id,
    )
    context = ExactCompatibilityContext(
        registry=registry, runtime_identity=identity,
        operation_fixture_digests=MappingProxyType(dict(operation_fixture_digests)),
        protocol_compatibility_id=native_protocol_id,
    )
    for operation, digest in context.operation_fixture_digests.items():
        assessment = registry.assess(identity, operation, digest, native_protocol_id)
        if assessment.verdict != CompatibilityVerdict.COMPATIBLE:
            raise CompatibilityRecordError(
                f"no exact tested compatibility for operation {operation!r}")
    profile = ManagedRuntimeProfile(
        runtime_root, repo_path, artifact_digest=artifact.digest, generation=generation)
    command = (artifact.executable,)
    runtime = ManagedNativeRuntime(profile, os.fspath(repo_path), command, context)
    provider = CodebaseMemoryProvider(
        command=command, exact_context=context, managed_runtime=runtime)
    return ManagedInstallation(artifact, context, profile, runtime, provider)
