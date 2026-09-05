"""SG-204 holdout oracle — the INDEPENDENT evaluator.

Contract: stdlib only. This module must NEVER import ``sot_graph`` —
its entire value is being a second opinion computed by a different
code path (CPython's own ``ast``) than the extractor under test. A
unit test enforces the import boundary.

Everything is deterministic: sampling is seeded per repo so two runs
on the same pinned commit produce identical oracles.
"""

from __future__ import annotations

import ast
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Holdout universes exclude only clearly-non-code trees. Note: NO
# "benchmarks/" prefix — holdout repos can ship real code under a
# benchmarks/ subpackage (jsonschema does) and the engine indexes it.
DEFAULT_EXCLUDE_PREFIXES = (
    "docs/",
    ".github/",
    "examples/",
)
DEFAULT_EXCLUDE_NAMES = {"setup.py", "conf.py", "conftest.py"}

_TOP_LEVEL_DEF = re.compile(
    r"^(?:async\s+)?def\s+([A-Za-z_]\w*)|^class\s+([A-Za-z_]\w*)", re.M
)
_TEST_NAME = re.compile(r"^test_|_test\.py$|^test\.py$")


@dataclass
class OracleConfig:
    exclude_prefixes: Tuple[str, ...] = DEFAULT_EXCLUDE_PREFIXES
    exclude_names: Set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_NAMES))


@dataclass
class Definition:
    path: str  # repo-relative POSIX
    name: str
    kind: str  # "function" | "class"
    line: int  # 1-based def/class statement line
    # True for symbols declared inside an ``if TYPE_CHECKING:`` guard:
    # they are part of the DECLARATION-PRESENCE universe (the engine must
    # index and expose them for symbol lookup) but stay OUT of the
    # runtime-impact universe (no runtime call edges involve them).
    type_only: bool = False


@dataclass
class CallEdge:
    caller_path: str
    caller_name: str
    callee_name: str
    callee_path: str


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def iter_python_files(root: Path, config: OracleConfig) -> List[str]:
    """Repo-relative .py paths after exclusions (deterministic order)."""
    out: List[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = _rel(path, root)
        parts = Path(rel).parts
        if any(
            rel.startswith(p) or (p.rstrip("/") + "/") in rel
            for p in config.exclude_prefixes
        ):
            continue
        if Path(rel).name in config.exclude_names:
            continue
        if any(
            seg
            in (".venv", "venv", "node_modules", "__pycache__", "site-packages", ".tox")
            for seg in parts
        ):
            continue
        out.append(rel)
    return out


def _is_overload(node: ast.AST) -> bool:
    """``@overload`` / ``@t.overload`` stubs — typing duplicates of the
    real implementation, which the engine records under the same name."""
    for dec in getattr(node, "decorator_list", []):
        if isinstance(dec, ast.Name) and dec.id == "overload":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "overload":
            return True
    return False


def _is_type_checking(test: ast.AST) -> bool:
    """``if TYPE_CHECKING:`` / ``if t.TYPE_CHECKING:`` guards."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _start_line(node: ast.AST) -> int:
    """Decorator-inclusive start line — the symbol begins at its first
    decorator, which is the convention the engine's nodes follow."""
    lines = [node.lineno]  # type: ignore[attr-defined]
    for dec in getattr(node, "decorator_list", []):
        lines.append(dec.lineno)
    return min(lines)


def _walk_definitions(tree: ast.AST, path: str) -> List[Definition]:
    """Defs in the engine's supported static scope: MODULE scope and
    CLASS scope (methods, properties, nested classes).

    Declaration PRESENCE vs runtime REACHABILITY are separate universes:

    - ``if TYPE_CHECKING:`` bodies ARE in this universe (declared symbols
      the engine must index for lookup) and are flagged ``type_only`` —
      the runtime-impact oracle (:func:`resolve_direct_calls`) excludes
      them. The ``else`` branch of such a guard is the runtime path and
      is kept unflagged.
    - defs nested inside functions are excluded (locals; the engine has
      no nodes for them and dedupes same-name duplicates into one
      representative);
    - ``@overload`` stubs are excluded (the implementation def is the
      real symbol).
    """
    defs: List[Definition] = []

    def visit_class(node: ast.ClassDef, type_only: bool) -> None:
        defs.append(Definition(path, node.name, "class", _start_line(node), type_only))
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not _is_overload(child):
                    defs.append(
                        Definition(path, child.name, "function",
                                   _start_line(child), type_only)
                    )
            elif isinstance(child, ast.ClassDef):
                visit_class(child, type_only)

    def visit_stmts(stmts: List[ast.stmt], type_only: bool) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If) and _is_type_checking(stmt.test):
                # Guard body: declared but type-only. The else branch is
                # the runtime path — walk it with type_only reset.
                visit_stmts(stmt.body, True)
                visit_stmts(stmt.orelse, False)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not _is_overload(stmt):
                    defs.append(
                        Definition(path, stmt.name, "function",
                                   _start_line(stmt), type_only)
                    )
            elif isinstance(stmt, ast.ClassDef):
                visit_class(stmt, type_only)

    visit_stmts(tree.body, False)  # type: ignore[attr-defined]
    return defs


