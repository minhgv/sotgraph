"""Explicit local SOT artifact administration; pinned trusted bootstrap only.

No PATH discovery, no unpinned downloads, no spawn. Bootstrap delegates to
``providers.bootstrap`` which fetches ONLY pin-manifest sources (master plan D1).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .artifacts import ArtifactError, ArtifactStore
from .runtime import ManagedRuntimeError
from sot_graph.locking import LockBusy


def add_parser(subparsers):
    parser = subparsers.add_parser('engine', help='Explicit local engine artifact administration (experimental)')
    parser.add_argument('--store', help='Private absolute store outside the repository (defaults to ~/.sotgraph/engine-store for bootstrap/mcp-probe)')
    parser.add_argument('--name', default='codebase-memory')
    operations = parser.add_subparsers(dest='engine_action', required=True)
    install = operations.add_parser('import', help='Verify and stage an explicit local artifact; never activate automatically')
    install.add_argument('--source', required=True)
    install.add_argument('--manifest', required=True)
    boot = operations.add_parser('bootstrap', help='Fetch, verify, and promote the pinned engine artifact (trusted bootstrap)')
    boot.add_argument('--source', help='Override pin source with a local artifact file or https URL (digest must still match the pin)')
    operations.add_parser('mcp-probe', help='MCP stdio handshake probe against the promoted engine artifact')
    for action in ('promote', 'rollback', 'uninstall'):
        operation = operations.add_parser(action, help='Select an already verified digest; preserve all data')
        operation.add_argument('--digest', required=True)
    operations.add_parser('status', help='Verify selected artifact without spawning an engine')
    operations.add_parser('doctor', help='Report artifact identity and experimental limitations')
    operations.add_parser('disable', help='Disable trusted project opt-in; preserve all stored data')
    operations.add_parser('config-status', help='Read trusted binding and runtime readiness without starting the engine')
    operations.add_parser('config-doctor', help='Alias for read-only trusted operational config-status')
    for action in ('register', 'prepare', 'probe', 'sync', 'search', 'runtime-status'):
        operation = operations.add_parser(action, help='Explicit managed SOT operation (experimental)')
        operation.add_argument('--runtime-root', required=True)
        operation.add_argument('--registry', required=True, help='Trusted administrator operation evidence JSON outside repository')
        operation.add_argument('--protocol', required=True)
        operation.add_argument('--generation', default='initial')
        if action == 'search':
            operation.add_argument('query')
            operation.add_argument('--limit', type=int, default=20)


def verified_search(outcome, root, limit):
    """Normalize only the measured table schema, then reverify every subject."""
    from sot_graph.assurance.orchestrator import cbm_candidates_from_outcome
    payload = outcome.payload
    failure = {'status': 'abstained', 'freshness': 'unknown', 'results': [],
               'next_action': 'Use sotgraph search for builtin results or explicit sotgraph engine sync.'}
    if not outcome.ok or not isinstance(payload, dict):
        return failure
    if payload.get('cols') != ['qn', 'label', 'file', 'lines', 'rank'] or not isinstance(payload.get('rows'), list):
        return failure
    for row in payload['rows']:
        if not isinstance(row, list) or len(row) != 5:
            return failure
        name, kind, path, span, rank = row
        if not all(isinstance(value, str) and value for value in (name, kind, path, span)):
            return failure
        match = re.fullmatch(r'(\d+)-(\d+)', span)
        if not match or int(match[1]) < 1 or int(match[2]) < int(match[1]):
            return failure
    candidates, truncated, gap = cbm_candidates_from_outcome(
        outcome, 'search_symbols', 'codebase-memory', repo_root=root)
    return {'status': 'ok', 'results': candidates[:limit], 'freshness': 'unknown',
            'scope_completeness': 'bounded', 'snapshot_bound': False,
            'truncated': truncated, 'gap': gap,
            'limitations': ['Existing SOT orchestrator normalization and trust ceilings apply.']}


def run(args, root):
    try:
        action = args.engine_action
        if action in ('register', 'disable', 'config-status', 'config-doctor'):
            from .trusted_config import (
                disable_managed_installation, managed_config_status,
                register_managed_installation,
            )
            if action == 'register':
                if not args.store:
                    raise ValueError('register requires --store')
                installation = register_managed_installation(
                    root, store_path=args.store, artifact_name=args.name,
                    runtime_root=args.runtime_root, registry_path=args.registry,
                    native_protocol_id=args.protocol, generation=args.generation)
                response = {'schema_version': 1, 'status': 'enabled', 'enabled': True,
                            'artifact_digest': installation.artifact.digest,
                            'lifecycle': 'not_started'}
            elif action == 'disable':
                changed = disable_managed_installation(root)
                response = {'schema_version': 1, 'status': 'disabled',
                            'enabled': False, 'changed': changed, 'lifecycle': 'not_started'}
            else:
                response = managed_config_status(root)
            print(json.dumps(response, sort_keys=True))
            if action in ('config-status', 'config-doctor'):
                if response['status'] == 'refused':
                    return 2
                return 0 if response['status'] == 'disabled' or response['ready'] else 1
            return 0
        if action in ('bootstrap', 'mcp-probe'):
            from .bootstrap import bootstrap_engine, default_store_root
            store_root = args.store or os.fspath(default_store_root())
            if action == 'bootstrap':
                receipt = bootstrap_engine(
                    repo_path=root, store_root=store_root,
                    source_override=getattr(args, 'source', None))
                print(json.dumps(receipt, sort_keys=True))
                return 0 if receipt['status'] in ('promoted', 'already') else 2
            from .engine_mcp import probe_engine_mcp
            probe_store = ArtifactStore(store_root, repo_path=root)
            descriptor = probe_store.resolve(args.name)
            if descriptor is None:
                raise ValueError('no promoted artifact; run engine bootstrap first')
            probe = probe_engine_mcp(descriptor.executable, store_root=store_root,
                                     engine_name=args.name)
            print(json.dumps(probe, sort_keys=True))
            return 0 if probe.get('status') == 'ok' else 2
        if not args.store:
            raise ValueError('engine operation requires --store')
        store = ArtifactStore(args.store, repo_path=root)
        if action in ('prepare', 'probe', 'sync', 'search', 'runtime-status'):
            from .base import IndexRequest, SymbolRequest
            from .compatibility import CompatibilityRegistry, TestedCompatibilityRecord, normalize_protocol_id
            from .installation import create_managed_installation
            path = Path(args.registry).resolve(strict=True)
            if path.is_relative_to(Path(root).resolve()) or path.stat().st_size > 262144:
                raise ValueError('registry must be bounded trusted administration outside repository')
            payload = json.loads(path.read_text())
            registry = CompatibilityRegistry()
            protocol = normalize_protocol_id(args.protocol)
            records = payload['records'] if isinstance(payload, dict) else payload
            digests = {}
            selected = store.resolve(args.name)
            if selected is None:
                raise ValueError('no promoted artifact')
            for item in records:
                record = TestedCompatibilityRecord.from_dict(item)
                if (record.provider_name != 'codebase-memory'
                        or record.artifact_sha256 != selected.digest
                        or (record.engine_commit or '').strip().lower() != selected.engine_commit.lower()
                        or record.protocol_compatibility_id != protocol):
                    continue
                if record.operation in digests:
                    raise ValueError('duplicate operation evidence')
                registry.register(record)
                digests[record.operation] = record.fixture_digest
            installation = create_managed_installation(
                store, artifact_name=args.name, repo_path=root,
                runtime_root=args.runtime_root, registry=registry,
                operation_fixture_digests=digests, native_protocol_id=protocol,
                generation=args.generation)
            if action == 'prepare':
                result = installation.runtime.prepare()
            elif action == 'probe':
                result = installation.provider.probe(root)
            elif action == 'sync':
                from sot_graph.cli import default_db_path
                from sot_graph.db import Database
                from sot_graph.locking import WriteLock
                from .codebase_memory import CodebaseMemoryProvider
                # Same provider atomic outcome/ledger path and project lock as
                # providers sync; never attach a writable ledger to read queries.
                with WriteLock(str(Path(root) / '.sot/write.lock'), timeout_ms=60000):
                    database = Database(getattr(args, 'db', None) or default_db_path(root))
                    try:
                        provider = CodebaseMemoryProvider(
                            command=(installation.artifact.executable,), db=database,
                            exact_context=installation.exact_context,
                            managed_runtime=installation.runtime)
                        result = provider.index(IndexRequest(repo_root=root))
                    finally:
                        database.close()
            elif action == 'search':
                if not 1 <= args.limit <= 100:
                    raise ValueError('limit must be 1..100')
                result = installation.provider.search_symbols(SymbolRequest(repo_root=root, query=args.query, limit=args.limit))
            else:
                result = installation.profile.status()
            if action == 'search':
                response = verified_search(result, root, args.limit)
            else:
                response = result if isinstance(result, dict) else asdict(result)
            print(json.dumps({'schema_version': 1, 'operation': action, 'result': response,
                              'platform_support': 'experimental'}, default=str, sort_keys=True))
            if action == 'probe':
                return 0 if response.get('installed') is True and response.get('healthy') is True else 1
            status = response.get('status', response.get('state'))
            return 0 if status in ('ok', 'READY', 'available', 'success') else 1
        if action == 'import':
            path = Path(args.manifest)
            if path.stat().st_size > 16384:
                raise ValueError('artifact manifest exceeds 16 KiB')
            descriptor = store.import_artifact(args.source, path.read_bytes())
        elif action == 'uninstall':
            descriptor = store.uninstall(args.name, args.digest)
        elif action in ('promote', 'rollback'):
            descriptor = store.promote(args.name, args.digest)
        else:
            descriptor = store.resolve(args.name)
        print(json.dumps({
            'schema_version': 1, 'status': 'ok' if descriptor else 'missing',
            'artifact': asdict(descriptor) if descriptor else None,
            'compatibility': 'not_assessed_by_artifact_administration',
            'lifecycle': 'not_started', 'platform_support': 'experimental',
            'snapshot': 'not_assessed',
            'next_action': 'Use sotgraph engine import then sotgraph engine promote for explicit local installation.' if not descriptor else None,
            'limitations': ['Artifact selection does not enable query dispatch.',
                            'Rollback preserves runtime namespaces, notes and evidence; it does not downgrade an index.'],
        }, default=str, sort_keys=True))
        return 0 if descriptor else 1
    except (ArtifactError, ManagedRuntimeError, LockBusy, sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        # Never turn native or untrusted manifest text into executable remediation.
        print(json.dumps({'schema_version': 1, 'status': 'refused',
                          'next_action': 'Use sotgraph engine doctor with a trusted private store; verify local manifest and digest.'}))
        return 2
