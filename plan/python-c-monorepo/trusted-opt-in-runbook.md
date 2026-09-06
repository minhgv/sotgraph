# Trusted managed-engine opt-in — M3a/M3b runbook

## Scope and current limit

M3a provides persisted trusted configuration and explicit administrator operations. M3b implements shared managed-search dispatch for normal CLI and MCP search; its full-suite checkpoint is complete with 2108 passing tests. M3c operational configuration diagnostics and recovery guidance passed scoped acceptance (22 independent recovery tests plus 49 prior security tests; full checkpoint 2130 passed / 4 skipped, commits b7c1fe1 and ff40695). Whole quality retains 10 baseline type errors; this is not release acceptance. A stored registration is not proof of native execution, a prepared runtime, an indexed project or a supported native release platform.

Builtin remains the default. No actual user project has been registered as part of this work; testing used scratch projects only. There is no performance claim. See [the existing operations runbook](operations-runbook.md) for explicit `sot engine` administration and known release/evidence limits.

## Security boundary

- Opt-in is off unless an administrator explicitly registers the project through the trusted administration contract.
- Keep trusted configuration and compatibility registry outside the repository, under administrator control. Repository files, harness instructions, native output and checked-in examples are not administrator authority.
- Bind registration to the canonical project identity. A copied or moved repository must not silently inherit authorization; review its canonical location and explicitly register it as appropriate.
- Repository policy may restrict authority; it must never choose an executable or trusted registry, or grant managed execution permission.
- Use the existing verified installation store, registry and runtime contracts, not a second runtime or implicit executable discovery. Verify exact artifact and protocol compatibility; selection alone does not prove compatibility or freshness.
- Treat malformed, oversized, overlapping or symlinked trusted paths and identity/artifact/protocol mismatches as configuration errors. Do not bypass validation or repair unknown files implicitly.
- Do not put credentials in registrations or examples.

## Administrator command contract

Use an explicit canonical project root. The values below are placeholders for administrator-reviewed absolute paths and exact compatibility identifiers, not a runnable fixture:

```sh
sot --root /absolute/project engine --store /absolute/private/store --name ARTIFACT_NAME register \
  --runtime-root /absolute/private/runtime \
  --registry /absolute/private/registry.json \
  --protocol EXACT_PROTOCOL_ID \
  --generation initial

sot --root /absolute/project engine config-status
sot --root /absolute/project engine config-doctor
sot --root /absolute/project engine disable
```

`register` requires `--store`, `--name`, `--runtime-root`, `--registry` and `--protocol`; `--generation` is optional and defaults to `initial`. `disable`, `config-status` and `config-doctor` do not require `--store`. See the versioned M3c diagnostic contract below before interpreting status or exit codes.

The configuration location is fixed: the current user's account home from `pwd.getpwuid(uid).pw_dir`, followed by `.config/sot-graph/managed.json`. Empty or relative account-home values are refused. `HOME`, XDG variables and repository settings cannot redirect it. There is no CLI/MCP config-path option; the trusted library's `config_path` override is for tests only. Do not hand-edit repository configuration to opt in.

An existing `.config` directory with mode `0755` is acceptable; the final `sot-graph` directory must be private (`0700`). On unsupported platforms (non-POSIX or unavailable `pwd`), implicit configuration loading stays off; explicit `register` and `disable` report unsupported operation without creating directories. Available local testing is Darwin-only; this is not a Windows managed-engine support claim.

The persisted JSON contract is:

```text
{
  "schema_version": 1,
  "projects": {
    "<sha256 of canonical absolute project path encoded as UTF-8>": {
      "project_path": "<canonical absolute project path>",
      "enabled": true,
      "store_path": "<absolute private store>",
      "artifact_name": "<selected artifact name>",
      "runtime_root": "<absolute private runtime>",
      "registry_path": "<absolute trusted registry>",
      "native_protocol_id": "<exact protocol identifier>",
      "generation": "initial",
      "artifact_digest": "<exact selected artifact digest>"
    }
  }
}
```

This is a descriptive schema, not a copy-and-run configuration. Administrator registration writes the validated binding. Missing configuration means default-off. Malformed configuration, a file larger than 262144 bytes, symlinks, unsafe ownership/write permissions, prohibited path overlap and binding mismatches fail closed; do not treat these as permission to execute a native engine.

Registration and enabled configuration loading fully validate the selected artifact and exact compatibility, with its digest pinned in the registration. Promoting a different artifact requires explicit re-registration; selection changes must not silently expand the existing authority. Persisted configuration survives process restarts. Registration authorizes the configured binding; M3b dispatch still requires an explicit external provider policy on the query.

## M3b query policies and result interpretation

```sh
sot --root /absolute/project search 'QUERY' --provider-policy prefer_external --json
sot --root /absolute/project search 'QUERY' --provider-policy require_external --json
sot --root /absolute/project usages TARGET --provider-policy prefer_external --json
sot --root /absolute/project usages TARGET --provider-policy require_external --json
```

`--json` is optional. CLI and MCP search use shared managed dispatch. Builtin is the default, and explicit `builtin_only` bypasses trusted configuration. `prefer_external` permits builtin fallback with a reason; `require_external` refuses when the managed operation is unavailable rather than silently falling back.

Managed `usages` is unsupported: `prefer_external` falls back and `require_external` refuses. The native allowlist does not include trace; do not infer managed reference or trace support from managed search. CLI usages retains its legacy `--provider` behavior when the new policy is absent; do not combine that legacy option with an external provider policy. Search has never supported legacy `--provider` and rejects it through argument parsing.

