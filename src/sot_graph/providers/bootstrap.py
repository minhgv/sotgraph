"""Trusted engine bootstrap: fetch pinned artifacts, verify, stage, promote.

Master plan 2026-09-06 D1/D4. The ONLY sanctioned retrieval path for engine
binaries: sources and digests are pinned in ``engine_pins.json`` shipped inside
this package. Fetches happen at install/setup/explicit command time — never on
query — and an artifact whose bytes do not match the pinned sha256 is deleted
and refused before it can reach :class:`ArtifactStore`. No PATH discovery and
no unpinned URLs are accepted, with one narrow exception: an explicit
administrator ``source_override`` (local file or URL) whose bytes must still
match the pinned digest for the host platform.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore, host_platform

__all__ = ["BootstrapError", "default_store_root", "auto_bootstrap_allowed",
           "load_pins", "resolve_pin", "bootstrap_engine"]

_SIZE_SLACK_BYTES = 64 << 20  # tolerate rebuild variance; digest is the gate
_FETCH_CHUNK = 1 << 20
_OFF_VALUES = frozenset({"off", "0", "false", "no"})


class BootstrapError(RuntimeError):
    """Fail-closed bootstrap refusal; never remediated with engine-native hints."""


def default_store_root() -> Path:
    """User-level engine store outside every repository (master plan D3)."""
    return Path.home() / ".sotgraph" / "engine-store"


def auto_bootstrap_allowed() -> bool:
    return os.environ.get("SOT_ENGINE_BOOTSTRAP", "").strip().lower() not in _OFF_VALUES


def load_pins(pins_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    path = Path(pins_path) if pins_path else Path(__file__).with_name("engine_pins.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BootstrapError(f"cannot read engine pin manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 \
            or not isinstance(data.get("pins"), list):
        raise BootstrapError("engine pin manifest schema mismatch")
    for pin in data["pins"]:
        required = {"name", "platform", "engine_commit", "protocol",
                    "source", "sha256", "size_bytes"}
        if not isinstance(pin, dict) or not required.issubset(pin):
            raise BootstrapError("engine pin entry schema mismatch")
    return data


def resolve_pin(pins: dict[str, Any] | None = None,
                platform: str | None = None) -> dict[str, Any]:
    pins = pins or load_pins()
    platform = platform or host_platform()
    for pin in pins["pins"]:
        if pin["platform"] == platform:
            return pin
    available = ", ".join(sorted(p["platform"] for p in pins["pins"])) or "none"
    raise BootstrapError(
        f"no pinned engine artifact for platform {platform!r} (available: {available})")


def _source_token() -> str | None:
    for key in ("SOT_ENGINE_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    return None


def _as_local_source(source: str) -> Path | None:
    """Return a local path for path/file:// sources; None for remote URLs."""
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("", "file"):
        raw = urllib.parse.unquote(urllib.request.url2pathname(parsed.path or source))
        return Path(raw)
    return None


def _verify_local_digest(path: Path, expected: str) -> None:
    seen = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_FETCH_CHUNK), b""):
            seen.update(chunk)
    if seen.hexdigest() != expected:
        raise BootstrapError(
            f"source digest mismatch: expected {expected}, got {seen.hexdigest()}")