def extract_definitions(
    root: Path,
    config: OracleConfig,
) -> Tuple[List[Definition], List[str]]:
    """Every def/class in every kept .py file, plus parse failures.

    Files that CPython's ``ast`` cannot parse are excluded from the
    oracle universe and REPORTED — the benchmark reports them as
    unsupported-syntax, never as silent misses.
    """
    defs: List[Definition] = []
    failures: List[str] = []
    for rel in iter_python_files(root, config):
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            failures.append(rel)
            continue
        defs.extend(_walk_definitions(tree, rel))
    return defs, failures


def all_definition_names(root: Path, config: OracleConfig) -> Set[Tuple[str, str]]:
    """EVERY def/class name ast can see, in every scope — the validation
    universe for presence PRECISION.

    Unlike :func:`extract_definitions` (the supported-scope recall
    universe), this includes function-local defs, module-level
    conditional blocks (``if WINDOWS:``), ``TYPE_CHECKING`` bodies and
    ``@overload`` stubs: the engine indexes some of those, and an
    engine node pointing at any def that physically exists in the
    source is NOT a hallucination — only names ast cannot find at all
    are precision failures.
    """
    names: Set[Tuple[str, str]] = set()
    for rel in iter_python_files(root, config):
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add((rel, node.name))
    return names


def _module_key(rel: str) -> str:
    """app/pkg/mod.py -> 'mod' (last stem) — from-import resolution key."""
    return Path(rel).stem