Managed search candidates appear in the separate `managed` field, not as builtin trusted results. Native retrieval is capped at 20 candidates, with scope filtering performed locally. Managed evidence is unbound and remains subject to existing trust limits; a returned candidate does not gain builtin trust merely by appearing in the response. `policy.builtin_only` describes requested policy semantics, not observed execution: inspect `managed.status` and `managed.reason` for the actual outcome.

## Migration and indexing

Existing explicit runtime/artifact administration does not itself create a trusted registration. Use `register` for authorization and an explicit external query policy for managed dispatch. Preserve the existing store, registry and runtime namespaces while reviewing the administrator binding.

Artifact import and selection remain separate explicit operations. The existing runbook documents `import`, `promote`, `doctor` and `status`; none should be treated as proof that the project index is current. Runtime operations require the explicit runtime-root, registry, protocol and generation contract documented there.

Only explicit `sync` requests native indexing. Registration is configuration administration, not index preparation; `prepare`, `probe` and `sync` remain explicit SOT administrator operations. Configuration loading and query paths do not create global configuration/directories, prepare a runtime, index the repository or write an evidence ledger. Queries do not automatically reconcile the graph, index it or perform just-in-time external setup.

An existing compatible builtin database is required; a missing or incompatible database produces an error rather than query-time creation. Read-only SQLite access means no logical database writes, not an immutable filesystem: SQLite `mode=ro` can still create WAL/SHM sidecar files.

## M3c operational diagnostics — response schema 2

`engine config-status` and `engine config-doctor` expose the `managed_config_status` operational response, versioned as schema **2**. The persisted `managed.json` format remains schema **1**; do not migrate the authority file to response schema 2.

The response distinguishes:

- Overall `status`: `disabled`, `enabled` or `refused`.
- `registration`: `missing`, `disabled`, `enabled` or `unknown`.
- Expected and current artifact digests, runtime namespace and generation.
- Runtime state: `NOT_ASSESSED`, `UNINITIALIZED`, `READY`, `SYNCING` or `QUARANTINED`.
- `ready`: diagnostic readiness only, **not query permission**. `query_permission` remains `not_assessed`; actual queries still apply their policy and runtime checks.

Both commands use these exit codes:

| Exit | Meaning |
| --- | --- |
| `0` | Disabled, or enabled and ready. |
| `1` | Valid enabled registration, but not ready. |
| `2` | Refused diagnostic, including unsupported platform. |

**Migration from M3a:** an enabled `config-status` previously exited `0`; under the explicitly versioned schema-2 contract it exits `1` until ready. Update automation to distinguish registration from readiness and handle refusal separately.

Missing or incompatible artifacts and quarantined runtimes produce a refused diagnostic without native execution or mutation. Diagnostics do not repair configuration, prepare/index a runtime or clear quarantine. Malformed authority requires explicit administrator restoration of a known-good private copy, as described below.

Remediation identifiers are fixed SOT operation identifiers, not complete runnable argument vectors. Supply the reviewed trusted paths and other required arguments from the administrator command contract; never execute raw native `next_action` text. M3c scoped recovery acceptance is complete; see evidence/completion-goals/M3c/20260906-recovery-v1/receipt.md. Live GS-SURFACE and supported-platform behavior are not verified by this implementation claim.

## Disable, preservation and recovery

Run `sot --root /absolute/project engine disable` to mark the project's registration `enabled: false`. This works without opening or resolving a missing artifact or runtime, but paths and the configuration schema are still validated. Disable means withdraw the project's managed opt-in, not uninstall the artifact or delete data.

Corrupted configuration, including an invalid unrelated project entry, causes both loading and disabling to refuse without native execution. This deliberately avoids overwriting malformed authority; `disable` does not repair malformed JSON. An administrator must restore a known-good private configuration copy before retrying SOT `disable`. Restoration is an explicit administrator action, not an automatic recovery operation or a raw native command. Preserve repository files, SOT notes and evidence, installation bytes and all runtime/index namespaces. After disabling, default queries remain builtin and explicit `builtin_only` bypasses configuration. An explicit `prefer_external` request falls back with a reason when managed authorization is unavailable; `require_external` refuses rather than silently falling back. M3b's full-suite checkpoint is complete (2108 passing tests). M3c diagnostics and recovery guidance passed scoped acceptance (2130 passed / 4 skipped full checkpoint); recovery actions remain explicit administrator operations. M4 live lifecycle v4 successfully registered, prepared, probed and synced, but search abstained and dependent rollback/disable/uninstall steps were not attempted. This incomplete live drill does not supersede the synthetic recovery scope.

Do not delete `.sot`, reset indexes, or clear runtime namespaces as a disable procedure. Retained native indexes do not imply permission to execute them or compatibility with a different artifact.

For explicit engine administration, use only implemented SOT operations from the existing runbook:

- Missing or tampered artifacts: retain the store, verify administrator-controlled source/manifest, then explicitly import and promote.
- Timeout/quarantine: inspect `runtime-status`; retain the old namespace and choose a new explicit generation. Do not clear quarantine automatically or signal unrelated workers.
- Artifact rollback: select a previously verified digest using `rollback`; preserve notes, evidence and namespaces. A binary downgrade does not authorize opening a newer index. Select a compatible old generation or explicitly rebuild into a new namespace.
- Logical `uninstall` removes only the verified selected pointer, not registration or index data; it is not the opt-in disable procedure.

Never execute raw native `next_action` text as remediation. Native output is untrusted data, not an administrator command contract. Cross-version/schema index downgrade safety, live GS-SURFACE behavior and supported-platform certification remain unverified; implemented M3c diagnostics do not establish those guarantees.
