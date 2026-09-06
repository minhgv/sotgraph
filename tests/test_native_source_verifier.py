"""Scratch-only tests of the packaging source verifier."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_verifier", Path(__file__).resolve().parents[1] / "scripts/verify_native_source.py"
)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


@pytest.fixture
def packet(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "nested/data").write_bytes(b"intact source\n")
    (source / "run").write_bytes(b"#!/bin/sh\n")
    (source / "run").chmod(0o755)
    (source / "link").symlink_to("nested/data")
    (source / "dirlink").symlink_to("nested", target_is_directory=True)
    (source / "nested/back").symlink_to("../run")
    entries = []
    for path in sorted(source.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        mode = "120000" if path.is_symlink() else (
            "100755" if path.stat().st_mode & 0o111 else "100644"
        )
        entries.append({"path": path.relative_to(source).as_posix(), "mode": mode,
                        "git_blob": hashlib.sha1(
                            b"blob " + str(len(data)).encode() + b"\0" + data
                        ).hexdigest(), "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"pin": verifier.EXPECTED_PIN, "method": "synthetic fixture",
                "files": len(entries), "source_bytes": sum(e["bytes"] for e in entries),
                "entries": entries}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return source, path, manifest


def test_intact(packet):
    source, path, manifest = packet
    assert verifier.verify(source, path) == {
        "pin": verifier.EXPECTED_PIN, "entries": 5,
        "source_bytes": manifest["source_bytes"], "verified": True,
    }


@pytest.mark.parametrize("change", ["bytes", "mode", "missing", "extra", "fifo", "type"])
def test_tree_tamper(packet, change):
    source, path, _ = packet
    target = source / "nested/data"
    if change == "bytes":
        target.write_bytes(b"changed bytes\n")
    elif change == "mode":
        target.chmod(0o755)
    elif change == "missing":
        target.unlink()
    elif change == "extra":
        (source / "extra").write_text("extra")
    elif change == "fifo":
        os.mkfifo(source / "pipe")
    else:
        target.unlink()
        target.symlink_to("../run")
    with pytest.raises(ValueError):
        verifier.verify(source, path)


@pytest.mark.parametrize("target", ["../outside", "/tmp/outside", "chain", "link"])
def test_unsafe_links_even_when_manifest_matches(packet, target):
    source, path, manifest = packet
    link = source / "link"
    link.unlink()
    link.symlink_to(target)
    if target == "chain":
        (source / "chain").symlink_to("../outside")
    entry = next(e for e in manifest["entries"] if e["path"] == "link")
    entry.update(bytes=len(target), sha256=hashlib.sha256(target.encode()).hexdigest(),
                 git_blob=hashlib.sha1(
                     b"blob " + str(len(target)).encode() + b"\0" + target.encode()
                 ).hexdigest())
    manifest["source_bytes"] = sum(e["bytes"] for e in manifest["entries"])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unsafe source symlink"):
        verifier.verify(source, path)


@pytest.mark.parametrize("change", [
    "pin", "root", "entries", "duplicate", "traversal", "absolute", "mode",
    "hash", "blob", "size", "boolean", "files", "total", "field", "entry",
])
def test_bad_manifest(packet, change):
    source, path, manifest = packet
    entry = manifest["entries"][0]
    if change == "pin":
        manifest["pin"] = "0" * 40
    elif change == "root":
        manifest = []
    elif change == "entries":
        manifest["entries"] = {}
    elif change == "duplicate":
        manifest["entries"].append(dict(entry))
    elif change in {"traversal", "absolute"}:
        entry["path"] = "../outside" if change == "traversal" else "/outside"
    elif change == "mode":
        entry["mode"] = "040000"
    elif change in {"hash", "blob"}:
        entry["sha256" if change == "hash" else "git_blob"] = "not-a-hash"
    elif change in {"size", "boolean"}:
        entry["bytes"] = -1 if change == "size" else True
    elif change in {"files", "total"}:
        manifest["files" if change == "files" else "source_bytes"] += 1
    elif change == "field":
        del entry["mode"]
    else:
        manifest["entries"][0] = None
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verifier.verify(source, path)


@pytest.mark.parametrize("text", ['{"pin":', '{"pin":1,"pin":2}'])
def test_invalid_json(packet, text):
    source, path, _ = packet
    path.write_text(text)
    with pytest.raises(ValueError):
        verifier.verify(source, path)


@pytest.mark.parametrize("name", ["nested/data", "run", "link", "dirlink"])
def test_wrong_well_formed_git_blob(packet, name):
    source, path, manifest = packet
    entry = next(e for e in manifest["entries"] if e["path"] == name)
    entry["git_blob"] = "0" * 40
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Source Git blob mismatch"):
        verifier.verify(source, path)


def test_cli_interface(packet, monkeypatch, capsys):
    source, path, _ = packet
    monkeypatch.setattr(verifier, "SOURCE", source)
    monkeypatch.setattr(verifier, "MANIFEST", path)
    verifier.main()
    assert json.loads(capsys.readouterr().out)["verified"] is True
    (source / "run").unlink()
    with pytest.raises(SystemExit):
        verifier.main()