def _type_checking_spans(tree: ast.AST) -> List[Tuple[int, int]]:
    """Inclusive line ranges covered by the bodies of ``if TYPE_CHECKING:``
    guards (anywhere in the file). Call/import statements lexically inside
    a guard never execute, so they are not runtime edges and stay out of
    the impact oracle — mirroring the engine's extractor policy.
    """
    spans: List[Tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            starts = [_start_line(s) for s in node.body]
            ends = [
                getattr(s, "end_lineno", None) or s.lineno for s in node.body
            ]
            if starts and ends:
                spans.append((min(starts), max(ends)))
    return spans


def _in_spans(lineno: int, spans: List[Tuple[int, int]]) -> bool:
    return any(start <= lineno <= end for start, end in spans)


def resolve_direct_calls(
    root: Path,
    defs: List[Definition],
    config: OracleConfig,
) -> Tuple[List[CallEdge], int]:
    """Direct-call edges under the SUPPORTED STATIC scope only.

    In scope: same-file bare-name calls, and calls through names bound
    by ``from <module> import <name>`` where exactly one kept file has
    that module stem and defines that name. Attribute calls, star
    imports and re-exports are out of scope (counted as unresolved).

    RUNTIME-IMPACT universe: ``type_only`` definitions (declared inside
    ``if TYPE_CHECKING:`` guards) never resolve calls here, and call or
    import statements lexically inside a guard body are skipped — the
    engine must not fabricate runtime edges for them either.
    Returns (edges, unresolved_call_names).
    """
    runtime_defs = [d for d in defs if not d.type_only]
    by_module: Dict[str, List[Definition]] = {}
    by_file_name: Dict[str, Set[str]] = {}
    for d in runtime_defs:
        by_module.setdefault(_module_key(d.path), []).append(d)
        by_file_name.setdefault(d.path, set()).add(d.name)

    edges: List[CallEdge] = []
    unresolved = 0
    for rel in iter_python_files(root, config):
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        tc_spans = _type_checking_spans(tree)
        # from-import aliases: local name -> (module stem, original name)
        imported: Dict[str, Tuple[str, str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if _in_spans(node.lineno, tc_spans):
                    continue  # type-only import: not a runtime binding
                stem = node.module.split(".")[-1]
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    imported[alias.asname or alias.name] = (stem, alias.name)
        local_defs = by_file_name.get(rel, set())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if _in_spans(node.lineno, tc_spans):
                    continue  # call inside a TYPE_CHECKING guard: no runtime edge
                func = node.func
                callee_name: Optional[str] = None
                via_import = False
                if isinstance(func, ast.Name):
                    callee_name = func.id
                    if func.id in imported:
                        stem, orig = imported[func.id]
                        callees = [d for d in by_module.get(stem, []) if d.name == orig]
                        if len(callees) == 1:
                            for caller in _enclosing(tree, node.lineno):
                                edges.append(
                                    CallEdge(rel, caller, orig, callees[0].path)
                                )
                            continue
                        via_import = True
                if callee_name is None or via_import:
                    if callee_name is None:
                        unresolved += 1
                    continue
                if callee_name in local_defs:
                    for caller in _enclosing(tree, node.lineno):
                        edges.append(CallEdge(rel, caller, callee_name, rel))
    return edges, unresolved


def _enclosing(tree: ast.AST, lineno: int) -> List[str]:
    """Innermost enclosing function chain, dotted (e.g. ``Class.method``).

    The engine indexes nested defs as qualified nodes
    (``outer.inner``) and attributes a call to the def that lexically
    contains it, so the oracle mirrors that: INNERMOST enclosing
    function/method, classes above it kept in the dotted chain. Calls
    inside lambdas or comprehensions belong to the enclosing def.
    Class-body and module-level call sites have no function caller at
    all and are out of the supported static scope.
    """
    # deepest (chain, innermost-holder-is-function) so far
    holder: List[Tuple[List[str], bool]] = [([], False)]

    def visit(node: ast.AST, stack: List[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                end = child.end_lineno or child.lineno
                if child.lineno <= lineno <= max(end, child.lineno):
                    candidate = stack + [child.name]
                    is_func = isinstance(
                        child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    if len(candidate) > len(holder[0][0]):
                        holder[0] = (candidate, is_func)
                    visit(child, candidate)
                    continue
            visit(child, stack)

    visit(tree, [])
    chain, innermost_is_function = holder[0]
    if chain and innermost_is_function:
        return [".".join(chain)]
    return []


def sample_definitions(
    defs: List[Definition],
    seed: int,
    limit: int,
) -> List[Definition]:
    rng = random.Random(f"sg204-presence-{seed}")
    pool = list(defs)
    if len(pool) <= limit:
        return pool
    return sorted(rng.sample(pool, limit), key=lambda d: (d.path, d.line))


def mutated_queries(
    defs: List[Definition],
    seed: int,
    limit: int,
) -> List[str]:
    """Deterministic names that must NOT exist (abstention probes).

    The engine's search prefixes every token (``"tok"*``), so appending
    digits to a real name still matches via the first token. Probes
    therefore REVERSE the name and strip separators first —
    ``int_to_bytes`` becomes ``setybotni`` — yielding one long token no
    real token starts with (a short part like ``ot`` alone would still
    prefix-match ``other``), then digits are appended for uniqueness.
    """
    rng = random.Random(f"sg204-abstain-{seed}")
    pool = [d.name for d in defs] or ["zzz"]
    probes: Set[str] = set()
    while len(probes) < min(limit, max(1, len(pool))):
        base = "".join(c for c in rng.choice(pool)[::-1] if c.isalnum())
        probes.add(f"{base}{rng.randrange(10**6, 10**7):07d}zz")
    return sorted(probes)


def is_test_path(rel: str) -> bool:
    """True when the repo-relative path is a pytest-style test module."""
    return rel.endswith(".py") and bool(_TEST_NAME.search(Path(rel).name))


def test_files(root: Path, config: OracleConfig) -> List[str]:
    out: List[str] = []
    for rel in iter_python_files(root, config):
        name = Path(rel).name
        if _TEST_NAME.search(name):
            out.append(rel)
    return out


def referenced_names(text: str) -> Set[str]:
    """Bare names referenced by a source text (ast Name ids only).

    Attribute names (``x.replace``) are deliberately NOT counted: the
    test-selection ground truth flags tests that reference a changed
    symbol directly, and an attribute hit is almost always a method on
    an unrelated object (``str.replace``) — counting it produces
    name-collision false positives against the engine's graph, which
    resolves bare calls and imports only. A parse failure falls back to
    a word scan — coarse-but-honest beats silently skipping the file.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set(re.findall(r"\b([A-Za-z_]\w*)\b", text))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def top_level_delta(head_text: str, base_text: str) -> Set[str]:
    """Top-level def/class names added, removed or changed between two
    file revisions — the ground-truth changed-symbol set for a diff."""

    def top(names: Set[str], src: str) -> None:
        for match in _TOP_LEVEL_DEF.finditer(src):
            names.add(match.group(1) or match.group(2) or "")

    head_names: Set[str] = set()
    base_names: Set[str] = set()
    top(head_names, head_text)
    top(base_names, base_text)
    return head_names ^ base_names
