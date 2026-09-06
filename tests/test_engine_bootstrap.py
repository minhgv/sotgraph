"""Trusted engine bootstrap: pinned fetch, verify, stage, promote (no network)."""
import hashlib
import json
from pathlib import Path

import pytest

from sot_graph.providers import bootstrap as bp
from sot_graph.providers.artifacts import (
    ARTIFACT_PROTOCOL_VERSION,
    ArtifactManifest,
    ArtifactRejected,
    ArtifactStore,
    host_platform,
)


@pytest.fixture
def fake_engine(tmp_path):
    payload = b"#!/bin/sh\necho engine-stub\n" * 64
    path = tmp_path / "engine-bin"
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest(), len(payload)


def _write_pins(tmp_path, binary_path, digest, size, platform=None):
    pins = {
        "schema_version": 1,
        "pins": [{
            "name": "codebase-memory",
            "platform": platform or host_platform(),
            "engine_commit": "46ae198fc11cda80e817acbc5f5908d7c2de7032",
            "protocol": ARTIFACT_PROTOCOL_VERSION,
            "source": "https://example.invalid/engine-bin",
            "sha256": digest,
            "size_bytes": size,
        }],
    }
    pins_path = tmp_path / "engine_pins.json"
    pins_path.write_text(json.dumps(pins), encoding="utf-8")
    return pins_path


def test_bootstrap_local_source_promotes(tmp_path, fake_engine):
    binary, digest, size = fake_engine
    repo = tmp_path / "repo"
    repo.mkdir()
    pins_path = _write_pins(tmp_path, binary, digest, size)
    receipt = bp.bootstrap_engine(
        repo_path=repo, store_root=tmp_path / "store",
        source_override=str(binary), pins_path=pins_path)
    assert receipt["status"] == "promoted"
    assert receipt["sha256"] == digest
    store = ArtifactStore(tmp_path / "store", repo_path=repo)
    descriptor = store.resolve("codebase-memory")
    assert descriptor is not None and descriptor.digest == digest
    assert Path(descriptor.executable).is_file()


def test_bootstrap_idempotent_already(tmp_path, fake_engine):
    binary, digest, size = fake_engine
    repo = tmp_path / "repo"
    repo.mkdir()
    pins_path = _write_pins(tmp_path, binary, digest, size)
    first = bp.bootstrap_engine(repo_path=repo, store_root=tmp_path / "store",
                                source_override=str(binary), pins_path=pins_path)
    second = bp.bootstrap_engine(repo_path=repo, store_root=tmp_path / "store",
                                 pins_path=pins_path)  # no override; already promoted
    assert first["status"] == "promoted" and second["status"] == "already"


def test_bootstrap_digest_mismatch_fail_closed(tmp_path, fake_engine):
    binary, digest, size = fake_engine
    other = tmp_path / "other-bin"
    other.write_bytes(b"tampered")
    repo = tmp_path / "repo"
    repo.mkdir()
    pins_path = _write_pins(tmp_path, binary, digest, size)
    with pytest.raises(bp.BootstrapError, match="digest mismatch"):
        bp.bootstrap_engine(repo_path=repo, store_root=tmp_path / "store",
                            source_override=str(other), pins_path=pins_path)
    store = ArtifactStore(tmp_path / "store", repo_path=repo)
    assert store.resolve("codebase-memory") is None


def test_resolve_pin_rejects_foreign_platform(tmp_path):
    pins = {"schema_version": 1, "pins": [{
        "name": "codebase-memory", "platform": "not-a-platform",
        "engine_commit": "46ae198fc11cda80e817acbc5f5908d7c2de7032",
        "protocol": "artifacts-v1", "source": "https://example.invalid/x",
        "sha256": "0" * 64, "size_bytes": 1}]}
    with pytest.raises(bp.BootstrapError, match="no pinned engine artifact"):
        bp.resolve_pin(pins, platform=host_platform())


def test_fetch_remote_file_url_verifies_digest(tmp_path, fake_engine):
    binary, digest, size = fake_engine
    from urllib.parse import quote
    url = "file://" + quote(str(binary))
    target = bp._fetch_remote(url, digest, size, tmp_path / "tmp")
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    target.unlink()  # caller (bootstrap_engine) owns cleanup of successful fetches
    with pytest.raises(bp.BootstrapError, match="sha256"):
        bp._fetch_remote(url, "f" * 64, size, tmp_path / "tmp")
    assert not list((tmp_path / "tmp").glob("bootstrap.*")), "failed fetch must clean up"


def test_manifest_bytes_match_artifact_schema(tmp_path, fake_engine):
    binary, digest, size = fake_engine
    pins_path = _write_pins(tmp_path, binary, digest, size)
    pin = bp.resolve_pin(bp.load_pins(pins_path))
    manifest = ArtifactManifest.parse(bp._manifest_bytes(pin))
    assert manifest.name == "codebase-memory"
    assert manifest.digest == digest
    assert manifest.platform == host_platform()
    with pytest.raises(ArtifactRejected):
        ArtifactManifest.parse(bp._manifest_bytes(dict(pin, platform="other-os")))


def test_auto_bootstrap_policy_env(monkeypatch):
    monkeypatch.setenv("SOT_ENGINE_BOOTSTRAP", "off")
    assert bp.auto_bootstrap_allowed() is False
    monkeypatch.setenv("SOT_ENGINE_BOOTSTRAP", "1")
    assert bp.auto_bootstrap_allowed() is True
    monkeypatch.delenv("SOT_ENGINE_BOOTSTRAP", raising=False)
    assert bp.auto_bootstrap_allowed() is True


def test_load_pins_rejects_malformed(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 2, "pins": []}')
    with pytest.raises(bp.BootstrapError):
        bp.load_pins(bad)


def test_github_url_maps_to_tag_api():
    api = bp._github_release_tag_api(
        "https://github.com/minhgv/sotgraph-cbm/releases/download/engine-v1.0/art.bin")
    assert api == ("https://api.github.com/repos/minhgv/sotgraph-cbm/"
                   "releases/tags/engine-v1.0")
    assert bp._github_release_tag_api("https://example.com/x") is None
    assert bp._github_release_tag_api("https://github.com/owner/repo/blob/main/x") is None


def test_shipped_pins_manifest_is_valid():
    data = bp.load_pins()
    assert data["schema_version"] == 1 and data["pins"], "package must ship usable pins"
    for pin in data["pins"]:
        ArtifactManifest.parse(bp._manifest_bytes(pin))  # every shipped pin is installable
