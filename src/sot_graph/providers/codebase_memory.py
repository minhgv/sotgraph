"""sot_graph.providers.codebase_memory — one-shot FEDERATED_CLI adapter.

Wire contract (verified against Codebase Memory source @010569f, v0.10.8):
- invocation: ``<command> cli --json <tool> [--flag value | --args-file path]``
  executed as a pure argv list (never a shell), ``cwd`` = canonical repo root.
- stdout carries EXACTLY ONE MCP envelope JSON document:
  ``{"content":[{"type":"text","text":"..."}],"isError":bool,"structuredContent":{}}``
- logs/progress go to stderr and are never part of the payload.
- exit codes: 0 = ok, 1 = error / ``isError`` envelope, 2 = bad arguments.
- bootstrap failures surface as a JSON-RPC error envelope on stdout.
- ``--version`` prints ``codebase-memory-mcp <version>``.

P1 boundaries (honest abstention):
- The adapter NEVER invokes ``index_repository``. A missing/stale index is
  reported as a failed outcome with ``next_action="run sotgraph providers sync
  codebase-memory"`` so the caller can fall back truthfully.
- Evidence normalization/trust ceilings live in ``normalization`` and are
  applied by callers; this module extracts payloads verbatim.
- Remediation surface (hardening): public ``next_action`` comes only from
  an SOT-only allowlist; public errors and record details carry only the
  generic operation + classification — raw native text is withheld
  everywhere (no admin/debug echo path exists).
- Exact-compatibility context (opt-in, admin/programmatic only): every
  dispatch is assessed against the trusted registry BEFORE spawn; the
  executable sha256 is re-verified per dispatch. Only COMPATIBLE may run;
  legacy construction stays version-only and is never promoted.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Mapping, Protocol, runtime_checkable

from sot_graph.proc import RunResult, run_command
from sot_graph.provider_contract import (
    Capability,
    ProviderIdentity,
    normalize_sha256_digest,
)
from sot_graph.snapshot import dirty_state, get_head_sha

from .base import (
    ArchitectureRequest,
    CoverageRequest,
    ImpactRequest,
    IndexRequest,
    ProviderRunRecord,
    ProviderStatus,
    QueryOutcome,
    SymbolRequest,
    TraceRequest,
)
from .compatibility import (
    CompatibilityAssessment,
    CompatibilityRecordError,
    CompatibilityRegistry,
    CompatibilityVerdict,
    normalize_protocol_id,
)
from .normalization import (
    TESTED_CBM_VERSION,
    VERSION_COMPATIBLE,
    VERSION_INCOMPATIBLE,
    VERSION_UNTESTED,
    VERSION_UNKNOWN,
)

if TYPE_CHECKING:  # managed.py imports THIS module at runtime; never reverse
    from .managed import ManagedResult

__all__ = [
    "CodebaseMemoryProvider",
    "PROVIDER_NAME",
    "NEXT_ACTION_SYNC",
    "NEXT_ACTION_VERSION_PIN",
    "NEXT_ACTION_EXPLICIT_PROJECT",
    "NEXT_ACTION_ADAPTER_UPDATE",
    "NEXT_ACTION_ALLOWLIST",
    "allowlisted_next_action",
    "PROBE_OPERATION",
    "ExactCompatibilityContext",
    "SnapshotBinding",
    "SnapshotMatch",
    "snapshot_flags",
]

logger = logging.getLogger(__name__)

PROVIDER_NAME = "codebase-memory"

#: Actionable fix attached to every index-missing/stale abstention (P1).
#: Verified against the CLI parser: ``sotgraph providers sync <provider_name>``
#: exists (src/sot_graph/cli.py, ``prov_subs.add_parser("sync")``).
NEXT_ACTION_SYNC = "run sotgraph providers sync codebase-memory"

#: Wire-incompatible fail-close (G1.5): explicitly unavailable via sotgraph (no
#: pin/upgrade/install command exists); golden version is provenance only.
NEXT_ACTION_VERSION_PIN = (
    "unavailable via sotgraph: no command can pin, upgrade, or install the "
    "codebase-memory binary; queries fail closed on this wire "
    f"(golden-tested {TESTED_CBM_VERSION})"
)

#: Ambiguous or unresolvable project match: sotgraph currently exposes no public
#: way to state a provider project (and no dedupe command), so the outcome
#: honestly reports the resolution as unresolvable — no workaround offered.
NEXT_ACTION_EXPLICIT_PROJECT = (
    "sotgraph cannot currently resolve ambiguous codebase-memory projects; "
    "no sotgraph command applies"
)

#: Adapter schema drift: no sotgraph command fixes a wire format change; rerun
#: once the adapter itself is updated. Ledger-receipt guidance only.
NEXT_ACTION_ADAPTER_UPDATE = (
    "rerun after a sotgraph provider adapter update; no sotgraph command fixes "
    "provider schema drift"
)

#: Registry operation modeling the ``--version``/status probe. Kept distinct
#: from actual tool operations so a registry author explicitly decides
#: whether a verified binary may even be probed.
PROBE_OPERATION = "--version"

#: Public remediation allowlist. ``next_action`` on public outcomes may ONLY
#: carry one of these values (or None): sotgraph commands verified against the
#: CLI parser, explicit "unavailable via sotgraph" markers, or the neutral
#: adapter-update note. Native provider output must never be echoed here.
NEXT_ACTION_ALLOWLIST = frozenset({
    NEXT_ACTION_SYNC,
    NEXT_ACTION_VERSION_PIN,
    NEXT_ACTION_EXPLICIT_PROJECT,
    NEXT_ACTION_ADAPTER_UPDATE,
})


def allowlisted_next_action(value: str | None) -> str | None:
    """Fail-closed pass-through for public ``next_action`` values.

    Allowlisted SOT remediation (and None) passes unchanged; anything else —
    especially any string derived from native provider output — is dropped
    to None with a warning, so hostile native text can never become an
    operational instruction on the public error path.
    """
    if value is None or value in NEXT_ACTION_ALLOWLIST:
        return value
    logger.warning(
        "cbm: dropped non-allowlisted next_action (possible native text "
        "leak): %.160r", value,
    )
    return None


#: ``codebase-memory-mcp <semver>`` — anchored at start of first stdout line.
_VERSION_PATTERN = re.compile(r"^codebase-memory-mcp\s+(\S+)")

DEFAULT_QUERY_TIMEOUT_SECONDS = 30.0
DEFAULT_INDEX_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024

#: argv flag substrings whose VALUE is considered sensitive in any log/ledger.
_SENSITIVE_FLAGS = (
    "token", "secret", "password", "api-key", "apikey", "authorization",
    "credential",
)


@dataclass(frozen=True)
class _InvokeOutcome:
    """Raw result of one CLI invocation plus its ledger-ready run record."""

    ok: bool
    status: str
    payload: Any = None
    error: str | None = None
    run: ProviderRunRecord | None = None
    match: "SnapshotMatch | None" = None
    assessment: "CompatibilityAssessment | None" = None


@runtime_checkable
class ManagedQueryRuntime(Protocol):
    """Structural duck type of ``managed.ManagedNativeRuntime`` (P2).

    Typing-only: ``managed.py`` constructs a CodebaseMemoryProvider at
    runtime, so importing it here would be circular. Injection is validated
    structurally (method presence) plus defensive reads of the runtime's
    bound ``_repo``/``_exe`` — a same-package seam to promote to public
    read-only properties in a later managed.py revision.
    """

    def prepare(self) -> "ManagedResult": ...
    def query(self, operation: str, args: Mapping[str, Any]) -> "ManagedResult": ...
    def sync(self, repo_path: str) -> "ManagedResult": ...


#: Provider query tools a managed runtime serves; every other tool refuses
#: WITHOUT legacy fallback (the unmanaged spawn path is never taken).
_MANAGED_QUERY_TOOLS = frozenset({"search_graph", "list_projects", "index_status"})
#: ManagedResult.status -> legacy outcome status: one normalized outcome shape
#: for downstream ``_query_outcome`` (fail-closed mapping for unknown keys).
_MANAGED_STATUS_MAP = {
    "ok": "ok",
    "not_prepared": "provider_error",
    "denied_operation": "unsupported_managed",
    "gate_refused": "compatibility_unknown",
    "runtime_refused": "provider_error",
    "receipt_invalid": "provider_error",
    "timeout": "timeout",
}
#: The managed search wire pins the adapter default limit (managed.py).
_MANAGED_SEARCH_LIMIT = 20
#: Capabilities the managed runtime can actually serve, drawn from the
#: EXISTING Capability enum: search_graph reads (symbols) and index_status
#: binding/sync receipts (source-verification). Managed advertisement is the
#: intersection with the provider's configured capabilities, never the rest.
_MANAGED_SERVED_CAPABILITIES = frozenset({
    Capability.SYMBOLS.value,
    Capability.SOURCE_VERIFICATION.value,
})


@dataclass(frozen=True)
class _ManagedRunShell:
    """RunResult-shaped view of one managed dispatch for ``_index_record``.

    ``returncode`` is ALWAYS None: a managed receipt exposes no native
    process exit code, so an unknown native exit is persisted as unknown —
    never a fabricated 0/1. The dispatch verdict travels in ``status``;
    no native argv or output text is fabricated either.
    """

    argv: tuple[str, ...] = ("index_repository", "managed")
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    truncated: bool = False
    error: str | None = None


#: Chunk size for bounded-memory artifact hashing (1 MiB).
_HASH_CHUNK_BYTES = 1 << 20


def _file_sha256(path: str) -> str | None:
    """sha256 of file contents read in bounded chunks; None when unreadable.

    Callers re-invoke this per dispatch: no digest is ever cached, so an
    executable swapped between invocations is detected on the next one
    (TOCTOU between hash and spawn remains a documented P2 limitation).
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


