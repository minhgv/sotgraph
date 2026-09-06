"""Verify trusted manifest bytes/modes, not independent upstream authenticity."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "engines/codebase-memory-mcp"
MANIFEST = ROOT / "plan/python-c-monorepo/evidence/source-import-manifest.json"
EXPECTED_PIN = "46ae198fc11cda80e817acbc5f5908d7c2de7032"


def _object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest key: {key}")
        result[key] = value
    return result


def verify(source: Path, manifest_path: Path) -> dict:
    """Check a quiescent source tree against a version-controlled manifest."""
    manifest = json.loads(manifest_path.read_text(), object_pairs_hook=_object)
    if not isinstance(manifest, dict) or set(manifest) != {
        "pin", "method", "files", "source_bytes", "entries"
    }:
        raise ValueError("Invalid manifest schema")
    if manifest["pin"] != EXPECTED_PIN:
        raise ValueError("Unexpected release pin")
    if (not isinstance(manifest["method"], str) or not manifest["method"]
            or not isinstance(manifest["entries"], list)):
        raise ValueError("Invalid manifest metadata")
    expected = {}
    for entry in manifest["entries"]:
        if not isinstance(entry, dict) or set(entry) != {
            "path", "mode", "git_blob", "bytes", "sha256"
        }:
            raise ValueError("Invalid manifest entry")
        name = entry["path"]
        if (not isinstance(name, str) or not name or "\x00" in name
                or "\\" in name or PurePosixPath(name).is_absolute()
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or name in expected):
            raise ValueError("Invalid or duplicate manifest path")
        if (entry["mode"] not in ("100644", "100755", "120000")
                or type(entry["bytes"]) is not int or entry["bytes"] < 0
                or not isinstance(entry["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or not isinstance(entry["git_blob"], str)
                or not re.fullmatch(r"[0-9a-f]{40}", entry["git_blob"])):
            raise ValueError(f"Invalid manifest entry metadata: {name}")
        expected[name] = entry
    for field, value in (("files", len(expected)),
                         ("source_bytes", sum(e["bytes"] for e in expected.values()))):
        if type(manifest[field]) is not int or manifest[field] != value:
            raise ValueError(f"Invalid manifest total: {field}")
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Source root must be a real directory")
    root = source.resolve()
    actual = set()
    for directory, dirs, files in os.walk(source, followlinks=False):
        # Only the regular root submodule gitfile is checkout metadata.
        # Nested .git paths and directories remain subject to inventory checks.
        if Path(directory) == source and ".git" in files:
            gitfile = source / ".git"
            if (gitfile.is_symlink() or not gitfile.is_file()
                    or not gitfile.read_text().startswith("gitdir: ")):
                raise ValueError("Invalid submodule gitfile")
            files = [name for name in files if name != ".git"]
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                try:
                    try:
                        resolved = path.resolve(strict=True)
                    except FileNotFoundError:
                        resolved = path.resolve()
                    resolved.relative_to(root)
                except (ValueError, RuntimeError, OSError) as exc:
                    raise ValueError(f"Unsafe source symlink: {path}") from exc
            elif stat.S_ISDIR(mode):
                continue
            elif not stat.S_ISREG(mode):
                raise ValueError(f"Unexpected source file type: {path}")
            actual.add(path.relative_to(source).as_posix())
    if actual != expected.keys():
        raise ValueError(f"Source inventory mismatch: {sorted(actual ^ expected.keys())[:10]}")
    for name, entry in expected.items():
        path = source / name
        digest = hashlib.sha256()
        if entry["mode"] == "120000":
            if not path.is_symlink():
                raise ValueError(f"Expected symlink: {name}")
            data = os.fsencode(os.readlink(path))
            digest.update(data)
            size = len(data)
            blob = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0")
            blob.update(data)
        else:
            if path.is_symlink():
                raise ValueError(f"Unexpected symlink: {name}")
            size = path.stat().st_size
            blob = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0")
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    blob.update(block)
            executable = bool(path.stat().st_mode & 0o111)
            if executable != (entry["mode"] == "100755"):
                raise ValueError(f"Source mode mismatch: {name}")
        if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
            raise ValueError(f"Source content mismatch: {name}")
        if blob.hexdigest() != entry["git_blob"]:
            raise ValueError(f"Source Git blob mismatch: {name}")
    return {"pin": manifest["pin"], "entries": len(expected),
            "source_bytes": manifest["source_bytes"], "verified": True}


def main() -> None:
    try:
        result = verify(SOURCE, MANIFEST)
    except (ValueError, OSError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result))


if __name__ == "__main__":
    main()
