# Trusted managed-engine opt-in — M3a runbook

## Scope and current limit

M3a provides persisted trusted configuration and explicit administrator operations only. It does **not** wire normal CLI queries or MCP tools to the managed engine. That integration belongs to M3b; operational status/recovery integration belongs to M3c. A stored registration is not proof of native execution, a prepared runtime, an indexed project, CLI/MCP parity, or a supported native release platform.

Default Python-only behavior remains unchanged. See [the existing operations runbook](operations-runbook.md) for the experimental explicit `sot engine` administration path and its known release/evidence limits.

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
sot --root /absolute/project engine disable
```

`register` requires `--store`, `--name`, `--runtime-root`, `--registry` and `--protocol`; `--generation` is optional and defaults to `initial`. `disable` and `config-status` do not require `--store`. `config-status` concerns persisted configuration, not a claim that a runtime is healthy or indexed.

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

Registration and enabled configuration loading fully validate the selected artifact and exact compatibility, with its digest pinned in the registration. Promoting a different artifact requires explicit re-registration; selection changes must not silently expand the existing authority. Persisted configuration survives process restarts, but does not itself enable ordinary CLI/MCP dispatch in M3a.

## Migration and indexing

Existing explicit engine administration does not itself create a trusted registration or enable ordinary CLI/MCP managed dispatch. Preserve the existing store, registry and runtime namespaces while reviewing the administrator binding.

Artifact import and selection remain separate explicit operations. The existing runbook documents `import`, `promote`, `doctor` and `status`; none should be treated as proof that the project index is current. Runtime operations require the explicit runtime-root, registry, protocol and generation contract documented there.

Only explicit `sync` requests indexing. Configuration loading and query paths must not create global configuration/directories, prepare a runtime, index the repository or write an evidence ledger. M3a registration is configuration administration, not index preparation. M3b must establish these guarantees for ordinary CLI/MCP dispatch; this document does not claim that wiring already exists.

## Disable, preservation and recovery

Run `sot --root /absolute/project engine disable` to mark the project's registration `enabled: false`. This works without opening or resolving a missing artifact or runtime, but paths and the configuration schema are still validated. Disable means withdraw the project's managed opt-in, not uninstall the artifact or delete data.

Corrupted configuration, including an invalid unrelated project entry, causes both loading and disabling to refuse without native execution. This deliberately avoids overwriting malformed authority; `disable` does not repair malformed JSON. An administrator must restore a known-good private configuration copy before retrying SOT `disable`. Restoration is an explicit administrator action, not an automatic recovery operation or a raw native command. Preserve repository files, SOT notes and evidence, installation bytes and all runtime/index namespaces. In M3a, ordinary CLI/MCP behavior is already unchanged; do not present disabling as an integrated dispatch transition that has been tested. The intended M3b behavior is return to builtin/default-off dispatch.

Do not delete `.sot`, reset indexes, or clear runtime namespaces as a disable procedure. Retained native indexes do not imply permission to execute them or compatibility with a different artifact.

For explicit engine administration, use only implemented SOT operations from the existing runbook:

- Missing or tampered artifacts: retain the store, verify administrator-controlled source/manifest, then explicitly import and promote.
- Timeout/quarantine: inspect `runtime-status`; retain the old namespace and choose a new explicit generation. Do not clear quarantine automatically or signal unrelated workers.
- Artifact rollback: select a previously verified digest using `rollback`; preserve notes, evidence and namespaces. A binary downgrade does not authorize opening a newer index. Select a compatible old generation or explicitly rebuild into a new namespace.
- Logical `uninstall` removes only the verified selected pointer, not registration or index data; it is not the opt-in disable procedure.

Never execute raw native `next_action` text as remediation. Native output is untrusted data, not an administrator command contract. Cross-version/schema index downgrade safety and normal CLI/MCP status/recovery integration remain separate milestones.
