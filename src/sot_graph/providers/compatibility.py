"""Per-artifact provider compatibility contract (P1).

A real compatibility contract, not version-string masquerading as binary
identity: a provider binary is COMPATIBLE only when the EXACT artifact
(sha256 of the installed binary) was explicitly tested against the EXACT
fixture-suite digest, under the EXACT normalized protocol id, for the
requested operation. Everything else is UNKNOWN or INCOMPATIBLE with
explicit reasons — never an implicit default promising compatibility.

Trust model:
- The registry is EMPTY by default and grows only via user-supplied,
  validated :class:`TestedCompatibilityRecord` instances. Nothing here
  claims that an installed binary's historical fixtures are physically
  bound — that evidence must be registered explicitly.
- ``identity=None`` (legacy external path) keeps existing behavior
  upstream and is assessed UNKNOWN here, never COMPATIBLE.
- Thread-safe, pure in-memory, no I/O, no import side effects.

Adapters may later opt into an exact registry context (followup) by
constructing a registry, registering tested records, and calling
:meth:`CompatibilityRegistry.assess` with the runtime
``ProviderIdentity``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, fields, MISSING
from enum import Enum
from typing import Any, Mapping

from sot_graph.provider_contract import (
    Capability,
    ProviderIdentity,
    normalize_sha256_digest,
)

COMPATIBILITY_SCHEMA_VERSION = 1

#: Literal sentinel some probes report instead of a real version string.
#: It never binds a version-string equality check (only digests do).
UNKNOWN_VERSION_LITERALS = frozenset({"unknown", "n/a", "none", ""})


class CompatibilityVerdict(str, Enum):
    """Explicit assessment outcome — no fourth "assume yes" state exists."""

    COMPATIBLE = "compatible"
    UNKNOWN = "unknown"
    INCOMPATIBLE = "incompatible"


class CompatibilityRecordError(ValueError):
    """A tested-compatibility record (or assessment input) failed validation."""


def normalize_protocol_id(value: str) -> str:
    """Normalize a protocol compatibility id (trim + lowercase).

    Raises ``CompatibilityRecordError`` on non-strings or empty input.
    """
    if not isinstance(value, str):
        raise CompatibilityRecordError(
            f"protocol_compatibility_id must be a string, got {type(value).__name__}"
        )
    normalized = value.strip().lower()
    if not normalized:
        raise CompatibilityRecordError("protocol_compatibility_id must be non-empty")
    return normalized


def _normalize_operation(operation: str | Capability) -> str:
    if isinstance(operation, Capability):
        return operation.value
    if not isinstance(operation, str):
        raise CompatibilityRecordError(
            f"operation must be a string or Capability, got {type(operation).__name__}"
        )
    normalized = operation.strip()
    if not normalized:
        raise CompatibilityRecordError("operation must be non-empty")
    return normalized


def _binding_version(version: str | None) -> str | None:
    """Return a version usable for equality binding, else None.

    ``None``, non-string garbage, and unknown-sentinel literals never bind:
    two artifacts whose probes both said "unknown" must not be treated as
    the same version.
    """
    if version is None or not isinstance(version, str):
        return None
    cleaned = version.strip().lower()
    if cleaned in UNKNOWN_VERSION_LITERALS:
        return None
    return cleaned


def _normalize_required_text(record_type: str, name: str, value: str) -> str:
    if not isinstance(value, str):
        raise CompatibilityRecordError(
            f"{record_type}.{name} must be a string, got {type(value).__name__}"
        )
    cleaned = value.strip()
    if not cleaned:
        raise CompatibilityRecordError(f"{record_type}.{name} must be non-empty")
    return cleaned


def _normalize_optional_text(record_type: str, name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_required_text(record_type, name, value)


def _normalize_record_digest(record_type: str, name: str, value: str) -> str:
    try:
        return normalize_sha256_digest(value)
    except ValueError as exc:
        raise CompatibilityRecordError(f"{record_type}.{name}: {exc}") from exc


@dataclass(frozen=True)
class TestedCompatibilityRecord:
    """Immutable claim: the EXACT artifact was tested for one operation.

    Validation is bounded and eager (``__post_init__``): malformed digests,
    empty provider/operation text, and un-normalizable protocol ids fail
    construction explicitly. Digests are normalized to bare lowercase
    64-hex; the protocol id is normalized (trim + lowercase) so record
    equality is exact-byte identity, not string cosmetics.

    Unknown fields are explicit: the dataclass signature rejects unknown
    kwargs with ``TypeError``, and :meth:`from_dict` rejects unknown keys
    with :class:`CompatibilityRecordError` (dict payloads are untrusted).
    """

    provider_name: str
    operation: str
    artifact_sha256: str
    fixture_digest: str
    protocol_compatibility_id: str
    version: str | None = None
    engine_commit: str | None = None
    tested_by: str | None = None
    tested_at: str | None = None
    #: Only schema 1 exists. Serializers always emit it; ``from_dict`` treats
    #: an OMITTED schema_version as 1 (explicit legacy policy for pre-schema
    #: payloads) while a PRESENT value must be the integer 1 — bools, numeric
    #: strings, and unsupported versions are rejected.
    schema_version: int = COMPATIBILITY_SCHEMA_VERSION

    #: Not a pytest test class despite the ``Test`` prefix.
    __test__ = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != COMPATIBILITY_SCHEMA_VERSION
        ):
            raise CompatibilityRecordError(
                f"record.schema_version must be the integer {COMPATIBILITY_SCHEMA_VERSION}, "
                f"got {self.schema_version!r}"
            )
        object.__setattr__(self, "provider_name", _normalize_required_text("record", "provider_name", self.provider_name))
        object.__setattr__(self, "operation", _normalize_operation(self.operation))
        object.__setattr__(self, "artifact_sha256", _normalize_record_digest("record", "artifact_sha256", self.artifact_sha256))
        object.__setattr__(self, "fixture_digest", _normalize_record_digest("record", "fixture_digest", self.fixture_digest))
        object.__setattr__(self, "protocol_compatibility_id", normalize_protocol_id(self.protocol_compatibility_id))
        object.__setattr__(self, "version", _normalize_optional_text("record", "version", self.version))
        object.__setattr__(self, "engine_commit", _normalize_optional_text("record", "engine_commit", self.engine_commit))
        object.__setattr__(self, "tested_by", _normalize_optional_text("record", "tested_by", self.tested_by))
        object.__setattr__(self, "tested_at", _normalize_optional_text("record", "tested_at", self.tested_at))

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        """Exact lookup key: (provider, operation, artifact, fixture, protocol)."""
        return (
            self.provider_name,
            self.operation,
            self.artifact_sha256,
            self.fixture_digest,
            self.protocol_compatibility_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_name": self.provider_name,
            "operation": self.operation,
            "artifact_sha256": self.artifact_sha256,
            "fixture_digest": self.fixture_digest,
            "protocol_compatibility_id": self.protocol_compatibility_id,
            "version": self.version,
            "engine_commit": self.engine_commit,
            "tested_by": self.tested_by,
            "tested_at": self.tested_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TestedCompatibilityRecord:
        """Build a record from an untrusted mapping; unknown keys are explicit errors.

        Legacy policy: a payload WITHOUT ``schema_version`` is treated as
        schema 1; a present value must be the supported integer.
        """
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(payload) - known)
        if unknown:
            raise CompatibilityRecordError(f"unknown record field(s): {', '.join(unknown)}")
        optional = {
            f.name for f in fields(cls) if f.default is not MISSING or f.default_factory is not MISSING
        }
        missing = sorted(known - optional - set(payload))
        if missing:
            raise CompatibilityRecordError(f"missing required field(s): {', '.join(missing)}")
        if "schema_version" in payload and (
            isinstance(payload["schema_version"], bool)
            or not isinstance(payload["schema_version"], int)
        ):
            raise CompatibilityRecordError(
                "record.schema_version must be the integer "
                f"{COMPATIBILITY_SCHEMA_VERSION}, got {payload['schema_version']!r}"
            )
        return cls(**dict(payload))


@dataclass(frozen=True)
class CompatibilityAssessment:
    """Result of assessing a runtime identity against the tested registry."""

    verdict: CompatibilityVerdict
    reasons: tuple[str, ...]
    operation: str
    artifact_sha256: str | None = None
    matched_record: TestedCompatibilityRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMPATIBILITY_SCHEMA_VERSION,
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "operation": self.operation,
            "artifact_sha256": self.artifact_sha256,
            "matched_record": None if self.matched_record is None else self.matched_record.to_dict(),
        }


class CompatibilityRegistry:
    """In-memory registry of user-supplied tested-compatibility records.

    Starts empty (no hardcoded trust). All mutation and lookup go through
    one re-entrant lock; there is no I/O and no import-time state.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str, str, str, str], TestedCompatibilityRecord] = {}

    def register(self, record: TestedCompatibilityRecord) -> None:
        """Register a validated tested record.

        Re-registering a byte-identical record under the same exact key is an
        idempotent no-op; a different record under the same key is an explicit
        ``CompatibilityRecordError`` (silently replacing test evidence would
        erode the chain of custody).
        """
        if not isinstance(record, TestedCompatibilityRecord):
            raise CompatibilityRecordError(
                f"register() requires a TestedCompatibilityRecord, got {type(record).__name__}"
            )
        with self._lock:
            existing = self._records.get(record.key)
            if existing is not None and existing != record:
                raise CompatibilityRecordError(
                    "conflicting tested record for key "
                    f"{record.key}: existing record differs from new one"
                )
            self._records[record.key] = record

    def records(self) -> tuple[TestedCompatibilityRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def assess(
        self,
        identity: ProviderIdentity | None,
        operation: str | Capability,
        fixture_digest: str | None = None,
        protocol_compatibility_id: str | None = None,
    ) -> CompatibilityAssessment:
        """Assess a runtime identity; every outcome carries explicit reasons.

        - ``identity is None``: the legacy external path without identity is
          UNKNOWN here (existing upstream behavior is untouched) — never
          assumed compatible.
        - Same version string with a different artifact digest is
          INCOMPATIBLE: the version string provably does not bind the binary.
        - Missing fixture digest / protocol id on an otherwise exact match is
          UNKNOWN: no evidence, no implicit promise.
        """
        op = _normalize_operation(operation)

        fx: str | None = None
        if fixture_digest is not None:
            try:
                fx = normalize_sha256_digest(fixture_digest)
            except ValueError as exc:
                raise CompatibilityRecordError(f"fixture_digest: {exc}") from exc

        proto: str | None = None
        if protocol_compatibility_id is not None:
            proto = normalize_protocol_id(protocol_compatibility_id)

        if identity is None:
            return CompatibilityAssessment(
                verdict=CompatibilityVerdict.UNKNOWN,
                reasons=(
                    "provider identity is None: legacy external path is outside "
                    "this compatibility contract and is never assumed compatible",
                ),
                operation=op,
            )

        if not isinstance(identity, ProviderIdentity):
            raise CompatibilityRecordError(
                f"identity must be a ProviderIdentity or None, got {type(identity).__name__}"
            )

        if identity.artifact_sha256 is None:
            return CompatibilityAssessment(
                verdict=CompatibilityVerdict.UNKNOWN,
                reasons=(
                    "runtime identity carries no artifact_sha256; the version "
                    f"string {identity.version!r} does not identify a binary",
                ),
                operation=op,
                artifact_sha256=None,
            )

        if not isinstance(identity.name, str):
            raise CompatibilityRecordError(
                f"identity.name must be a string, got {type(identity.name).__name__}"
            )
        provider_name = identity.name.strip()

        try:
            artifact = normalize_sha256_digest(identity.artifact_sha256)
        except ValueError as exc:
            raise CompatibilityRecordError(f"identity.artifact_sha256: {exc}") from exc

        with self._lock:
            snapshot = list(self._records.values())

        exact = [
            r
            for r in snapshot
            if r.provider_name == provider_name
            and r.operation == op
            and r.artifact_sha256 == artifact
        ]
        if exact:
            if proto is None:
                return CompatibilityAssessment(
                    verdict=CompatibilityVerdict.UNKNOWN,
                    reasons=(
                        "exact artifact record(s) exist but the runtime protocol "
                        "compatibility id is unknown; compatibility cannot be bound",
                    ),
                    operation=op,
                    artifact_sha256=artifact,
                )
            protocol_matches = [r for r in exact if r.protocol_compatibility_id == proto]
            if not protocol_matches:
                tested_protocols = sorted({r.protocol_compatibility_id for r in exact})
                return CompatibilityAssessment(
                    verdict=CompatibilityVerdict.INCOMPATIBLE,
                    reasons=(
                        f"artifact {artifact} was tested under protocol id(s) "
                        f"{tested_protocols}, not {proto!r}: the wire contract differs",
                    ),
                    operation=op,
                    artifact_sha256=artifact,
                )
            if fx is None:
                return CompatibilityAssessment(
                    verdict=CompatibilityVerdict.UNKNOWN,
                    reasons=(
                        "exact artifact record(s) exist but no fixture-suite digest "
                        "was supplied; refusing an implicit compatibility promise",
                    ),
                    operation=op,
                    artifact_sha256=artifact,
                )
            fixture_matches = [r for r in protocol_matches if r.fixture_digest == fx]
            if not fixture_matches:
                tested_fixtures = sorted({r.fixture_digest for r in protocol_matches})
                return CompatibilityAssessment(
                    verdict=CompatibilityVerdict.UNKNOWN,
                    reasons=(
                        f"artifact {artifact} was tested against fixture suite(s) "
                        f"{tested_fixtures}, not {fx}: no test evidence covers this suite",
                    ),
                    operation=op,
                    artifact_sha256=artifact,
                )
            matched = fixture_matches[0]
            reasons = [
                f"exact artifact digest match ({artifact})",
                f"fixture-suite digest match ({fx})",
                f"protocol id match ({proto})",
            ]
            runtime_version = _binding_version(identity.version)
            record_version = _binding_version(matched.version)
            if runtime_version is not None and record_version is not None and runtime_version != record_version:
                reasons.append(
                    "note: version string differs from the tested record "
                    f"({identity.version!r} vs {matched.version!r}) but the binary "
                    "identity is digest-exact"
                )
            if (
                isinstance(identity.engine_commit, str)
                and matched.engine_commit is not None
                and identity.engine_commit.strip() != matched.engine_commit
            ):
                reasons.append(
                    "note: engine commit differs from the tested record "
                    f"({identity.engine_commit!r} vs {matched.engine_commit!r}) but "
                    "the binary identity is digest-exact"
                )
            return CompatibilityAssessment(
                verdict=CompatibilityVerdict.COMPATIBLE,
                reasons=tuple(reasons),
                operation=op,
                artifact_sha256=artifact,
                matched_record=matched,
            )

        # No exact-digest evidence. Explicitly reject the masquerade case:
        # same provider + same binding version string, different artifact.
        runtime_version = _binding_version(identity.version)
        if runtime_version is not None:
            masquerades = [
                r
                for r in snapshot
                if r.provider_name == provider_name
                and r.operation == op
                and _binding_version(r.version) == runtime_version
            ]
            if masquerades:
                tested_artifacts = sorted({r.artifact_sha256 for r in masquerades})
                return CompatibilityAssessment(
                    verdict=CompatibilityVerdict.INCOMPATIBLE,
                    reasons=(
                        f"version {identity.version!r} matches tested record(s) for "
                        f"artifact(s) {tested_artifacts} but the installed artifact "
                        f"digest is {artifact}: a version string does not prove "
                        "binary identity",
                    ),
                    operation=op,
                    artifact_sha256=artifact,
                )

        detail = (
            f"no tested compatibility record for provider {provider_name!r}, "
            f"operation {op!r}, artifact {artifact}"
        )
        if fx is not None:
            detail += f", fixture suite {fx}"
        if proto is not None:
            detail += f", protocol id {proto!r}"
        return CompatibilityAssessment(
            verdict=CompatibilityVerdict.UNKNOWN,
            reasons=(detail + "; the operation is unsupported by current compatibility evidence",),
            operation=op,
            artifact_sha256=artifact,
        )


__all__ = [
    "COMPATIBILITY_SCHEMA_VERSION",
    "CompatibilityAssessment",
    "CompatibilityRecordError",
    "CompatibilityRegistry",
    "CompatibilityVerdict",
    "TestedCompatibilityRecord",
    "normalize_protocol_id",
]