@dataclass(frozen=True)
class ExactCompatibilityContext:
    """Opt-in exact-compatibility context (P1) — admin/programmatic only.

    Never derived from repository ``config``: every field is supplied by a
    trusted administrator in code, so an unvalidated repo override cannot
    grant binary trust. Supplying ANY component enables strict mode: every
    dispatch is assessed before spawn and fails closed on UNKNOWN or
    INCOMPATIBLE — partial context never silently downgrades to legacy.

    ``operation_fixture_digests`` maps a tool operation name (or
    ``PROBE_OPERATION``) to the sha256 digest of the fixture suite the
    artifact was tested against for that operation.
    """

    registry: CompatibilityRegistry | None = None
    runtime_identity: ProviderIdentity | None = None
    operation_fixture_digests: Mapping[str, str] | None = None
    protocol_compatibility_id: str | None = None

    def __post_init__(self) -> None:
        if self.registry is not None and not isinstance(
            self.registry, CompatibilityRegistry
        ):
            raise TypeError(
                "registry must be a CompatibilityRegistry, got "
                f"{type(self.registry).__name__}"
            )
        if self.runtime_identity is not None and not isinstance(
            self.runtime_identity, ProviderIdentity
        ):
            raise TypeError(
                "runtime_identity must be a ProviderIdentity, got "
                f"{type(self.runtime_identity).__name__}"
            )
        digests = self.operation_fixture_digests
        if digests is not None:
            if not isinstance(digests, Mapping):
                raise TypeError("operation_fixture_digests must be a Mapping")
            for operation, value in digests.items():
                try:
                    normalize_sha256_digest(value)
                except ValueError as exc:
                    raise CompatibilityRecordError(
                        f"operation_fixture_digests[{operation!r}]: {exc}"
                    ) from exc
        if self.protocol_compatibility_id is not None:
            normalize_protocol_id(self.protocol_compatibility_id)

@dataclass(frozen=True)
class SnapshotBinding:
    """CBM index state captured from one ``index_status`` call (P2).

    Exactly what the wire reported — nothing is fabricated when a field is
    missing; unknown values stay ``None``.
    """

    project: str | None
    head_sha: str | None
    branch: str | None
    index_status: str | None
    captured_at: int


@dataclass(frozen=True)
class SnapshotMatch:
    """Verdict of comparing a CBM index binding against the SOT worktree.

    ``bound``  — an index binding was obtained at all (else UNVERIFIABLE).
    ``fresh``  — the index provably reflects the current HEAD (and, when
                 paths were consulted, every coverage entry was fresh).
    Anything that cannot be proven fresh is ``fresh=False`` (fail-closed):
    ``detail`` distinguishes STALE (head mismatch / stale coverage) from
    UNKNOWN (SOT HEAD unavailable, tooling failure).
    """

    bound: bool
    fresh: bool
    detail: str
    project: str | None = None
    cbm_head_sha: str | None = None
    sot_head_sha: str | None = None
    branch: str | None = None
    stale_paths: tuple[str, ...] = ()
    dirty: bool | None = None  # P1.a: worktree dirty state (None = unverifiable)
    dirty_fingerprint: str | None = None

    @property
    def freshness(self) -> str:
        """FRESH | STALE | UNKNOWN | UNBOUND — the ledger vocabulary."""
        if not self.bound:
            return "UNBOUND"
        if self.fresh:
            return "FRESH"
        if self.dirty:
            return "STALE"  # dirty worktree: content diverged from any commit
        if self.stale_paths or (
            self.cbm_head_sha is not None and self.sot_head_sha is not None
        ):
            return "STALE"
        return "UNKNOWN"


def snapshot_flags(metadata: Mapping[str, Any]) -> tuple[bool, bool]:
    """Extract ``(snapshot_bound, source_changed)`` for trust_ceiling().

    Reads the ``freshness`` marker this adapter attaches to QueryOutcome
    metadata. Fail-closed: anything but FRESH caps at UNVERIFIABLE/STALE,
    so a candidate derived from a mismatched snapshot can NEVER be SUPPORTED.
    """
    freshness = metadata.get("freshness")
    if freshness == "FRESH":
        return True, False
    if freshness == "STALE":
        return True, True
    return False, False