def _github_release_tag_api(url: str) -> str | None:
    """Map a browser download URL to the GitHub release-tag API endpoint."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 6 or parts[2] != "releases" or parts[3] != "download":
        return None
    owner, repo, tag = parts[0], parts[1], urllib.parse.quote(parts[4])
    return f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"


def _fetch_remote(url: str, expected_sha256: str, size_bytes: int,
                  tmp_dir: Path) -> Path:
    """Stream the pinned URL to a temp file, enforcing digest + size cap.

    Private GitHub releases cannot be fetched by sending a bearer token to the
    browser download URL; when a token is available and the pin points at a
    GitHub release asset, resolve the asset through the API
    (``Accept: application/octet-stream``) and stream the signed redirect.
    """
    headers = {"User-Agent": "sotgraph-bootstrap"}
    token = _source_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    fetch_url = url
    tag_api = _github_release_tag_api(url)
    if tag_api is not None and token:
        lookup_headers = dict(headers, Accept="application/vnd.github+json")
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(tag_api, headers=lookup_headers),
                    timeout=60) as response:
                release = json.load(response)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise BootstrapError(f"engine release lookup failed: {exc}") from exc
        filename = url.rsplit("/", 1)[-1]
        asset = next((a for a in release.get("assets", [])
                      if a.get("name") == filename), None)
        if asset is None:
            raise BootstrapError(
                f"pinned engine asset {filename!r} not found in release")
        fetch_url = asset["url"]
        headers["Accept"] = "application/octet-stream"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(tmp_dir, 0o700)  # ArtifactStore refuses group/other-writable temp dirs
    target = tmp_dir / f"bootstrap.{uuid.uuid4().hex}"
    cap = size_bytes + _SIZE_SLACK_BYTES
    try:
        with urllib.request.urlopen(
                urllib.request.Request(fetch_url, headers=headers),
                timeout=120) as response, open(target, "wb") as out:
            seen, total = hashlib.sha256(), 0
            while True:
                chunk = response.read(_FETCH_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > cap:
                    raise BootstrapError(
                        f"engine artifact exceeds pinned size cap ({total} > {cap} bytes)")
                out.write(chunk)
                seen.update(chunk)
        if seen.hexdigest() != expected_sha256:
            raise BootstrapError("downloaded engine artifact failed pinned sha256 check")
        return target
    except BootstrapError:
        target.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise BootstrapError(f"engine artifact fetch failed: {exc}") from exc


def _manifest_bytes(pin: dict[str, Any]) -> bytes:
    manifest = {
        "schema_version": 1,
        "name": pin["name"],
        "digest": pin["sha256"],
        "platform": pin["platform"],
        "protocol": pin["protocol"],
        "engine_commit": pin["engine_commit"],
    }
    return (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")


def bootstrap_engine(repo_path: str | os.PathLike[str],
                     store_root: str | os.PathLike[str] | None = None,
                     source_override: str | None = None,
                     pins_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Fetch (if needed), verify, stage and promote the pinned engine artifact.

    Idempotent: when the store already promotes the pinned digest the result
    is ``already`` and nothing is fetched. Every failure is fail-closed — a
    mismatched artifact never reaches the store.
    """
    pin = resolve_pin(pins=pins_path and load_pins(pins_path))
    store_root = Path(store_root) if store_root else default_store_root()
    store_root.mkdir(parents=True, exist_ok=True)
    os.chmod(store_root, 0o700)
    tmp_dir = store_root / "tmp"
    if tmp_dir.is_dir():  # self-heal leftover dirs from interrupted fetches
        os.chmod(tmp_dir, 0o700)
    store = ArtifactStore(store_root, repo_path=repo_path)

    existing = store.resolve(pin["name"])
    if existing is not None and existing.digest == pin["sha256"]:
        return {"schema_version": 1, "status": "already", "name": pin["name"],
                "sha256": pin["sha256"], "platform": pin["platform"],
                "engine_commit": pin["engine_commit"], "source": pin["source"],
                "store_root": str(store_root)}

    fetched: Path | None = None
    source = source_override or pin["source"]
    try:
        local = _as_local_source(source)
        if local is not None:
            if not local.is_file():
                raise BootstrapError(f"engine artifact source not found: {local}")
            _verify_local_digest(local, pin["sha256"])
        else:
            if not source.startswith("https://"):
                raise BootstrapError("engine artifact sources must be https:// or local")
            fetched = _fetch_remote(source, pin["sha256"], int(pin["size_bytes"]),
                                    store_root / "tmp")
            local = fetched
        descriptor = store.import_artifact(local, _manifest_bytes(pin))
        store.promote(pin["name"], descriptor.digest)
    finally:
        if fetched is not None:
            fetched.unlink(missing_ok=True)
    return {"schema_version": 1, "status": "promoted", "name": pin["name"],
            "sha256": pin["sha256"], "platform": pin["platform"],
            "engine_commit": pin["engine_commit"], "source": source,
            "store_root": str(store_root)}
