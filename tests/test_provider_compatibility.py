"""Tests for the per-artifact provider compatibility contract (P1).

Covers: exact-artifact success, same-version-different-digest rejection,
unsupported operation, fixture-digest mismatch, missing identity, invalid
entries, unknown fields/version handling, and serialization backward
compatibility of the extended ProviderIdentity.
"""

import threading

import pytest

from sot_graph.provider_contract import (
    Capability,
    EvidenceEnvelope,
    IntegrationMode,
    ProviderIdentity,
    Subject,
    VerificationResult,
    normalize_sha256_digest,
)
from sot_graph.providers.compatibility import (
    CompatibilityRecordError,
    CompatibilityRegistry,
    CompatibilityVerdict,
    TestedCompatibilityRecord,
    normalize_protocol_id,
)

ARTIFACT_A = "11" * 32
ARTIFACT_B = "22" * 32
FIXTURE_V1 = "aa" * 32
FIXTURE_V2 = "bb" * 32
PROTOCOL_V1 = "sot-native-envelope/1"


def _record(**overrides):
    kwargs = dict(
        provider_name="gitnexus",
        operation="impact",
        artifact_sha256=ARTIFACT_A,
        fixture_digest=FIXTURE_V1,
        protocol_compatibility_id=PROTOCOL_V1,
        version="1.2.3",
    )
    kwargs.update(overrides)
    return TestedCompatibilityRecord(**kwargs)


def _identity(**overrides):
    kwargs = dict(
        name="gitnexus",
        version="1.2.3",
        mode=IntegrationMode.FEDERATED_CLI,
        capability=Capability.IMPACT,
        artifact_sha256=ARTIFACT_A,
        protocol_compatibility_id=PROTOCOL_V1,
    )
    kwargs.update(overrides)
    return ProviderIdentity(**kwargs)


def _registry():
    registry = CompatibilityRegistry()
    registry.register(_record())
    return registry


class TestExactArtifactCompatibility:
    def test_exact_digest_fixture_and_protocol_is_compatible(self):
        assessment = _registry().assess(
            _identity(), "impact", fixture_digest=FIXTURE_V1, protocol_compatibility_id=PROTOCOL_V1
        )
        assert assessment.verdict is CompatibilityVerdict.COMPATIBLE
        assert assessment.matched_record is not None
        assert assessment.matched_record.artifact_sha256 == ARTIFACT_A
        assert assessment.reasons  # every verdict carries explicit reasons

    def test_sha256_prefixed_digests_and_protocol_case_normalize(self):
        registry = CompatibilityRegistry()
        registry.register(
            _record(
                artifact_sha256=f"sha256:{ARTIFACT_A.upper()}",
                protocol_compatibility_id="  SOT-Native-Envelope/1  ",
            )
        )
        assessment = registry.assess(
            _identity(),
            Capability.IMPACT,
            fixture_digest=f"sha256:{FIXTURE_V1}",
            protocol_compatibility_id="SOT-NATIVE-ENVELOPE/1",
        )
        assert assessment.verdict is CompatibilityVerdict.COMPATIBLE

    def test_version_string_mismatch_with_digest_exact_is_still_compatible(self):
        """Digest is identity; a cosmetic version drift is a note, not a veto."""
        assessment = _registry().assess(
            _identity(version="1.2.3-rebuilt"),
            "impact",
            fixture_digest=FIXTURE_V1,
            protocol_compatibility_id=PROTOCOL_V1,
        )
        assert assessment.verdict is CompatibilityVerdict.COMPATIBLE
        assert any("version" in r for r in assessment.reasons)

    def test_multiple_fixture_suites_for_one_artifact(self):
        registry = _registry()
        registry.register(_record(fixture_digest=FIXTURE_V2))
        for fx in (FIXTURE_V1, FIXTURE_V2):
            assessment = registry.assess(
                _identity(), "impact", fixture_digest=fx, protocol_compatibility_id=PROTOCOL_V1
            )
            assert assessment.verdict is CompatibilityVerdict.COMPATIBLE


class TestVersionMasqueradeRejected:
    def test_same_version_different_digest_is_incompatible(self):
        assessment = _registry().assess(
            _identity(artifact_sha256=ARTIFACT_B),
            "impact",
            fixture_digest=FIXTURE_V1,
            protocol_compatibility_id=PROTOCOL_V1,
        )
        assert assessment.verdict is CompatibilityVerdict.INCOMPATIBLE
        assert any(ARTIFACT_B in r for r in assessment.reasons)
        assert assessment.matched_record is None

    def test_same_version_unknown_record_version_does_not_bind(self):
        """A record without a usable version string cannot drive the masquerade rule."""
        registry = CompatibilityRegistry()
        registry.register(_record(version="unknown"))
        assessment = registry.assess(
            _identity(artifact_sha256=ARTIFACT_B),
            "impact",
            fixture_digest=FIXTURE_V1,
            protocol_compatibility_id=PROTOCOL_V1,
        )
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN


class TestExplicitUnknownAndUnsupported:
    def test_unregistered_operation_is_explicitly_unsupported(self):
        assessment = _registry().assess(
            _identity(), "trace", fixture_digest=FIXTURE_V1, protocol_compatibility_id=PROTOCOL_V1
        )
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN
        assert any("trace" in r for r in assessment.reasons)

    def test_fixture_digest_mismatch_is_unknown_with_reason(self):
        assessment = _registry().assess(
            _identity(), "impact", fixture_digest=FIXTURE_V2, protocol_compatibility_id=PROTOCOL_V1
        )
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN
        assert any(FIXTURE_V2 in r for r in assessment.reasons)

    def test_missing_fixture_digest_is_unknown_not_compatible(self):
        assessment = _registry().assess(_identity(), "impact", protocol_compatibility_id=PROTOCOL_V1)
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN

    def test_protocol_id_mismatch_is_incompatible(self):
        assessment = _registry().assess(
            _identity(), "impact", fixture_digest=FIXTURE_V1, protocol_compatibility_id="sot-native-envelope/2"
        )
        assert assessment.verdict is CompatibilityVerdict.INCOMPATIBLE

    def test_missing_protocol_id_is_unknown_not_compatible(self):
        assessment = _registry().assess(_identity(), "impact", fixture_digest=FIXTURE_V1)
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN


class TestMissingOrDegradedIdentity:
    def test_none_identity_is_unknown_legacy_path(self):
        assessment = _registry().assess(None, "impact", fixture_digest=FIXTURE_V1)
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN
        assert assessment.matched_record is None
        assert any("None" in r or "legacy" in r for r in assessment.reasons)

    def test_identity_without_artifact_digest_is_unknown(self):
        assessment = _registry().assess(
            _identity(artifact_sha256=None),
            "impact",
            fixture_digest=FIXTURE_V1,
            protocol_compatibility_id=PROTOCOL_V1,
        )
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN
        assert any("artifact_sha256" in r for r in assessment.reasons)

    def test_empty_registry_is_unknown_everywhere(self):
        assessment = CompatibilityRegistry().assess(
            _identity(), "impact", fixture_digest=FIXTURE_V1, protocol_compatibility_id=PROTOCOL_V1
        )
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN


class TestValidationBounded:
    def test_malformed_record_digest_rejected(self):
        with pytest.raises(CompatibilityRecordError):
            _record(artifact_sha256="deadbeef")

    def test_malformed_record_fixture_digest_rejected(self):
        with pytest.raises(CompatibilityRecordError):
            _record(fixture_digest="zz" * 32)

    def test_empty_provider_or_operation_rejected(self):
        with pytest.raises(CompatibilityRecordError):
            _record(provider_name="  ")
        with pytest.raises(CompatibilityRecordError):
            _record(operation="")

    def test_non_record_rejected_at_register(self):
        with pytest.raises(CompatibilityRecordError):
            CompatibilityRegistry().register({"provider_name": "gitnexus"})

    def test_conflicting_duplicate_key_rejected(self):
        registry = _registry()
        with pytest.raises(CompatibilityRecordError, match="conflicting"):
            registry.register(_record(tested_at="2026-09-05"))

    def test_identical_duplicate_registration_is_idempotent(self):
        registry = _registry()
        registry.register(_record())
        assert len(registry) == 1

    def test_unknown_dict_field_rejected(self):
        with pytest.raises(CompatibilityRecordError, match="unknown record field"):
            TestedCompatibilityRecord.from_dict({**_record().to_dict(), "trust_me": True})

    def test_missing_dict_field_rejected(self):
        payload = _record().to_dict()
        del payload["artifact_sha256"]
        with pytest.raises(CompatibilityRecordError, match="missing required field"):
            TestedCompatibilityRecord.from_dict(payload)

    def test_from_dict_round_trip(self):
        assert TestedCompatibilityRecord.from_dict(_record().to_dict()) == _record()

    def test_malformed_assessment_fixture_digest_rejected(self):
        with pytest.raises(CompatibilityRecordError):
            _registry().assess(_identity(), "impact", fixture_digest="not-a-digest")

    def test_malformed_identity_artifact_digest_rejected(self):
        with pytest.raises(CompatibilityRecordError):
            _registry().assess(_identity(artifact_sha256="short"), "impact")

    def test_empty_operation_rejected(self):
        with pytest.raises(CompatibilityRecordError):
            _registry().assess(_identity(), "   ")

    def test_normalize_protocol_id_requires_non_empty(self):
        assert normalize_protocol_id("  SOT/1 ") == "sot/1"
        with pytest.raises(CompatibilityRecordError):
            normalize_protocol_id("   ")

    def test_normalize_sha256_digest_helper(self):
        assert normalize_sha256_digest(f"sha256:{'AA' * 32}") == "aa" * 32
        with pytest.raises(ValueError):
            normalize_sha256_digest("abc")