def redact_argv(argv: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Mask values of sensitive flags so argv can be logged/persisted.

    Handles both ``--token abc`` (separated) and ``--token=abc`` (inline).
    """
    redacted: list[str] = []
    sensitive_next = False
    for part in argv:
        if sensitive_next:
            redacted.append("***REDACTED***")
            sensitive_next = False
            continue
        lowered = part.lower()
        if lowered.startswith("--") and any(
            marker in lowered for marker in _SENSITIVE_FLAGS
        ):
            if "=" in part:
                redacted.append(part.split("=", 1)[0] + "=***REDACTED***")
            else:
                redacted.append(part)
                sensitive_next = True
            continue
        redacted.append(part)
    return tuple(redacted)


def _command_digest(redacted: tuple[str, ...]) -> str:
    """Stable sha256 over the REDACTED argv (ledger ``command_digest``)."""
    return hashlib.sha256("\0".join(redacted).encode("utf-8")).hexdigest()


#: Suffix marking that raw native text is NOT included in a public error or
#: record detail: provider-controlled stderr/stdout/envelope text is never
#: quoted, bounded, or paraphrased anywhere — only the generic operation +
#: classification travels.
_NATIVE_TEXT_WITHHELD = "native diagnostic withheld"


def _count_json_documents(text: str) -> int:
    """Count whitespace-separated top-level JSON documents in ``text``.

    Returns -1 when the text is not parseable as JSON at some offset.
    """
    decoder = json.JSONDecoder()
    idx = 0
    count = 0
    stripped = text.strip()
    while idx < len(stripped):
        while idx < len(stripped) and stripped[idx] in " \t\r\n":
            idx += 1
        if idx >= len(stripped):
            break
        try:
            _, end = decoder.raw_decode(stripped, idx)
        except json.JSONDecodeError:
            return -1
        count += 1
        idx = end
    return count


def _extract_payload(envelope: Mapping[str, Any]) -> tuple[Any, str | None]:
    """Extract the tool payload from an MCP success envelope.

    Prefers a non-empty ``structuredContent``; otherwise parses the JSON text
    of ``content[0]``. Returns ``(payload, problem)`` — problem None on success.
    """
    structured = envelope.get("structuredContent")
    if isinstance(structured, Mapping) and structured:
        return dict(structured), None

    content = envelope.get("content")
    if not isinstance(content, list) or not content:
        return None, "schema drift: envelope has no content array"
    first = content[0]
    if not isinstance(first, Mapping):
        return None, "schema drift: content[0] is not an object"
    if first.get("type") != "text":
        return None, f"schema drift: unsupported content type {first.get('type')!r}"
    text = first.get("text")
    if not isinstance(text, str):
        return None, "schema drift: content[0].text missing or not a string"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Text-report tools (search_graph, trace_path, get_architecture)
        # emit a human-readable report instead of JSON (ADR-0001 §6);
        # surface the report verbatim so callers parse documented columns.
        return text, None
    return payload, None


class CodebaseMemoryProvider:
    """Adapter for the Codebase Memory one-shot CLI (FEDERATED_CLI)."""

    #: P3.4 versioned plugin contract this adapter is built against.
    contract_version = 1
    name = "codebase-memory"
    capabilities: tuple[str, ...]

    def __init__(
        self,
        config: Any = None,
        *,
        db: Any = None,
        command: list[str] | tuple[str, ...] | None = None,
        query_timeout_seconds: float | None = None,
        index_timeout_seconds: float | None = None,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        provider_version: str | None = None,
        exact_context: ExactCompatibilityContext | None = None,
        managed_runtime: "ManagedQueryRuntime | None" = None,
        engine_store_root: str | os.PathLike[str] | None = None,
    ) -> None:
        cfg_command: list[str] | None = getattr(config, "command", None)
        cfg_caps = tuple(getattr(config, "capabilities", ()) or ())
        cfg_timeout = getattr(config, "timeout_seconds", None)
        self.command: tuple[str, ...] = tuple(
            command if command is not None else (cfg_command or ["codebase-memory-mcp"])
        )
        self.capabilities = cfg_caps
        self._db = db
        query_timeout = (
            query_timeout_seconds
            if query_timeout_seconds is not None
            else (
                cfg_timeout
                if cfg_timeout is not None
                else DEFAULT_QUERY_TIMEOUT_SECONDS
            )
        )
        index_timeout = (
            index_timeout_seconds
            if index_timeout_seconds is not None
            else (
                cfg_timeout
                if cfg_timeout is not None
                else self._INDEX_TIMEOUT_SECONDS
            )
        )
        self._query_timeout = float(query_timeout)
        self._index_timeout = float(index_timeout)
        self._max_output_bytes = int(max_output_bytes)
        # P1.1 namespace (master plan §7.1): when set, every engine spawn
        # merges CBM_RUNTIME_DIR/CBM_CACHE_DIR into the child env (per-account
        # layout under the engine store); the parent environment is untouched.
        self._engine_store_root = (
            os.fspath(engine_store_root) if engine_store_root is not None else None)
        #: repo_root(realpath) -> (resolved_project, problem, next_action);
        #: avoids one ``list_projects`` round-trip per query on the same root.
        self._project_cache: dict[str, tuple[str | None, str | None, str | None]] = {}
        self._version: str | None = provider_version
        # Guards _version and _project_cache against concurrent probe/query
        # races; reentrant so nested adapter calls stay safe. Critical
        # sections never span a process spawn.
        self._lock = threading.RLock()
        # Strict mode is enabled by ANY supplied context; it is never
        # derivable from repository config (admin/programmatic only).
        if exact_context is not None:
            if not isinstance(exact_context, ExactCompatibilityContext):
                raise TypeError(
                    "exact_context must be an ExactCompatibilityContext, got "
                    f"{type(exact_context).__name__}"
                )
            if command is None:
                raise ValueError(
                    "strict exact-compatibility requires an explicit command= "
                    "(single absolute executable); repository-config command "
                    "is not accepted"
                )
            if len(self.command) != 1:
                raise ValueError(
                    "strict exact-compatibility requires a single-element "
                    "command: interpreter+script argv would bypass artifact "
                    "hashing"
                )
            if not os.path.isabs(self.command[0]):
                raise ValueError(
                    "strict exact-compatibility requires an absolute "
                    "executable path; PATH discovery is refused"
                )
        self._exact = exact_context
        # P2 managed injection (programmatic only; not wired to config/CLI):
        # the caller supplies an already-constructed ManagedNativeRuntime
        # bound to THIS exact context. The command/repo binding captured here
        # is immutable-consistent: every managed dispatch re-checks it and
        # refuses divergence instead of re-binding (no spawn, fail-closed).
        self._managed: ManagedQueryRuntime | None = None
        self._managed_repo: str | None = None
        self._managed_command: tuple[str, ...] | None = None
        if managed_runtime is not None:
            if exact_context is None:
                raise ValueError(
                    "managed_runtime requires exact_context: a managed "
                    "runtime dispatches only under digest-exact gating"
                )
            if not isinstance(managed_runtime, ManagedQueryRuntime):
                raise TypeError(
                    "managed_runtime must expose prepare/query/sync "
                    f"(ManagedQueryRuntime), got {type(managed_runtime).__name__}"
                )
            bound_repo = getattr(managed_runtime, "_repo", None)
            if not isinstance(bound_repo, str) or not bound_repo:
                raise ValueError(
                    "managed runtime does not expose its bound repo; refusing "
                    "an ambiguous repo binding (seam: managed.py should "
                    "promote _repo to a public read-only property)"
                )
            # The runtime must carry the SAME trusted exact context (same
            # object, or equivalent public identity/records/fixture
            # mappings); a divergent trust root is refused, never skipped.
            inner_ctx = getattr(
                getattr(managed_runtime, "_provider", None), "_exact", None)
            if not isinstance(inner_ctx, ExactCompatibilityContext):
                raise ValueError(
                    "managed runtime does not expose its exact-compatibility "
                    "context; refusing an unverifiable identity binding"
                )
            if inner_ctx is not exact_context and not self._managed_context_equivalent(
                    exact_context, inner_ctx):
                raise ValueError(
                    "managed runtime exact context is not the trusted context "
                    "(identity, fixture digests, protocol id, or registry "
                    "records differ); refusing divergent trust roots"
                )
            bound_exe = getattr(managed_runtime, "_exe", None)
            if not isinstance(bound_exe, str) or not bound_exe:
                raise ValueError(
                    "managed runtime does not expose its executable binding; "
                    "refusing an untestable artifact identity"
                )
            if (os.path.realpath(bound_exe)
                    != os.path.realpath(self.command[0])):
                raise ValueError(
                    "managed runtime executable differs from the provider "
                    "command; per-dispatch artifact identity would diverge"
                )
            self._managed = managed_runtime
            self._managed_repo = os.path.realpath(bound_repo)
            self._managed_command = self.command

    @staticmethod
    def _managed_context_equivalent(
        a: ExactCompatibilityContext, b: ExactCompatibilityContext
    ) -> bool:
        """Public-field equivalence of two exact contexts: runtime identity,
        per-operation fixture digests, protocol id, and registry records
        (by value, via the public ``records()`` accessor). No private
        protocol data is read or fabricated."""
        if a.runtime_identity != b.runtime_identity:
            return False
        if dict(a.operation_fixture_digests or {}) != dict(
                b.operation_fixture_digests or {}):
            return False
        if (a.protocol_compatibility_id or None) != (
                b.protocol_compatibility_id or None):
            return False
        if a.registry is None or b.registry is None:
            return a.registry is b.registry
        if a.registry is b.registry:
            return True
        try:
            return Counter(a.registry.records()) == Counter(b.registry.records())
        except Exception:  # noqa: BLE001 - equivalence must never raise
            return False

    @property
    def _strict_compat(self) -> bool:
        """True when any exact-compatibility context component was supplied."""
        return self._exact is not None

    def _locked_version(self) -> str | None:
        """Race-free snapshot of the descriptive provider version string."""
        with self._lock:
            return self._version

    def _identity_basis(
        self, assessment: CompatibilityAssessment | None = None
    ) -> str:
        """Metadata marker derived from THIS dispatch's assessment.

        ``artifact_verified`` — strict gate verdict COMPATIBLE now;
        ``unverified`` — strict but refused/no assessment this dispatch;
        ``version_only`` — legacy; descriptive string, never a binary
        identity claim and never promoted.
        """
        if not self._strict_compat:
            return "version_only"
        if (
            assessment is not None
            and assessment.verdict is CompatibilityVerdict.COMPATIBLE
        ):
            return "artifact_verified"
        return "unverified"

    # ------------------------------------------------- exact-compat gating

    def _compat_gate(self, operation: str) -> CompatibilityAssessment:
        """Assess ``operation`` against the trusted registry; never spawns.

        Order matters: the on-disk executable is hashed fresh (per dispatch,
        bounded chunks) and must match the claimed identity digest BEFORE the
        registry is consulted, so a caller cannot claim a tested artifact it
        does not run. Only the physically verified digest is passed to the
        registry. Any failure is an explicit UNKNOWN/INCOMPATIBLE assessment,
        never an exception and never a legacy fallback.
        """
        ctx = self._exact
        assert ctx is not None
        unknown = CompatibilityVerdict.UNKNOWN

        def _unk(*reasons: str) -> CompatibilityAssessment:
            return CompatibilityAssessment(
                verdict=unknown, reasons=reasons, operation=operation,
            )

        # Re-checked EVERY dispatch: provider.command is public and may be
        # reassigned after construction; ctor validation alone is not a gate.
        if len(self.command) != 1:
            return _unk(
                "strict compatibility context requires a single-element "
                "command; interpreter+script argv would bypass artifact "
                "hashing",
            )
        exe = self.command[0]
        if not os.path.isabs(exe):
            return _unk(
                "strict compatibility context requires an explicit absolute "
                "executable path; PATH discovery is refused",
            )
        resolved = os.path.realpath(exe)
        on_disk = _file_sha256(resolved)
        if on_disk is None:
            return _unk(f"executable not readable at {resolved}")
        identity = ctx.runtime_identity
        if identity is None:
            return _unk("no runtime ProviderIdentity supplied")
        claimed = identity.artifact_sha256
        if claimed is None:
            return _unk(
                "claimed identity carries no artifact_sha256; a version "
                f"string ({identity.version!r}) never identifies a binary",
            )
        try:
            claimed_digest = normalize_sha256_digest(claimed)
        except ValueError as exc:
            return _unk(f"claimed identity artifact_sha256: {exc}")
        if claimed_digest != on_disk:
            return CompatibilityAssessment(
                verdict=CompatibilityVerdict.INCOMPATIBLE,
                reasons=(
                    f"claimed artifact digest {claimed_digest} does not match "
                    f"the executable on disk ({on_disk}); refusing to execute "
                    "an unverified binary",
                ),
                operation=operation,
                artifact_sha256=on_disk,
            )
        registry = ctx.registry
        if registry is None:
            return _unk("no compatibility registry supplied")
        fixture = (
            ctx.operation_fixture_digests.get(operation)
            if ctx.operation_fixture_digests is not None
            else None
        )
        try:
            return registry.assess(
                replace(identity, artifact_sha256=on_disk),
                operation,
                fixture_digest=fixture,
                protocol_compatibility_id=ctx.protocol_compatibility_id,
            )
        except CompatibilityRecordError as exc:
            return _unk(f"invalid compatibility context: {exc}")

    def _gate_outcome(
        self, tool: str, assessment: CompatibilityAssessment
    ) -> _InvokeOutcome:
        """No-spawn fail-closed outcome for a refused dispatch."""
        verdict = assessment.verdict
        status = (
            "compatibility_incompatible"
            if verdict is CompatibilityVerdict.INCOMPATIBLE
            else "compatibility_unknown"
        )
        detail = (
            f"{tool} refused before dispatch: exact-compatibility "
            f"{verdict.value}; native diagnostic withheld"
        )
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._locked_version(),
            capability=tool,
            status=status,
            exit_code=None,
            duration_ms=0,
            arguments_redacted=(tool,),
            # Reviewed remediation surface stays frozen: compatibility
            # fail-close reuses the allowlisted "unavailable via sotgraph" pin.
            next_action=NEXT_ACTION_VERSION_PIN,
            detail=detail,
        )
        return _InvokeOutcome(
            ok=False, status=status, error=detail, run=record,
            assessment=assessment,
        )

    def version_compatibility(self) -> str:
        """Classify the probed binary release against the golden-tested one.

        COMPATIBLE   — exact match; the golden fixtures prove this wire.
        UNTESTED     — same major.minor, different patch; queries still run
                       but downstream verdicts cap at UNVERIFIABLE.
        INCOMPATIBLE — different major.minor; queries fail closed.
        UNKNOWN      — probe has not produced a parsable version yet.

        Strict mode always reports UNKNOWN here: a version string alone
        never claims compatibility when artifact identity is enforced —
        the per-dispatch gate verdict drives outcome metadata instead.
        """
        if self._strict_compat:
            return VERSION_UNKNOWN
        with self._lock:
            version = self._version
        if version is None:
            return VERSION_UNKNOWN
        if version == TESTED_CBM_VERSION:
            return VERSION_COMPATIBLE
        if version.split(".")[:2] == TESTED_CBM_VERSION.split(".")[:2]:
            return VERSION_UNTESTED
        return VERSION_INCOMPATIBLE

    def _engine_spawn_env(self) -> dict[str, str] | None:
        """Namespaced engine env for one-shot spawns; ``None`` when opted out.

        Fail-closed: an unusable store raises BootstrapError (RuntimeError)
        with a clean message instead of falling back to the default layout.
        """
        if self._engine_store_root is None:
            return None
        from .bootstrap import engine_runtime_env
        return engine_runtime_env(self._engine_store_root, PROVIDER_NAME)

    def probe(self, repo_root: str) -> ProviderStatus:
        """Probe ``<command> --version``; never raises.

        Strict mode: the executable digest is verified (and the probe
        operation registry-assessed) BEFORE the spawn; an unknown version
        string does not block the probe — the verified digest is the
        identity, ``--version`` merely fills descriptive metadata.
        """
        if self._managed is not None:
            return self._managed_probe()
        gate: CompatibilityAssessment | None = None
        if self._strict_compat:
            gate = self._compat_gate(PROBE_OPERATION)
            if gate.verdict is not CompatibilityVerdict.COMPATIBLE:
                refused = self._gate_outcome(PROBE_OPERATION, gate)
                installed = _file_sha256(os.path.realpath(self.command[0])) is not None
                return ProviderStatus(
                    name=PROVIDER_NAME,
                    installed=installed,
                    healthy=False,
                    version=None,
                    detail=refused.error or "compatibility gate refused",
                    capabilities=self.capabilities,
                )
        started = time.monotonic()
        result = run_command(
            [*self.command, "--version"],
            cwd=os.path.realpath(repo_root),
            timeout_seconds=min(self._query_timeout, 15.0),
            max_output_bytes=self._max_output_bytes,
            env_extra=self._engine_spawn_env(),
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        self._persist_run(
            capability="probe", result=result, duration_ms=duration_ms,
            status=self._probe_status(result), repo_root=repo_root,
        )

        if result.error is not None:
            return ProviderStatus(
                name=PROVIDER_NAME,
                installed=False,
                healthy=False,
                version=None,
                detail=f"not installed: {result.error}",
                capabilities=self.capabilities,
            )
        match = _VERSION_PATTERN.match(result.stdout.strip())
        if result.returncode != 0 or match is None:
            detail = "unhealthy: " + (
                f"exit={result.returncode}" if result.returncode != 0
                else f"unparseable version output; {_NATIVE_TEXT_WITHHELD}"
            )
            return ProviderStatus(
                name=PROVIDER_NAME,
                installed=True,
                healthy=False,
                version=None,
                detail=detail,
                capabilities=self.capabilities,
            )
        with self._lock:
            self._version = match.group(1)
            version = self._version
        if gate is not None:
            # Strict mode: report the actual gate verdict, never the
            # deliberately-UNKNOWN version-only classification.
            detail = f"ok; exact-compat={gate.verdict.value}"
        else:
            detail = f"ok; wire-compat={self.version_compatibility()}"
        return ProviderStatus(
            name=PROVIDER_NAME,
            installed=True,
            healthy=True,
            version=version,
            detail=detail,
            capabilities=self.capabilities,
        )

    def _probe_status(self, result: RunResult) -> str:
        if result.error is not None:
            return "spawn_failed"
        if result.timed_out:
            return "timeout"
        if result.returncode == 0 and _VERSION_PATTERN.match(result.stdout.strip()):
            return "ok"
        return "error"

    # -------------------------------------------------- managed runtime (P2)

    def _managed_probe(self) -> ProviderStatus:
        """Managed probe: prepared-state read only; NO native dispatch.

        The managed runtime exposes no probe operation, and a native
        ``--version`` spawn would be an unmanaged path that could write into
        an unprepared profile. The trust gate is therefore assessed against a
        MANAGED-SERVED operation (``index_status``) — evidence a --version
        record can never provide — and health additionally requires a valid
        readiness marker. ``--version`` stays an explicit operation
        diagnostic, never part of the managed probe, and a state read
        persists no run receipt. Advertised capabilities are the
        intersection with what the managed runtime can serve.
        """
        problem = self._managed_binding_problem(self._managed_repo or "")
        gate = self._compat_gate("index_status")
        if problem is None and gate.verdict is not CompatibilityVerdict.COMPATIBLE:
            problem = (
                f"index_status exact-compatibility {gate.verdict.value}; "
                "native diagnostic withheld"
            )
        installed = _file_sha256(os.path.realpath(self.command[0])) is not None
        if problem is None and not self._managed_prepared():
            problem = (
                "managed runtime present but not prepared (or state "
                "unreadable); run the explicit sync path; the managed probe "
                "performs no native call"
            )
        if problem is not None:
            return ProviderStatus(
                name=PROVIDER_NAME, installed=installed, healthy=False,
                version=None, detail=problem,
                capabilities=self._managed_capabilities(),
            )
        return ProviderStatus(
            name=PROVIDER_NAME, installed=installed, healthy=True, version=None,
            detail=("ok; managed runtime prepared; exact-compat(index_status)"
                    "=compatible; version withheld (managed probe performs "
                    "no --version)"),
            capabilities=self._managed_capabilities(),
        )

    def _managed_capabilities(self) -> tuple[str, ...]:
        """Advertised capabilities intersected with managed-served ones:
        only the operations this runtime can actually serve are claimed."""
        return tuple(
            c for c in self.capabilities
            if str(c) in _MANAGED_SERVED_CAPABILITIES
        )

    def _managed_binding_problem(self, repo_root: str) -> str | None:
        """Immutable-binding check re-run before EVERY managed dispatch."""
        if self._managed is None:
            return "no managed runtime bound"
        if self.command != self._managed_command:
            return (
                "provider command changed after managed binding; refusing to "
                "dispatch through the runtime"
            )
        if os.path.realpath(repo_root) != self._managed_repo:
            return (
                "repo does not match the managed runtime binding; managed "
                "evidence covers exactly one repo and is never re-bound"
            )
        return None

    def _managed_prepared(self) -> bool:
        """Read runtime readiness WITHOUT any dispatch (probe path).

        Structural same-package read of the profile state and readiness
        marker (managed.py exposes prepared state only privately at this
        stage). Any unreadable/foreign runtime reports not prepared.
        """
        profile = getattr(self._managed, "_profile", None)
        marker_state = getattr(self._managed, "_marker_state", None)
        if profile is None or not callable(marker_state):
            return False
        try:
            if profile.status().get("state") != "READY":
                return False
            state = marker_state()
            return isinstance(state, tuple) and len(state) == 2 and state[0] == "valid"
        except Exception:  # noqa: BLE001 - a state read must never raise
            return False

    def _managed_run_record(
        self, tool: str, status: str, duration_ms: int, detail: str,
        gate: CompatibilityAssessment | None,
    ) -> ProviderRunRecord:
        """Record for one managed dispatch. NEVER persisted from a query
        path (queries write no ledger); runtime state and identity travel
        in the detail (artifact_verified only via a COMPATIBLE gate)."""
        profile = getattr(self._managed, "_profile", None)
        state: Any = None
        try:
            state = profile.status().get("state") if profile is not None else None
        except Exception:  # noqa: BLE001
            state = None
        return ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._locked_version(),
            capability=tool,
            status=status,
            exit_code=None,  # managed receipts expose no native exit code
            duration_ms=duration_ms,
            arguments_redacted=(tool, "managed"),
            next_action=(
                NEXT_ACTION_VERSION_PIN if status == "compatibility_unknown"
                else None
            ),
            detail=(
                f"{detail}; managed runtime_state={state or 'unknown'}; "
                f"identity_basis={self._identity_basis(gate)}"
            ),
        )

    def _managed_invoke(
        self,
        tool: str,
        args: Mapping[str, Any],
        *,
        repo_root: str,
        project: str | None,
        snapshot_bind: bool,
        gate: CompatibilityAssessment | None,
    ) -> _InvokeOutcome:
        """Route one query through the managed runtime.

        NO unmanaged spawn and NO ledger write: a query never prepares,
        never initializes, and never persists (read-only contract). Only
        the allowlisted wire args travel; the runtime injects the verified
        project binding itself. Outcome keeps the legacy normalized shape
        so ``_query_outcome``/snapshot normalization are reused unchanged.
        """
        refusal_status = "runtime_refused"
        problem = self._managed_binding_problem(repo_root)
        if problem is None and tool not in _MANAGED_QUERY_TOOLS:
            refusal_status = "unsupported_managed"
            problem = (
                f"{tool} is not a managed runtime read (managed reads: "
                f"{sorted(_MANAGED_QUERY_TOOLS)}); refusing without legacy "
                "fallback"
            )
        if problem is None and tool == "search_graph":
            if args.get("language") is not None:
                refusal_status = "unsupported_managed"
                problem = (
                    "search_graph language filter has no managed read "
                    "argument; refusing without legacy fallback"
                )
            elif args.get("limit", _MANAGED_SEARCH_LIMIT) != _MANAGED_SEARCH_LIMIT:
                refusal_status = "unsupported_managed"
                problem = (
                    "search_graph limit "
                    f"{args.get('limit')!r} is not the managed wire limit; "
                    "refusing without legacy fallback"
                )
        runtime = self._managed
        if runtime is None:
            problem = problem or "no managed runtime bound"
        if problem is not None or runtime is None:
            problem = problem or "no managed runtime bound"
            record = self._managed_run_record(
                tool, refusal_status, 0, problem, gate)
            return _InvokeOutcome(False, refusal_status, error=problem,
                                  run=record, assessment=gate)
        margs: dict[str, Any] = (
            {"query": args["query"]} if tool == "search_graph" else {}
        )
        started = time.monotonic()
        failure: str | None = None
        status = "runtime_refused"
        mr: "ManagedResult | None" = None
        try:
            mr = runtime.query(tool, margs)
        except Exception as exc:  # noqa: BLE001 - dispatch never raises
            failure = (
                f"managed dispatch raised {type(exc).__name__}; "
                "diagnostic withheld"
            )
        else:
            status = _MANAGED_STATUS_MAP.get(mr.status, "provider_error")
            failure = mr.error
            if mr.cancellation_state:
                failure = f"{failure or mr.status}; {mr.cancellation_state}"
        duration_ms = int((time.monotonic() - started) * 1000)
        if mr is None:
            record = self._managed_run_record(
                tool, "runtime_refused", duration_ms, failure or "", gate)
            return _InvokeOutcome(False, "runtime_refused", error=failure,
                                  run=record, assessment=gate)
        payload = mr.payload if isinstance(mr.payload, dict) else None
        if (
            tool == "list_projects" and status == "ok"
            and isinstance(mr.payload, dict) and mr.payload.get("has_more")
        ):
            status, failure, payload = "schema_drift", (
                "managed listing exceeded one page; pagination is not a "
                "managed read capability"
            ), None
        # A runtime-side gate refusal overrides this dispatch's identity
        # claim: artifact_verified is never reported from a refused gate.
        assessment = None if mr.status == "gate_refused" else gate
        detail = failure or "managed dispatch ok"
        transport = getattr(mr, "transport", None)
        if transport is not None:  # P1.2 additive provenance (honest D6)
            detail += f"; transport={transport}"
            if getattr(mr, "fallback_reason", None):
                detail += f" (fallback: {mr.fallback_reason})"
        run = self._managed_run_record(
            tool, status, duration_ms, detail, assessment,
        )
        match = (
            self.snapshot_match(repo_root, project=project)
            if snapshot_bind and status == "ok" else None
        )
        return _InvokeOutcome(status == "ok", status, payload, failure,
                              run=run, match=match, assessment=assessment)

    def _managed_index(
        self, request: IndexRequest, gate: CompatibilityAssessment | None
    ) -> ProviderRunRecord:
        """Explicit managed sync: ``prepare()`` then ``sync()`` on the
        BOUND repo only. Success is a bool on receipt verification alone
        (status=indexed plus a runtime-verified project binding). The
        receipt is persisted through the SAME ``_index_record`` ledger path
        as the legacy sync — snapshot/evidence rules are never bypassed —
        and a snapshot binding is published ONLY when the worktree can
        prove freshness AND an independent native ``index_status`` reports
        the same head_sha (the SOT head alone never publishes). Runtime
        exceptions become safe non-ok receipts; nothing raises past this
        method."""
        repo_path = os.path.realpath(request.repo_root)
        pre_head = get_head_sha(repo_path)
        pre_dirty, _ = dirty_state(repo_path)
        started = time.monotonic()
        problem = self._managed_binding_problem(repo_path)
        runtime = self._managed
        if runtime is None:
            problem = problem or "no managed runtime bound"
        status, detail = "provider_error", problem or ""
        if problem is None and runtime is not None:
            prep: "ManagedResult | None" = None
            sync_res: "ManagedResult | None" = None
            try:
                prep = runtime.prepare()
            except Exception as exc:  # noqa: BLE001 - receipt, never raise
                detail = (
                    "managed prepare raised "
                    f"{type(exc).__name__}; diagnostic withheld"
                )
            if prep is not None and prep.status != "ok":
                detail = prep.error or "managed prepare refused"
                if prep.cancellation_state:
                    detail += f"; {prep.cancellation_state}"
            elif prep is not None:
                try:
                    sync_res = runtime.sync(repo_path)
                except Exception as exc:  # noqa: BLE001 - receipt, never raise
                    detail = (
                        "managed sync raised "
                        f"{type(exc).__name__}; diagnostic withheld"
                    )
                else:
                    if sync_res.status == "ok":
                        status, detail = "ok", (
                            "managed sync completed; receipt verified "
                            "(status=indexed, project binding verified)"
                        )
                    else:
                        status = (
                            "timeout" if sync_res.status == "timeout"
                            else "provider_error"
                        )
                        detail = sync_res.error or (
                            f"managed sync refused ({sync_res.status})"
                        )
                        if sync_res.cancellation_state:
                            detail += f"; {sync_res.cancellation_state}"
        shell = _ManagedRunShell(
            timed_out=status == "timeout",
            error=None if status == "ok" else detail,
        )
        return self._index_record(
            request, result=shell, status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
            detail=detail, redacted=("index_repository", "managed"),
            pre_head=pre_head, pre_dirty=pre_dirty,
            require_native_head=True, strict_publication=True,
        )

    # ----------------------------------------------------------------- invoke

    def _invoke(
        self,
        tool: str,
        args: Mapping[str, Any],
        *,
        repo_root: str,
        timeout_seconds: float,
        project: str | None = None,
        snapshot_bind: bool = False,
    ) -> _InvokeOutcome:
        """Run one one-shot CLI tool call; never raises.

        The request travels as a JSON ``--args-file`` so no user-controlled
        string ever touches a shell or argv quoting rules. With
        ``snapshot_bind=True`` a successful call additionally fetches
        ``index_status`` (P2) and records the snapshot match with the run.
        """
        # Strict mode: assess BEFORE any spawn; re-hashes the executable
        # fresh on every dispatch so a swapped binary is caught next call.
        # The legacy version veto applies only to the legacy path — a
        # digest-exact COMPATIBLE gate verdict outranks version strings.
        gate: CompatibilityAssessment | None = None
        if self._strict_compat:
            gate = self._compat_gate(tool)
            if gate.verdict is not CompatibilityVerdict.COMPATIBLE:
                return self._gate_outcome(tool, gate)
        elif self.version_compatibility() == VERSION_INCOMPATIBLE:
            detail = (
                f"probed version {self._locked_version()!r} is wire-incompatible "
                f"with golden-tested {TESTED_CBM_VERSION!r}; refusing to query"
            )
            record = ProviderRunRecord(
                run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
                provider_name=PROVIDER_NAME,
                provider_version=self._locked_version(),
                capability=tool,
                status="version_incompatible",
                exit_code=None,
                duration_ms=0,
                arguments_redacted=(tool, repo_root),
                next_action=NEXT_ACTION_VERSION_PIN,
                detail=detail,
            )
            logger.info("cbm %s refused: %s", tool, detail)
            return _InvokeOutcome(
                ok=False, status="version_incompatible",
                error=detail, run=record,
            )
        if self._managed is not None:
            # Managed routing (strict gate already passed above): the
            # unmanaged spawn/args-file path below is never reached.
            return self._managed_invoke(
                tool, args, repo_root=repo_root, project=project,
                snapshot_bind=snapshot_bind, gate=gate,
            )
        cwd = os.path.realpath(repo_root)
        args_file: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="cbm-req-", delete=False,
                encoding="utf-8",
            ) as handle:
                json.dump(dict(args), handle, ensure_ascii=False)
                args_file = handle.name

            argv = [*self.command, "cli", "--json", tool, "--args-file", args_file]
            started = time.monotonic()
            result = run_command(
                argv,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                max_output_bytes=self._max_output_bytes,
                env_extra=self._engine_spawn_env(),
            )
            duration_ms = int((time.monotonic() - started) * 1000)
        finally:
            if args_file is not None:
                try:
                    os.unlink(args_file)
                except OSError:  # pragma: no cover - best-effort cleanup
                    pass

        redacted = redact_argv(result.argv)
        outcome = self._shape_outcome(tool, result)
        logger.debug(
            "cbm cli tool=%s exit=%s timed_out=%s truncated=%s duration_ms=%d "
            "status=%s argv=%s",
            tool, result.returncode, result.timed_out, result.truncated,
            duration_ms, outcome.status, list(redacted),
        )
        match: SnapshotMatch | None = None
        if snapshot_bind and outcome.ok and not result.timed_out:
            match = self.snapshot_match(repo_root, project=project)
        evidence_items = self._evidence_items(
            tool, outcome, match
        ) if outcome.ok else []
        run = self._persist_run(
            capability=tool, result=result, duration_ms=duration_ms,
            status=outcome.status, repo_root=cwd, redacted=redacted,
            match=match, evidence_items=evidence_items,
        )
        return _InvokeOutcome(
            ok=outcome.ok, status=outcome.status, payload=outcome.payload,
            error=outcome.error, run=run, match=match, assessment=gate,
        )

    def _evidence_items(self, tool, outcome, match) -> list[dict]:
        """Build ledger evidence items from one successful outcome (P6).

        Pure extraction: no I/O, no ledger access. Items are persisted
        atomically with their run via ``record_provider_outcome``.
        """
        from sot_graph.assurance.orchestrator import (
            search_rows_from_payload,
            trace_edges_from_payload,
        )

        items: list[dict] = []
        payload = outcome.payload
        if not isinstance(payload, Mapping):
            # Text-report drift passthrough (P3.1) and other non-object
            # payloads carry no structured rows: zero evidence, never guess.
            return items
        payload = dict(payload)
        snap = match.cbm_head_sha if match is not None and match.bound else None
        if tool in ("trace_path", "trace", "impact"):
            for edge in trace_edges_from_payload(payload):
                items.append({
                    "path": "",
                    "symbol": str(edge.get("root") or ""),
                    "target_symbol": str(edge.get("qualified_name") or ""),
                    "relation": f"call:{edge.get('direction', 'out')}",
                    "snapshot_hash": snap,
                    "metadata_json": {"hop": edge.get("hop"),
                                      "edge_type": edge.get("edge_type"),
                                      "strategy": edge.get("strategy")},
                    "confidence": (
                        edge["confidence"]
                        if edge.get("confidence") is not None
                        else 1.0
                    ),
                })
        else:
            rows, _more, drift = search_rows_from_payload(payload)
            if not drift:
                for row in rows:
                    items.append({
                        "path": row.get("path") or "",
                        "symbol": row.get("qualified_name") or "",
                        "relation": "define",
                        "line_start": row.get("start_line"),
                        "line_end": row.get("end_line"),
                        "syntax_kind": row.get("kind"),
                        "snapshot_hash": snap,
                    })
        return items

    def _shape_outcome(self, tool: str, result: RunResult) -> _InvokeOutcome:
        """Classify one completed invocation against the wire contract."""
        if result.error is not None:
            return _InvokeOutcome(False, "spawn_failed", error=result.error)
        if result.timed_out:
            return _InvokeOutcome(
                False, "timeout",
                error=f"{tool} exceeded its time budget and was killed",
            )
        if result.truncated:
            return _InvokeOutcome(
                False, "truncated",
                error=(f"{tool} output exceeded the byte cap; refusing "
                       "partial evidence"),
            )
        # Contract: exit != 0 means failure regardless of stdout content
        # (1 = tool error / isError, 2 = bad arguments). Public errors carry
        # only the generic operation + classification: raw native text is
        # never quoted (it can carry actionable provider instructions).
        if result.returncode not in (0, None):
            status = (
                "bad_arguments" if result.returncode == 2 else "provider_error"
            )
            return _InvokeOutcome(
                False, status,
                error=f"{tool} exited {result.returncode}; {_NATIVE_TEXT_WITHHELD}",
            )
        if not result.stdout.strip():
            return _InvokeOutcome(
                False, "empty_stdout",
                error=f"{tool} produced no stdout; {_NATIVE_TEXT_WITHHELD}",
            )

        doc_count = _count_json_documents(result.stdout)
        if doc_count < 0:
            return _InvokeOutcome(
                False, "invalid_json",
                error=f"{tool} stdout is not valid JSON; {_NATIVE_TEXT_WITHHELD}",
            )
        if doc_count > 1:
            return _InvokeOutcome(
                False, "multiple_json",
                error=(f"{tool} stdout carried {doc_count} JSON documents; "
                       "the wire contract allows exactly one"),
            )

        envelope: Any = json.loads(result.stdout.strip())
        # JSON-RPC error envelope: {"jsonrpc":..,"error":{..}} without content.
        if isinstance(envelope, dict) and "error" in envelope and "content" not in envelope:
            return _InvokeOutcome(
                False, "jsonrpc_error",
                error=f"{tool} jsonrpc error envelope; {_NATIVE_TEXT_WITHHELD}",
            )
        if not isinstance(envelope, dict):
            return _InvokeOutcome(
                False, "schema_drift",
                error=(f"{tool} envelope is {type(envelope).__name__}, "
                       "expected object"),
            )

        if envelope.get("isError"):
            return _InvokeOutcome(
                False, "provider_error",
                error=(f"{tool} error envelope; provider reported failure; "
                       f"{_NATIVE_TEXT_WITHHELD}"),
            )

        payload, problem = _extract_payload(envelope)
        if problem is not None:
            return _InvokeOutcome(False, "schema_drift", error=problem)
        return _InvokeOutcome(True, "ok", payload=payload)

    # ------------------------------------------------------------- persistence

    def _persist_run(
        self,
        *,
        capability: str,
        result: RunResult,
        duration_ms: int,
        status: str,
        repo_root: str,
        redacted: tuple[str, ...] | None = None,
        match: SnapshotMatch | None = None,
        evidence_items: list[dict] | None = None,
    ) -> ProviderRunRecord:
        """Build the run record; persist run+binding+evidence atomically.

        P0 Contract 4: when a ledger is available the whole outcome goes
        through ``record_provider_outcome`` in ONE transaction — a failure
        rolls back run, binding, and evidence together. Without a ledger
        the record is returned so the caller can persist it. Ledger
        failures are swallowed (logged) — a broken ledger must never
        corrupt or abort an otherwise successful query.
        """
        with self._lock:
            version = self._version
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=version,
            capability=capability,
            status=status,
            exit_code=result.returncode,
            duration_ms=duration_ms,
            arguments_redacted=(
                redacted if redacted is not None else redact_argv(result.argv)
            ),
        )
        if self._db is not None:
            snapshot_hash = (
                match.cbm_head_sha if match is not None and match.bound else None
            )
            run_kwargs: dict = dict(
                provider_name=PROVIDER_NAME,
                provider_version=version,
                capability=capability,
                snapshot_hash=snapshot_hash,
                project_root=repo_root,
                position_encoding="UTF-8",
                arguments_json=json.dumps(list(record.arguments_redacted)),
                run_id=record.run_id,
                status=status,
                exit_code=result.returncode,
                duration_ms=duration_ms,
                command_digest=_command_digest(record.arguments_redacted),
            )
            binding = None
            if (
                match is not None and match.bound and match.project
                and getattr(self._db, "record_provider_binding", None)
                is not None
            ):
                binding = dict(
                    sot_repo_id=repo_root,
                    provider_name=PROVIDER_NAME,
                    provider_project_id=match.project,
                    head_sha=match.cbm_head_sha,
                    branch=match.branch,
                )
            atomic = getattr(self._db, "record_provider_outcome", None)
            try:
                if atomic is not None:
                    atomic(
                        run_kwargs,
                        binding,
                        evidence_items or [],
                    )
                else:
                    # Sidecar without the atomic API (test doubles):
                    # fall back to the per-method sequence.
                    self._db.record_provider_run(**run_kwargs)
                    if binding is not None:
                        self._db.record_provider_binding(**binding)
                    if evidence_items:
                        self._db.record_provider_evidence(
                            record.run_id, evidence_items
                        )
            except Exception as exc:  # pragma: no cover - defensive ledger guard
                logger.warning(
                    "cbm ledger persistence failed for run %s: %s",
                    record.run_id, exc,
                )
        return record

    @staticmethod
    def _match_metadata(match: SnapshotMatch | None) -> dict[str, Any]:
        """Metadata block attached to every bound QueryOutcome."""
        if match is None:
            return {"freshness": "UNBOUND", "snapshot_bound": False}
        meta: dict[str, Any] = {
            "freshness": match.freshness,
            "snapshot_bound": match.bound,
            "snapshot": {
                "cbm_head_sha": match.cbm_head_sha,
                "sot_head_sha": match.sot_head_sha,
                "branch": match.branch,
                "detail": match.detail,
                "stale_paths": list(match.stale_paths),
            },
        }
        # Convenience flags for trust_ceiling(): (snapshot_bound, source_changed)
        bound, changed = snapshot_flags(meta)
        meta["source_changed"] = changed
        return meta

    def _query_outcome(self, outcome: _InvokeOutcome) -> QueryOutcome:
        """Shape a raw invoke outcome into an honest public QueryOutcome.

        Provider-side failures (a missing/stale index surfaces as
        provider_error) carry ``next_action`` pointing at the explicit sync
        command; the caller falls back truthfully instead of serving partial
        evidence. When the invocation carried a snapshot binding (P2), the
        freshness verdict travels in ``metadata`` so downstream trust
        ceilings can downgrade stale evidence without re-querying.
        """
        index_related = outcome.status in (
            "provider_error", "jsonrpc_error", "spawn_failed", "bad_arguments",
        )
        if self._strict_compat:
            # Exact mode: COMPATIBLE here is backed by THIS dispatch's
            # digest-verified gate (identity_basis below), never by the
            # version string; everything else stays UNKNOWN (fail-closed
            # for trust normalization).
            version_compat = (
                VERSION_COMPATIBLE
                if outcome.assessment is not None
                and outcome.assessment.verdict is CompatibilityVerdict.COMPATIBLE
                else VERSION_UNKNOWN
            )
        else:
            version_compat = self.version_compatibility()
        metadata: dict[str, Any] = {
            "wire_status": outcome.status,
            "version_compatibility": version_compat,
            "identity_basis": self._identity_basis(outcome.assessment),
        }
        # Exact-compatibility assessment travels serialized in outcome
        # metadata: CLI and MCP consume this same QueryOutcome, so there is
        # exactly one serialization and one parser.
        if outcome.assessment is not None:
            metadata["exact_compatibility"] = outcome.assessment.to_dict()
        # Fail-closed: every outcome carries an explicit freshness marker;
        # unbound/unknown defaults cap downstream trust at UNVERIFIABLE.
        metadata.update(self._match_metadata(outcome.match))
        if outcome.status in (
            "compatibility_unknown", "compatibility_incompatible",
        ):
            next_action = NEXT_ACTION_VERSION_PIN
        elif outcome.status == "version_incompatible":
            next_action = NEXT_ACTION_VERSION_PIN
        elif index_related:
            next_action = NEXT_ACTION_SYNC
        else:
            next_action = None
        return QueryOutcome(
            ok=outcome.ok,
            run=outcome.run,  # type: ignore[arg-type]
            payload=outcome.payload,
            error=outcome.error,
            # Fail-closed allowlist: never promote anything (least of all
            # native-derived text) into an operational instruction.
            next_action=allowlisted_next_action(next_action),
            metadata=metadata,
        )

    # ------------------------------------------------------------ P1 surface

    # ------------------------------------------------- project resolution

    def _abstained_outcome(
        self,
        capability: str,
        repo_root: str,
        detail: str | None,
        next_action: str | None,
    ) -> QueryOutcome:
        """Honest no-spawn outcome when a query cannot even be addressed."""
        detail = detail or "query could not be addressed"
        next_action = allowlisted_next_action(next_action)
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._locked_version(),
            capability=capability,
            status="abstained",
            exit_code=None,
            duration_ms=0,
            arguments_redacted=(capability, repo_root),
            next_action=next_action,
            detail=detail,
        )
        return QueryOutcome(
            ok=False, run=record, payload=None, error=detail,
            next_action=next_action,
            metadata={"wire_status": "abstained",
                      "identity_basis": self._identity_basis(),
                      "freshness": "UNBOUND",
                      "snapshot_bound": False},
        )

    def resolve_project(
        self, repo_root: str
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve the CBM project name covering ``repo_root``.

        Never guesses: exactly one ``list_projects`` entry whose canonicalized
        ``root_path`` equals ``realpath(repo_root)`` wins; zero matches or two
        or more matches abstain with an SOT-only ``next_action`` (sync, or
        explicit-project since sotgraph has no command to disambiguate). Results
        are cached per repo root for the lifetime of this instance.
        """
        target = os.path.realpath(repo_root)
        with self._lock:
            cached = self._project_cache.get(target)
        if cached is not None:
            return cached
        all_projects: list[Any] = []
        has_more = True
        offset = 0
        limit = 50
        cursor = None
        seen_cursors: set[str] = set()
        loop_abort = False
        cap_exhausted = False
        max_safety_cap = 1000

        while has_more:
            args: dict[str, Any] = {"limit": limit, "offset": offset}
            if cursor is not None:
                args["cursor"] = cursor
            outcome = self._invoke(
                "list_projects", args,
                repo_root=repo_root,
                timeout_seconds=self._query_timeout,
            )
            if not outcome.ok or not isinstance(outcome.payload, Mapping):
                if outcome.status.startswith("compatibility_"):
                    # Never cached: the refusal is repairable (registry/
                    # binary fix) and must keep its own remediation, not
                    # degrade to the sync command. Next dispatch re-gates.
                    return (
                        None,
                        f"list_projects refused: {outcome.error}",
                        NEXT_ACTION_VERSION_PIN,
                    )
                resolved: tuple[str | None, str | None, str | None] = (
                    None,
                    f"list_projects failed: {outcome.error}",
                    NEXT_ACTION_SYNC,
                )
                with self._lock:
                    self._project_cache[target] = resolved
                return resolved
            projects = outcome.payload.get("projects")
            if isinstance(projects, list) and projects:
                all_projects.extend(projects)
                offset += len(projects)
            else:
                if outcome.payload.get("has_more"):
                    loop_abort = True
                break

            next_cursor = outcome.payload.get("next_cursor") or outcome.payload.get("cursor")
            if next_cursor:
                if str(next_cursor) in seen_cursors:
                    loop_abort = True
                    break
                seen_cursors.add(str(next_cursor))
                cursor = next_cursor

            has_more = bool(outcome.payload.get("has_more"))
            if not has_more:
                break
            if len(all_projects) >= max_safety_cap:
                cap_exhausted = True
                break

        if loop_abort or cap_exhausted:
            return (
                None,
                "list_projects pagination incomplete (loop=%s, cap=%s); "
                "sotgraph cannot currently resolve ambiguous provider projects"
                % (loop_abort, cap_exhausted),
                NEXT_ACTION_EXPLICIT_PROJECT,
            )
        matches = [
            p["name"] for p in all_projects
            if isinstance(p, Mapping)
            and isinstance(p.get("name"), str)
            and isinstance(p.get("root_path"), str)
            and os.path.realpath(p["root_path"]) == target
        ]
        if len(matches) == 1:
            resolved = (matches[0], None, None)
        elif len(matches) == 0:
            resolved = (
                None,
                f"no indexed CBM project covers {target}",
                NEXT_ACTION_SYNC,
            )
        else:
            resolved = (
                None,
                # Count only: raw project names are never echoed publicly.
                "ambiguous: %d indexed projects cover %s; sotgraph cannot "
                "currently disambiguate provider projects"
                % (len(matches), target),
                NEXT_ACTION_EXPLICIT_PROJECT,
            )
        with self._lock:
            self._project_cache[target] = resolved
        return resolved

    def _project_for(
        self, repo_root: str, explicit: str | None
    ) -> tuple[str | None, str | None, str | None]:
        """Explicit caller project wins; otherwise resolve via list_projects."""
        if explicit is not None:
            return explicit, None, None
        return self.resolve_project(repo_root)

    # ------------------------------------------------- P2 snapshot binding

    def _index_binding(
        self, repo_root: str, project: str | None
    ) -> SnapshotBinding | None:
        """Fetch one ``index_status`` binding for ``project``; None on failure.

        Deliberately NOT snapshot-bound itself (no recursion) and never
        raises: a failed probe degrades to an unbound match downstream.
        """
        args: dict[str, Any] = {}
        if project is not None:
            args["project"] = project
        try:
            outcome = self._invoke(
                "index_status", args,
                repo_root=repo_root,
                timeout_seconds=self._query_timeout,
            )
        except Exception:  # pragma: no cover - _invoke already never raises
            return None
        if not outcome.ok or not isinstance(outcome.payload, Mapping):
            return None
        payload = outcome.payload
        head = payload.get("head_sha")
        branch = payload.get("branch")
        status = payload.get("status")
        # Managed mode: the SOT-ledger stored head is NEVER native proof.
        # Only the provider's own index_status output may bind a head, so
        # the legacy ledger fallback below is skipped entirely when a
        # managed runtime is bound (a missing native head stays missing).
        if (
            not head and (status in ("ready", "ok")) and self._db is not None
            and project is not None and self._managed is None
        ):
            db_binding_api = getattr(self._db, "get_provider_binding", None)
            if db_binding_api is not None:
                row = (
                    db_binding_api(repo_root, PROVIDER_NAME)
                    or db_binding_api(os.path.realpath(repo_root), PROVIDER_NAME)
                )
                if row and row.get("provider_project_id") == project:
                    head = row.get("head_sha")
                    if not branch:
                        branch = row.get("branch")
        return SnapshotBinding(
            project=project,
            head_sha=head if isinstance(head, str) else None,
            branch=branch if isinstance(branch, str) else None,
            index_status=status if isinstance(status, str) else None,
            captured_at=int(time.time()),
        )

    def snapshot_match(
        self,
        repo_root: str,
        paths: tuple[str, ...] | list[str] = (),
        *,
        project: str | None = None,
    ) -> SnapshotMatch:
        """Compare the CBM index state against the SOT worktree (P2+P1.a).

        (a) CBM ``head_sha`` (via index_status) vs SOT HEAD SHA; (b) SOT
        worktree dirty state — checked unconditionally, even when ``paths``
        is empty — because the index binds to the committed tree, so any
        uncommitted change caps freshness at STALE; (c) when ``paths`` are
        given, every ``check_index_coverage`` entry must report
        ``hash_status == "fresh"``. Fail-closed: any unprovable step yields
        ``fresh=False`` with a distinguishing ``detail``.
        """
        resolved, problem, _next_action = self._project_for(repo_root, project)
        if resolved is None:
            return SnapshotMatch(
                bound=False, fresh=False,
                detail=f"unbound: {problem}",
            )
        binding = self._index_binding(repo_root, resolved)
        if binding is None or not binding.head_sha:
            return SnapshotMatch(
                bound=False, fresh=False, project=resolved,
                detail="unbound: index_status failed or reported no head_sha",
            )
        sot_head = get_head_sha(os.path.realpath(repo_root))
        if sot_head is None:
            return SnapshotMatch(
                bound=True, fresh=False, project=resolved,
                detail="unknown: SOT HEAD unavailable (not a git repo or no commits)",
                cbm_head_sha=binding.head_sha, branch=binding.branch,
            )
        fresh = binding.head_sha == sot_head
        detail = (
            "head_sha matches"
            if fresh
            else f"stale: cbm head_sha {binding.head_sha[:12]} != "
                 f"sot HEAD {sot_head[:12]}"
        )
        # P1.a: the CBM index binds to the COMMITTED tree. A dirty worktree —
        # checked unconditionally, including paths=() — means content the
        # index cannot prove anything about, so freshness caps at STALE even
        # when head_sha matches (blocker #1).
        worktree_root = os.path.realpath(repo_root)
        dirty, fingerprint = dirty_state(worktree_root)
        if dirty is None:
            fresh = False
            detail += "; unknown: worktree dirty state unverifiable (git status failed)"
        elif dirty:
            fresh = False
            detail += f"; stale: dirty worktree ({fingerprint or 'fingerprint unavailable'})"
        stale_paths: list[str] = []
        if paths:
            cov = self._invoke(
                "check_index_coverage", {"paths": list(paths)},
                repo_root=repo_root,
                timeout_seconds=self._query_timeout,
            )
            entries = (
                cov.payload.get("entries")
                if cov.ok and isinstance(cov.payload, Mapping) else None
            )
            if not isinstance(entries, list):
                fresh = False
                detail += "; unknown: coverage check unavailable"
            else:
                bad = [
                    e.get("path", "?")
                    for e in entries
                    if isinstance(e, Mapping) and e.get("hash_status") != "fresh"
                ]
                if bad:
                    fresh = False
                    stale_paths = [str(p) for p in bad]
                    detail += "; stale coverage: " + ", ".join(stale_paths[:5])
        return SnapshotMatch(
            bound=True, fresh=fresh, detail=detail, project=resolved,
            cbm_head_sha=binding.head_sha, sot_head_sha=sot_head,
            branch=binding.branch, stale_paths=tuple(stale_paths),
            dirty=dirty, dirty_fingerprint=fingerprint,
        )

    #: Explicit index sync budget: indexing is heavyweight, queries are not.
    _INDEX_TIMEOUT_SECONDS = 900.0

    def ensure_index(self, request: IndexRequest) -> ProviderRunRecord:
        """Implicit-path abstention: queries NEVER trigger indexing.

        The explicit admin path is :meth:`index` (``sotgraph providers sync``);
        keeping this hook abstaining preserves the no-implicit-index
        invariant for every read-side caller.
        """
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._locked_version(),
            capability="ensure_index",
            status="abstained",
            exit_code=None,
            duration_ms=0,
            arguments_redacted=(
                "ensure_index", request.repo_root, f"force={request.force}",
            ),
            next_action=NEXT_ACTION_SYNC,
            detail="implicit indexing refused; run 'sotgraph providers sync "
                   "codebase-memory' for the explicit index path",
        )
        logger.info("cbm ensure_index abstained: %s", NEXT_ACTION_SYNC)
        return record

    def index(self, request: IndexRequest, *, progress: bool = False) -> ProviderRunRecord:
        """EXPLICIT index sync: invoke ``index_repository`` and record it.

        Never called from a read path. Own time budget (heavyweight), args
        travel via --args-file, and the run is persisted whatever the exit
        status so the ledger keeps the receipt. ``--progress`` forwards the
        provider's own progress stream for interactive syncs.

        Strict mode: the explicit index operation is gated like every tool —
        without a tested record for ``index_repository`` the mutation is
        explicitly unavailable and never attempted (no mutating fallback).
        """
        gate: CompatibilityAssessment | None = None
        if self._strict_compat:
            gate = self._compat_gate("index_repository")
            if gate.verdict is not CompatibilityVerdict.COMPATIBLE:
                refused = self._gate_outcome("index_repository", gate)
                return self._index_record(
                    request, result=None, status=refused.status,
                    duration_ms=0, detail=refused.error or "compatibility gate refused",
                    redacted=("index_repository",),
                    next_action=NEXT_ACTION_VERSION_PIN,
                )
        if self._managed is not None:
            # Managed sync: prepare() + sync() through the runtime, receipt
            # persisted via the same _index_record ledger path below.
            return self._managed_index(request, gate)
        timeout = (
            request.timeout_seconds
            if request.timeout_seconds is not None
            else self._index_timeout
        )
        repo_path = os.path.realpath(request.repo_root)
        pre_head = get_head_sha(repo_path)
        pre_dirty, _ = dirty_state(repo_path)
        args: dict[str, Any] = {"repo_path": repo_path}
        argv = [
            *self.command, "cli",
            *(["--progress"] if progress else []),
            "--json", "index_repository", "--args-file", "@ARGS@",
        ]
        # run_command takes a closed argv; splice the real args-file in below.
        args_file: str | None = None
        started = time.monotonic()
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="cbm-index-", delete=False,
                encoding="utf-8",
            ) as handle:
                json.dump(args, handle, ensure_ascii=False)
                args_file = handle.name
            argv[argv.index("@ARGS@")] = args_file
            result = run_command(
                argv, cwd=repo_path,
                timeout_seconds=timeout,
                max_output_bytes=self._max_output_bytes,
                env_extra=self._engine_spawn_env(),
            )
            duration_ms = int((time.monotonic() - started) * 1000)
        except OSError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._index_record(
                request, result=None, status="spawn_failed",
                duration_ms=duration_ms, detail=str(exc), redacted=("index_repository",),
                pre_head=pre_head, pre_dirty=pre_dirty,
            )
        finally:
            if args_file is not None:
                try:
                    os.unlink(args_file)
                except OSError:  # pragma: no cover - best-effort cleanup
                    pass
        if result.timed_out:
            status, detail = "timeout", (
                "index_repository exceeded its time budget and was killed; "
                "re-run 'sotgraph providers sync codebase-memory' to resume"
            )
        elif result.error is not None:
            status, detail = "spawn_failed", result.error
        elif result.truncated:
            status, detail = "truncated", (
                "index_repository output exceeded the byte cap; index state unknown"
            )
        elif result.returncode not in (0, None):
            # Sync is a public CLI/MCP surface, not a debug mode: no native
            # text is echoed here either.
            status, detail = (
                "bad_arguments" if result.returncode == 2 else "provider_error"
            ), (f"index_repository exited {result.returncode}; "
                f"{_NATIVE_TEXT_WITHHELD}")
        else:
            status, detail = "ok", "index_repository completed"
        return self._index_record(
            request, result=result, status=status, duration_ms=duration_ms,
            detail=detail, redacted=tuple(redact_argv(result.argv)),
            pre_head=pre_head, pre_dirty=pre_dirty,
        )

    def _index_record(
        self, request: IndexRequest, *, result, status: str,
        duration_ms: int, detail: str, redacted: tuple,
        pre_head: str | None = None, pre_dirty: bool | None = None,
        next_action: str | None = None,
        require_native_head: bool = False,
        strict_publication: bool = False,
    ) -> ProviderRunRecord:
        version = self._locked_version()
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=version,
            capability="index_repository",
            status=status,
            exit_code=(result.returncode if result is not None else None),
            duration_ms=duration_ms,
            arguments_redacted=redacted,
            next_action=(
                next_action if next_action is not None
                else (None if status == "ok" else NEXT_ACTION_SYNC)
            ),
            detail=detail,
        )
        if result is not None and self._db is not None:
            try:
                snap_hash = None
                binding_dict = None
                if status == "ok":
                    repo_path = os.path.realpath(request.repo_root)
                    post_head = get_head_sha(repo_path)
                    post_dirty, _ = dirty_state(repo_path)
                    if (
                        pre_head is not None
                        and pre_head == post_head
                        and pre_dirty is False
                        and post_dirty is False
                    ):
                        self._project_cache.pop(repo_path, None)
                        resolved_proj, _, _ = self.resolve_project(request.repo_root)
                        publish = bool(resolved_proj)
                        if resolved_proj and require_native_head:
                            # Managed sync: the SOT HEAD alone is NEVER proof
                            # that the provider index reflects it. An
                            # independent native index_status must report the
                            # SAME head_sha, or no binding is published (the
                            # prior ledger binding, if any, is preserved).
                            native = self._index_binding(
                                request.repo_root, resolved_proj)
                            publish = (
                                native is not None
                                and native.head_sha is not None
                                and native.head_sha == post_head
                            )
                        if publish:
                            snap_hash = post_head
                            binding_dict = {
                                "sot_repo_id": request.repo_root,
                                "provider_name": PROVIDER_NAME,
                                "provider_project_id": resolved_proj,
                                "head_sha": snap_hash,
                                "branch": None,
                            }
                run_dict = {
                    "provider_name": PROVIDER_NAME,
                    "provider_version": version,
                    "capability": "index_repository",
                    "snapshot_hash": snap_hash,
                    "project_root": os.path.realpath(request.repo_root),
                    "position_encoding": "UTF-8",
                    "arguments_json": json.dumps(list(record.arguments_redacted)),
                    "run_id": record.run_id,
                    "status": status,
                    "exit_code": result.returncode,
                    "duration_ms": duration_ms,
                    "command_digest": _command_digest(record.arguments_redacted),
                }
                outcome_api = getattr(self._db, "record_provider_outcome", None)
                if outcome_api is not None:
                    outcome_api(
                        run=run_dict,
                        binding=binding_dict,
                        evidence=[],
                    )
                else:
                    self._db.record_provider_run(**run_dict)
            except Exception as exc:  # noqa: BLE001 - sidecar isolation
                logger.warning("cbm index run ledger write failed: %s", exc)
                # Managed-only strict boundary: a publication failure is
                # NEVER returned as ok/success. The native completion stays
                # a separate diagnostic, no persisted receipt is invented
                # (the atomic transaction already rolled back), and the
                # READY runtime is not quarantined for a ledger fault.
                # Legacy behavior (swallow, keep dispatch status) is
                # unchanged: strict_publication defaults to False.
                if strict_publication and record.status == "ok":
                    record = ProviderRunRecord(
                        run_id=record.run_id,
                        provider_name=record.provider_name,
                        provider_version=record.provider_version,
                        capability=record.capability,
                        status="publication_failed",
                        exit_code=record.exit_code,
                        duration_ms=record.duration_ms,
                        arguments_redacted=record.arguments_redacted,
                        next_action=NEXT_ACTION_SYNC,
                        detail=(
                            "native sync completed; ledger publication "
                            "failed and no receipt was persisted; "
                            f"{NEXT_ACTION_SYNC}"
                        ),
                    )
        else:
            logger.info("cbm index_repository %s: %s", status, detail)
        return record

    def _structured_payload(self, shaped: QueryOutcome, tool: str) -> QueryOutcome:
        """Decode the ``format=json`` payload of a successful outcome (P3.1).

        The wire's JSON body arrives as the envelope text content, so this
        adapter owns the str -> object decode: any drift (non-JSON text,
        non-object body) is a fail-closed ``schema_drift`` outcome — never
        parsed leniently, never passed through as text for someone else to
        guess at.
        """
        if not shaped.ok:
            return shaped
        payload = shaped.payload
        if isinstance(payload, Mapping):
            return shaped
        if not isinstance(payload, str):
            return self._drift_outcome(tool, "payload is not JSON text")
        try:
            decoded = json.loads(payload)
        except ValueError:
            return self._drift_outcome(
                tool, "format=json payload is not valid JSON text"
            )
        if not isinstance(decoded, Mapping):
            return self._drift_outcome(
                tool, f"format=json payload is {type(decoded).__name__}, expected object"
            )
        return QueryOutcome(
            ok=shaped.ok, run=shaped.run, payload=decoded,
            error=shaped.error, next_action=shaped.next_action,
            metadata=shaped.metadata,
        )

    def _drift_outcome(self, tool: str, detail: str) -> QueryOutcome:
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._locked_version(),
            capability=tool,
            status="schema_drift",
            exit_code=None,
            duration_ms=0,
            arguments_redacted=(tool,),
            next_action=NEXT_ACTION_ADAPTER_UPDATE,
            detail=detail,
        )
        return QueryOutcome(
            ok=False, run=record, payload=None,
            error=f"{tool} schema drift: {detail}; abstaining",
            next_action=None,
            metadata={"wire_status": "schema_drift",
                      "version_compatibility": self.version_compatibility(),
                      "identity_basis": self._identity_basis(),
                      "freshness": "UNBOUND", "snapshot_bound": False},
        )

    def search_symbols(self, request: SymbolRequest) -> QueryOutcome:
        """Structured symbol search via ``search_graph`` with format=json."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "search_graph", request.repo_root, problem, next_action
            )
        args: dict[str, Any] = {
            "query": request.query, "limit": request.limit,
            "project": project, "format": "json",
        }
        if request.language is not None:
            args["language"] = request.language
        outcome = self._invoke(
            "search_graph", args,
            repo_root=request.repo_root,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self._query_timeout
            ),
            project=project, snapshot_bind=True,
        )
        return self._structured_payload(self._query_outcome(outcome), "search_graph")

    def trace(self, request: TraceRequest) -> QueryOutcome:
        """Structured call-path trace via ``trace_path`` with format=json."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "trace_path", request.repo_root, problem, next_action
            )
        outcome = self._invoke(
            "trace_path",
            {
                # The real wire expects ``function_name`` (ADR-0001 §6) and
                # ``depth`` (P3.1: map the request's max_depth).
                "function_name": request.symbol,
                "direction": request.direction,
                "depth": request.max_depth,
                "project": project,
                "format": "json",
                "include_evidence": True,
            },
            repo_root=request.repo_root,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self._query_timeout
            ),
            project=project, snapshot_bind=True,
        )
        return self._structured_payload(self._query_outcome(outcome), "trace_path")

    def _refine_coverage_freshness(self, shaped: QueryOutcome) -> QueryOutcome:
        """Downgrade a bound coverage outcome whose entries are not fresh.

        The check_index_coverage payload is authoritative for path-level
        staleness: any entry without ``hash_status == "fresh"`` marks the
        run STALE even when head_sha still matches (content hashes lag the
        commit pointer after uncommitted edits).
        """
        entries = (
            shaped.payload.get("entries")
            if isinstance(shaped.payload, Mapping) else None
        )
        if not isinstance(entries, list):
            return shaped  # schema drift elsewhere; do not invent staleness
        stale_paths = [
            str(e.get("path", "?"))
            for e in entries
            if isinstance(e, Mapping) and e.get("hash_status") != "fresh"
        ]
        if not stale_paths:
            return shaped
        metadata = dict(shaped.metadata)
        snapshot = dict(metadata.get("snapshot") or {})
        snapshot["stale_paths"] = stale_paths
        snapshot["detail"] = (
            str(snapshot.get("detail", "")) + "; stale coverage: "
            + ", ".join(stale_paths[:5])
        ).strip()
        metadata["snapshot"] = snapshot
        metadata["freshness"] = "STALE"
        metadata["source_changed"] = True
        return QueryOutcome(
            ok=shaped.ok, run=shaped.run, payload=shaped.payload,
            error=shaped.error, next_action=shaped.next_action,
            metadata=metadata,
        )

    def impact(self, request: ImpactRequest) -> QueryOutcome:
        """Blast-radius query via ``detect_changes`` with format=json.

        The wire diffs git refs (``since...HEAD``). A staged or working-tree
        scope cannot be represented there — the adapter records an honest
        scope conflict instead of merging scopes builtin never asked for.
        """
        if request.staged or request.working_tree:
            scopes = ", ".join(
                s for s, on in (
                    ("staged", request.staged),
                    ("working-tree", request.working_tree),
                ) if on
            )
            return self._abstained_outcome(
                "detect_changes", request.repo_root,
                f"scope conflict: detect_changes compares git refs "
                f"(since...HEAD) only; {scopes} scope is builtin-only and is "
                f"never merged into external evidence",
                next_action=None,
            )
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "detect_changes", request.repo_root, problem, next_action
            )
        args: dict[str, Any] = {
            "project": project,
            "scope": "impact",
            "direction": "inbound",
            "depth": request.depth,
            "format": "json",
        }
        if request.since is not None:
            args["since"] = request.since
        outcome = self._invoke(
            "detect_changes", args,
            repo_root=request.repo_root,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self._query_timeout
            ),
            project=project, snapshot_bind=True,
        )
        return self._structured_payload(self._query_outcome(outcome), "detect_changes")

    def architecture(self, request: ArchitectureRequest) -> QueryOutcome:
        """Module structure via the ``get_architecture`` tool."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "get_architecture", request.repo_root, problem, next_action
            )
        outcome = self._invoke(
            "get_architecture", {"project": project},
            repo_root=request.repo_root,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self._query_timeout
            ),
            project=project, snapshot_bind=True,
        )
        return self._query_outcome(outcome)

    def coverage(self, request: CoverageRequest) -> QueryOutcome:
        """Index-coverage check via ``check_index_coverage`` (P3.1: explicit project)."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "check_index_coverage", request.repo_root, problem, next_action
            )
        args: dict[str, Any] = {
            "paths": list(request.paths), "project": project,
        }
        outcome = self._invoke(
            "check_index_coverage", args,
            repo_root=request.repo_root,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self._query_timeout
            ),
            project=project, snapshot_bind=True,
        )
        shaped = self._query_outcome(outcome)
        if not shaped.ok:
            return QueryOutcome(
                ok=False, run=shaped.run, payload=None, error=shaped.error,
                # A compatibility gate refusal keeps its own remediation
                # (sync cannot fix missing test evidence).
                next_action=shaped.next_action or NEXT_ACTION_SYNC,
                metadata=shaped.metadata,
            )
        return self._refine_coverage_freshness(shaped)
