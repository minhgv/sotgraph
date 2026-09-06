"""Legacy ``sot-graph`` naming migration helpers (plan P1.4).

SUR-08: user-owned configuration is never damaged. A legacy entry, file, or
directory is only removed when it is provably ours (it launches a sotgraph
server, or it is byte/marker-identical to what this package writes); anything
ambiguous is preserved untouched for the operator to inspect.
"""
from __future__ import annotations

import shutil
from pathlib import Path

SERVER_KEY = "sotgraph"
LEGACY_SERVER_KEY = "sot-graph"
SKILL_DIR_NAME = "sotgraph"
LEGACY_SKILL_DIR_NAME = "sot-graph"


def is_sotgraph_server_entry(entry) -> bool:
    """True only when an MCP server entry provably launches a sotgraph server."""
    if not isinstance(entry, dict):
        return False
    candidates = []
    command = entry.get("command")
    if isinstance(command, str):
        candidates.append(command)
    elif isinstance(command, list):
        candidates.extend(str(part) for part in command)
    args = entry.get("args")
    if isinstance(args, list):
        candidates.extend(str(part) for part in args)
    for candidate in candidates:
        if "sot_graph" in candidate or "sotgraph" in Path(candidate).name:
            return True
    return False


def assign_server_entry(servers: dict, entry: dict) -> None:
    """Set our server entry; drop the legacy key only when it is ours.

    A legacy ``sot-graph`` entry that cannot be identified as ours is never
    touched. Dropping a provably-ours legacy entry prevents double MCP
    registration after the key rename.
    """
    legacy_is_ours = is_sotgraph_server_entry(servers.get(LEGACY_SERVER_KEY))
    servers[SERVER_KEY] = entry
    if legacy_is_ours:
        servers.pop(LEGACY_SERVER_KEY, None)


def _skill_dir_is_ours(skill_dir: Path) -> bool:
    """A skill dir is ours when its only file is a SKILL.md naming our CLI."""
    try:
        entries = sorted(entry.name for entry in skill_dir.iterdir())
    except OSError:
        return False
    if entries != ["SKILL.md"]:
        return False
    try:
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "sotgraph" in content


def write_skill_dir(skills_dir: Path, content: str) -> Path:
    """Write the sotgraph skill and migrate a provably-ours legacy skill dir.

    The new dir is always written fresh from the template. A legacy
    ``sot-graph`` sibling is removed only when it contains exactly our
    SKILL.md; any extra user file inside keeps the whole dir intact.
    """
    new_dir = skills_dir / SKILL_DIR_NAME
    new_dir.mkdir(parents=True, exist_ok=True)
    skill_file = new_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    legacy_dir = skills_dir / LEGACY_SKILL_DIR_NAME
    if legacy_dir.is_dir() and _skill_dir_is_ours(legacy_dir):
        shutil.rmtree(legacy_dir, ignore_errors=True)
    return skill_file


def remove_legacy_file(path: Path, expected: bytes) -> bool:
    """Delete a legacy file only when byte-identical to the shipped template."""
    try:
        if path.read_bytes() != expected:
            return False
    except OSError:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def remove_legacy_dir(path: Path, expected: dict[str, bytes]) -> bool:
    """Delete a template-only legacy dir; any user addition keeps it intact."""
    try:
        entries = sorted(entry.name for entry in path.iterdir())
    except OSError:
        return False
    if entries != sorted(expected):
        return False
    if any((path / name).read_bytes() != data for name, data in expected.items()):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


__all__ = [
    "SERVER_KEY",
    "LEGACY_SERVER_KEY",
    "SKILL_DIR_NAME",
    "LEGACY_SKILL_DIR_NAME",
    "is_sotgraph_server_entry",
    "assign_server_entry",
    "write_skill_dir",
    "remove_legacy_file",
    "remove_legacy_dir",
]