class TestSerializationBackwardCompatible:
    @staticmethod
    def _envelope(provider):
        from sot_graph.provider_contract import (
            Assertion,
            SnapshotBinding,
            Subject,
            VerificationResult,
        )

        return EvidenceEnvelope(
            provider=provider,
            snapshot=SnapshotBinding("/repo", "abc123", "sha256:ff00", "sha256:aa11", True, "snap_1"),
            subject=Subject("function", "f", "src/app.py", 1, 2, "sha256:bb22"),
            assertion=Assertion("CALLS", "t", 0.9),
            verification=VerificationResult("SUPPORTED", True, True),
        )

    def test_provider_identity_default_dict_shape_unchanged(self):
        identity = ProviderIdentity("gitnexus", "1.2.3", IntegrationMode.FEDERATED_CLI, Capability.IMPACT)
        assert identity.artifact_sha256 is None
        assert identity.engine_commit is None
        assert identity.protocol_compatibility_id is None

    def test_envelope_to_dict_default_shape_unchanged(self):
        identity = ProviderIdentity("gitnexus", "1.2.3", IntegrationMode.FEDERATED_CLI, Capability.IMPACT)
        provider_block = self._envelope(identity).to_dict()["provider"]
        assert set(provider_block) == {"name", "version", "mode", "capability"}

    def test_envelope_to_dict_serializes_new_fields_only_when_set(self):
        provider_block = self._envelope(_identity(engine_commit="deadbeefcafe")).to_dict()["provider"]
        assert set(provider_block) == {
            "name",
            "version",
            "mode",
            "capability",
            "engine_commit",
            "artifact_sha256",
            "protocol_compatibility_id",
        }

    def test_envelope_validate_flags_malformed_artifact_digest(self):
        problems = self._envelope(_identity(artifact_sha256="bogus")).validate()
        assert any("artifact_sha256" in p for p in problems)

    def test_record_and_assessment_dicts_round_trip(self):
        payload = _record().to_dict()
        assert payload["artifact_sha256"] == ARTIFACT_A
        assert TestedCompatibilityRecord.from_dict(payload) == _record()
        assessment = _registry().assess(
            _identity(), "impact", fixture_digest=FIXTURE_V1, protocol_compatibility_id=PROTOCOL_V1
        )
        as_dict = assessment.to_dict()
        assert as_dict["verdict"] == "compatible"
        assert as_dict["matched_record"]["operation"] == "impact"


