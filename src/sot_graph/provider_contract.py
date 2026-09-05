"""Provider contract for the Verified Code Evidence & Change-Safety Layer.

Defines the normalized assertion/evidence vocabulary shared by every extractor
provider (sot-builtin, scip importer, federated CLI adapters). Purely additive:
no existing module imports this yet; adapters in later phases consume it.

Field rules (contract):
- Unknown values MUST be ``None`` or ``"unknown"`` — never fabricated defaults.
- Every evidence envelope binds to exactly one snapshot id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ENVELOPE_SCHEMA_VERSION = 1

#: VerificationResult.status vocabulary (same constant the docstring lists).
#: Used only by EvidenceEnvelope.validate as an additive guard.
VERIFICATION_STATUS_VOCABULARY = frozenset(
    {"SUPPORTED", "HEURISTIC", "AMBIGUOUS", "STALE", "UNVERIFIABLE"}
)

#: Exact sha256 hex digest (64 hex chars), optionally ``sha256:``-prefixed.
_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def normalize_sha256_digest(value: str) -> str:
    """Normalize a sha256 digest to bare lowercase 64-hex (``sha256:`` prefix optional).

    Raises ``ValueError`` on malformed input — never silently coerces, so a
    truncated or fabricated digest cannot masquerade as a content identity.
    """
    if not isinstance(value, str):
        raise ValueError(f"sha256 digest must be a string, got {type(value).__name__}")
    match = _SHA256_RE.match(value.strip())
    if match is None:
        raise ValueError(f"malformed sha256 digest: {value!r}")
    return match.group(1).lower()


class Capability(str, Enum):
    """Capability advertised by a provider."""

    SYMBOLS = "symbols"
    CALLGRAPH = "callgraph"
    IMPACT = "impact"
    TRACE = "trace"
    PDG = "pdg"
    TAINT = "taint"
    ARCHITECTURE = "architecture"
    BROAD_LANGUAGE_DISCOVERY = "broad-language-discovery"
    REPO_MAP = "repo-map"
    SOURCE_VERIFICATION = "source-verification"


class IntegrationMode(str, Enum):
    """How SOT-Graph talks to the provider (priority order for rollout)."""

    EMBEDDED = "embedded"
    IMPORT = "import"
    FEDERATED_CLI = "federated-cli"
    FEDERATED_MCP = "federated-mcp"


@dataclass(frozen=True)
class ProviderIdentity:
    """Who produced an assertion.

    ``version`` is a detected release string — it is descriptive metadata,
    never binary identity. ``artifact_sha256`` (exact sha256 of the installed
    binary/artifact) is the only identity-bearing field. All three extra
    fields are optional so existing positional construction and the default
    ``EvidenceEnvelope.to_dict`` shape are preserved unchanged.
    """

    name: str
    version: str | None
    mode: IntegrationMode
    capability: Capability
    engine_commit: str | None = None
    artifact_sha256: str | None = None
    protocol_compatibility_id: str | None = None


@dataclass(frozen=True)
class SnapshotBinding:
    """Which source snapshot an assertion was captured against.

    Mirrors the ``snapshots`` table (schema v6). ``snapshot_id=None`` means
    UNBOUND: the assertion may not participate in PROVEN decisions.
    """

    repository_root: str
    commit_sha: str | None
    worktree_fingerprint: str | None
    manifest_digest: str | None
    dirty: bool
    snapshot_id: str | None


@dataclass(frozen=True)
class Subject:
    """The code entity an assertion is about."""

    kind: str
    qualified_name: str
    path: str
    start_line: int | None
    end_line: int | None
    content_hash: str | None


@dataclass(frozen=True)
class Assertion:
    """A single provider claim about a relation between subjects."""

    relation: str
    target: str
    provider_confidence: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    """SOT-Graph verification outcome for one assertion."""

    status: str  # SUPPORTED | HEURISTIC | AMBIGUOUS | STALE | UNVERIFIABLE
    source_span_verified: bool
    snapshot_verified: bool
    conflicts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Normalized evidence record every adapter must emit (guide §5)."""

    provider: ProviderIdentity
    snapshot: SnapshotBinding
    subject: Subject
    assertion: Assertion
    verification: VerificationResult
    schema_version: int = ENVELOPE_SCHEMA_VERSION

    def validate(self) -> list[str]:
        """Return contract violations; empty list means valid."""
        problems: list[str] = []
        if self.verification.status not in VERIFICATION_STATUS_VOCABULARY:
            problems.append(
                f"verification.status {self.verification.status!r} outside contract vocabulary"
            )
        if self.snapshot.snapshot_id is None and self.verification.status == "SUPPORTED":
            problems.append("UNBOUND snapshot cannot yield SUPPORTED")
        if self.provider.mode is IntegrationMode.FEDERATED_CLI and self.provider.version is None:
            problems.append("federated-cli provider must report detected version or 'unknown'")
        if self.assertion.provider_confidence is not None and not (
            0.0 <= self.assertion.provider_confidence <= 1.0
        ):
            problems.append("provider_confidence outside [0,1]")
        if not isinstance(self.subject.path, str) or not self.subject.path:
            problems.append("subject.path must be a non-empty string")
        elif self.subject.path.startswith("/"):
            problems.append("subject.path must be repo-relative, not absolute")
        if self.provider.artifact_sha256 is not None:
            try:
                normalize_sha256_digest(self.provider.artifact_sha256)
            except ValueError:
                problems.append("provider.artifact_sha256 is not a valid sha256 digest")
        for _fname in ("engine_commit", "protocol_compatibility_id"):
            _fval = getattr(self.provider, _fname)
            if isinstance(_fval, str) and not _fval.strip():
                problems.append(f"provider.{_fname} must be non-empty when present")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": {
                "name": self.provider.name,
                "version": self.provider.version,
                "mode": self.provider.mode.value,
                "capability": self.provider.capability.value,
                # Additive identity fields: serialized only when set so the
                # default (unset) dict shape stays byte-identical for
                # consumers of the P0 vocabulary.
                **(
                    {}
                    if self.provider.engine_commit is None
                    else {"engine_commit": self.provider.engine_commit}
                ),
                **(
                    {}
                    if self.provider.artifact_sha256 is None
                    else {"artifact_sha256": self.provider.artifact_sha256}
                ),
                **(
                    {}
                    if self.provider.protocol_compatibility_id is None
                    else {"protocol_compatibility_id": self.provider.protocol_compatibility_id}
                ),
            },
            "snapshot": {
                "repository_root": self.snapshot.repository_root,
                "commit": self.snapshot.commit_sha,
                "worktree_fingerprint": self.snapshot.worktree_fingerprint,
                "manifest_digest": self.snapshot.manifest_digest,
                "dirty": self.snapshot.dirty,
                "snapshot_id": self.snapshot.snapshot_id,
            },
            "subject": {
                "kind": self.subject.kind,
                "qualified_name": self.subject.qualified_name,
                "path": self.subject.path,
                "start_line": self.subject.start_line,
                "end_line": self.subject.end_line,
                "content_hash": self.subject.content_hash,
            },
            "assertion": {
                "relation": self.assertion.relation,
                "target": self.assertion.target,
                "provider_confidence": self.assertion.provider_confidence,
                "metadata": self.assertion.metadata,
            },
            "verification": {
                "status": self.verification.status,
                "source_span_verified": self.verification.source_span_verified,
                "snapshot_verified": self.verification.snapshot_verified,
                "conflicts": self.verification.conflicts,
            },
        }