class TestThreadSafety:
    def test_concurrent_register_and_assess(self):
        registry = CompatibilityRegistry()
        records = [
            _record(
                operation=f"op{i}",
                artifact_sha256=f"{i:064x}",
                fixture_digest=f"{i + 16:064x}",
            )
            for i in range(8)
        ]
        # One wait per worker thread (2 register + 2 assess): the barrier is
        # the simultaneous-start rendezvous; the event additionally orders
        # registration-completion before any assessment (no race on lookup).
        barrier = threading.Barrier(4)
        registered = threading.Event()
        errors: list[BaseException] = []

        def register_all():
            try:
                barrier.wait(timeout=10)
                for rec in records:
                    registry.register(rec)
                registered.set()
            except BaseException as exc:  # surfaced on the main thread below
                errors.append(exc)

        def assess_all():
            try:
                barrier.wait(timeout=10)
                if not registered.wait(timeout=10):
                    raise RuntimeError("registration never completed")
                for rec in records:
                    assessment = registry.assess(
                        _identity(
                            artifact_sha256=rec.artifact_sha256,
                            protocol_compatibility_id=PROTOCOL_V1,
                        ),
                        rec.operation,
                        fixture_digest=rec.fixture_digest,
                        protocol_compatibility_id=PROTOCOL_V1,
                    )
                    assert assessment.verdict is CompatibilityVerdict.COMPATIBLE
            except BaseException as exc:  # surfaced on the main thread below
                errors.append(exc)

        threads = [threading.Thread(target=register_all) for _ in range(2)]
        threads += [threading.Thread(target=assess_all) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not any(t.is_alive() for t in threads), "worker thread hung; barrier/wait budget broken"
        assert errors == [], f"worker threads raised: {errors!r}"
        assert len(registry) == len(records)


class TestNonStringIdentityFields:
    def test_non_string_version_is_unbindable_not_crash(self):
        """Non-str version never binds the masquerade rule (no AttributeError)."""
        assessment = _registry().assess(
            _identity(version=123, artifact_sha256=ARTIFACT_B),
            "impact",
            fixture_digest=FIXTURE_V1,
            protocol_compatibility_id=PROTOCOL_V1,
        )
        assert assessment.verdict is CompatibilityVerdict.UNKNOWN

    def test_non_string_version_still_assesses_exact_digest(self):
        assessment = _registry().assess(
            _identity(version=123),
            "impact",
            fixture_digest=FIXTURE_V1,
            protocol_compatibility_id=PROTOCOL_V1,
        )
        assert assessment.verdict is CompatibilityVerdict.COMPATIBLE

    def test_non_string_engine_commit_does_not_crash_note(self):
        assessment = _registry().assess(
            _identity(engine_commit=7),
            "impact",
            fixture_digest=FIXTURE_V1,
            protocol_compatibility_id=PROTOCOL_V1,
        )
        assert assessment.verdict is CompatibilityVerdict.COMPATIBLE

    def test_non_string_name_is_typed_controlled_error(self):
        with pytest.raises(CompatibilityRecordError, match="identity.name"):
            _registry().assess(
                _identity(name=123), "impact", fixture_digest=FIXTURE_V1, protocol_compatibility_id=PROTOCOL_V1
            )


class TestRecordSchemaVersion:
    def test_to_dict_emits_schema_version_one(self):
        assert _record().to_dict()["schema_version"] == 1

    def test_from_dict_rejects_unsupported_schema(self):
        payload = {**_record().to_dict(), "schema_version": 2}
        with pytest.raises(CompatibilityRecordError, match="schema_version"):
            TestedCompatibilityRecord.from_dict(payload)

    def test_from_dict_rejects_bool_and_numeric_string_schema(self):
        for bad in (True, "1"):
            payload = {**_record().to_dict(), "schema_version": bad}
            with pytest.raises(CompatibilityRecordError, match="schema_version"):
                TestedCompatibilityRecord.from_dict(payload)

    def test_from_dict_omitted_schema_is_explicit_legacy_v1_policy(self):
        payload = _record().to_dict()
        del payload["schema_version"]
        record = TestedCompatibilityRecord.from_dict(payload)
        assert record.schema_version == 1
        with pytest.raises(CompatibilityRecordError, match="missing required"):
            TestedCompatibilityRecord.from_dict({"provider_name": "x"})


class TestEnvelopeValidateGuards:
    @staticmethod
    def _envelope(**overrides):
        from sot_graph.provider_contract import (
            Assertion,
            SnapshotBinding,
            Subject,
            VerificationResult,
        )

        kwargs = dict(
            provider=ProviderIdentity("gn", "1.2.3", IntegrationMode.FEDERATED_CLI, Capability.IMPACT),
            snapshot=SnapshotBinding("/repo", "abc123", "sha256:ff00", "sha256:aa11", True, "snap_1"),
            subject=Subject("function", "f", "src/app.py", 1, 2, "sha256:bb22"),
            assertion=Assertion("CALLS", "t", 0.9),
            verification=VerificationResult("SUPPORTED", True, True),
        )
        kwargs.update(overrides)
        return EvidenceEnvelope(**kwargs)

    def test_status_outside_vocabulary_flagged(self):
        envelope = self._envelope(verification=VerificationResult("MADE_UP", True, True))
        assert any("vocabulary" in p for p in envelope.validate())

    def test_non_string_subject_path_flagged_without_crash(self):
        envelope = self._envelope(subject=Subject("function", "f", 123, 1, 2, None))
        assert any("non-empty string" in p for p in envelope.validate())

    def test_empty_subject_path_flagged(self):
        envelope = self._envelope(subject=Subject("function", "f", "", 1, 2, None))
        assert any("non-empty string" in p for p in envelope.validate())
