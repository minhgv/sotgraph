"""SUR12 supplemental scratch administrator lifecycle (never ordinary live opt-in).

Freeze this script and the review protocol before an explicitly approved exclusive
run. No slot means a BLOCKED receipt and no native execution. This is NOT M5
real-version evidence, ordinary CLI/MCP persisted dispatch, or lifetime isolation
proof. No account-home injection, security monkeypatches, global kills, or adoption.
Shared process runner may kill only its own spawned process group on timeout/cap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import time

# Also run this driver with -B; helper imports must not mutate checkout caches.
sys.dont_write_bytecode = True
# These helpers have no import-time instrumentation; never call diagnostic.main.
from diagnose_native_latency import bounded_command, digest_file, inventory, source_identity  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sot_graph.proc import run_command  # noqa: E402

CLI = """import sys,json,dataclasses
sys.path.insert(0,sys.argv.pop(1))
from sot_graph.providers import admin
original_verified_search=admin.verified_search
def private_diagnostic(outcome, root, limit):
 # Harness-only structured receipt: captured in exclusive mode-0600 stderr.
 # Public CLI redaction and production query authority remain unchanged.
 print(json.dumps({'private_search_outcome':dataclasses.asdict(outcome)},default=str),file=sys.stderr)
 return original_verified_search(outcome,root,limit)
admin.verified_search=private_diagnostic
from sot_graph.cli import main
raise SystemExit(main())
"""
CONFIG = """import sys,json
sys.path.insert(0,sys.argv.pop(1))
from sot_graph.providers.trusted_config import register_managed_installation,load_managed_installation,disable_managed_installation
repo,store,runtime,registry,protocol,generation,config,action=sys.argv[1:]
if action=='register':
 register_managed_installation(repo,store_path=store,artifact_name='codebase-memory',runtime_root=runtime,registry_path=registry,native_protocol_id=protocol,generation=generation,config_path=config)
 installation=load_managed_installation(repo,config_path=config)
 if installation is None: raise RuntimeError('explicit config reload failed')
 print(json.dumps({'status':'ok','artifact_digest':installation.artifact.digest,'authority':'explicit scratch library config only'}))
else:
 disable_managed_installation(repo,config_path=config)
 if load_managed_installation(repo,config_path=config) is not None: raise RuntimeError('disable failed')
 print(json.dumps({'status':'disabled','authority':'explicit scratch library config only'}))
"""


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'registry', 'output-dir'):
        p.add_argument('--' + name, type=Path, required=True)
    for name in ('sha256', 'native-commit', 'protocol'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--exclusive-slot')
    p.add_argument('--second-binary', type=Path)
    p.add_argument('--second-sha256')
    return p


def validate(args):
    for value, size in ((args.sha256, 64), (args.native_commit, 40)):
        if not re.fullmatch('[0-9a-f]{' + str(size) + '}', value):
            raise ValueError('invalid lowercase SHA/commit identity')
    if not args.protocol.strip():
        raise ValueError('protocol must be nonempty')
    if bool(args.second_binary) != bool(args.second_sha256):
        raise ValueError('second binary and SHA must be supplied together')
    if args.second_sha256 and (not re.fullmatch('[0-9a-f]{64}', args.second_sha256)
                               or args.second_sha256 == args.sha256):
        raise ValueError('second artifact must have a distinct verified SHA')


def private_write(path, data):
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def snapshot_files(root):
    return {str(p.relative_to(root)): digest_file(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


class Runner:
    def __init__(self, args):
        self.args = args
        self.out = args.output_dir.resolve()
        self.lab = None
        self.env = None
        self.receipt = {'schema_version': 1, 'status': 'RUNNING', 'commands': [],
                        'exclusive_slot': args.exclusive_slot,
                        'persisted_cli_mcp': 'BLOCKED: isolated OS account authority required',
                        'm5': 'NOT_PROVEN: distinct bytes alone do not prove real versions',
                        'lifetime': 'BLOCKED: point-in-time inventory only; no descendant lifetime instrumentation',
                        'scope': 'supplemental explicit scratch administrator CLI and trusted-config API'}

    def save(self):
        temporary = self.out / 'receipt.tmp'
        temporary.write_text(json.dumps(self.receipt, indent=2) + '\n')
        os.chmod(temporary, 0o600)
        temporary.replace(self.out / 'receipt.json')

    def command(self, label, argv):
        number = len(self.receipt['commands'])
        row = {'label': label, 'argv': argv, 'returncode': None}
        self.receipt['commands'].append(row)
        self.save()
        start = time.monotonic()
        try:
            if self.lab is None:
                raise RuntimeError('scratch not allocated')
            result = run_command(argv, cwd=self.lab / 'repo', env=self.env,
                                 timeout_seconds=180, max_output_bytes=1048576)
            row.update(returncode=result.returncode, timed_out=result.timed_out,
                       truncated=result.truncated, error=result.error,
                       output_encoding='UTF-8 replacement decoded by shared runner')
            private_write(self.out / f'{number:02d}.stdout', result.stdout.encode('utf-8'))
            private_write(self.out / f'{number:02d}.stderr', result.stderr.encode('utf-8'))
        except Exception as exc:
            row['error'] = type(exc).__name__
            raise
        finally:
            row['elapsed_s'] = time.monotonic() - start
            row['outputs'] = {suffix: {'file': f'{number:02d}.{suffix}',
                                      'sha256': digest_file(self.out / f'{number:02d}.{suffix}'),
                                      'bytes': (self.out / f'{number:02d}.{suffix}').stat().st_size}
                              for suffix in ('stdout', 'stderr')
                              if (self.out / f'{number:02d}.{suffix}').exists()}
            self.save()
        if row['returncode'] != 0 or row.get('timed_out') or row.get('truncated') or row.get('error'):
            raise RuntimeError(f'{label} failed; unsafe dependent steps not attempted')

    def cli(self, label, *args):
        if self.lab is None:
            raise RuntimeError('scratch not allocated')
        self.command(label, [sys.executable, '-I', '-B', '-c', CLI, str(ROOT / 'src'),
                             '--root', str(self.lab / 'repo'), *map(str, args)])

    def engine(self, action, *args):
        if self.lab is None:
            raise RuntimeError('scratch not allocated')
        self.cli(action, 'engine', '--store', self.lab / 'store', action, *args)

    def managed(self, action, generation):
        if self.lab is None:
            raise RuntimeError('scratch not allocated')
        # Native compatibility evidence covers the fixed wire limit of 20.
        extra = ['greet', '--limit', '20'] if action == 'search' else []
        self.engine(action, *extra, '--runtime-root', self.lab / 'r',
                    '--registry', self.lab / 'evidence/registry.json',
                    '--protocol', self.args.protocol, '--generation', generation)

    def config(self, action, generation):
        if self.lab is None:
            raise RuntimeError('scratch not allocated')
        self.command('explicit-config-' + action,
                     [sys.executable, '-I', '-B', '-c', CONFIG, str(ROOT / 'src'),
                      str(self.lab / 'repo'), str(self.lab / 'store'),
                      str(self.lab / 'r'), str(self.lab / 'evidence/registry.json'),
                      self.args.protocol, generation, str(self.lab / 'config/managed.json'), action])

    def execute(self):
        self.out.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.save()
        try:
            validate(self.args)
            self.receipt['source_before'] = source_identity()
            self.receipt['script_sha256'] = digest_file(Path(__file__))
            self.receipt['inputs'] = {key: str(value) for key, value in vars(self.args).items()}
            if not self.args.exclusive_slot or not self.args.exclusive_slot.strip():
                self.receipt['status'] = 'BLOCKED'
                self.receipt['reason'] = 'explicit exclusive-slot approval required; no scratch/native commands run'
                return 2
            registry_path = self.args.registry.resolve(strict=True)
            if registry_path.is_relative_to(ROOT) or registry_path.stat().st_size > 262144:
                raise ValueError('registry must be bounded and outside source repository')
            registry_bytes = registry_path.read_bytes()
            records = json.loads(registry_bytes)
            records = records['records'] if isinstance(records, dict) else records
            artifacts = [(self.args.binary, self.args.sha256)]
            if self.args.second_binary:
                artifacts.append((self.args.second_binary, self.args.second_sha256))
            for binary, digest in artifacts:
                if digest_file(binary.resolve(strict=True)) != digest:
                    raise ValueError('binary SHA mismatch')
            self.lab = Path(tempfile.mkdtemp(prefix='sl-', dir='/tmp')).resolve()
            os.chmod(self.lab, 0o700)
            # Keep the canonical runtime root within Darwin's native socket budget.
            for name in ('repo', 'home', 'store', 'r', 'config', 'evidence', 'tmp', 'oldCBM'):
                (self.lab / name).mkdir(mode=0o700)
            private_write(self.lab / 'repo/alpha.py', b'def greet(name):\n    return "hello " + name\n')
            private_write(self.lab / 'repo/user-notes.txt', b'preserve user evidence\n')
            private_write(self.lab / 'oldCBM/sentinel', b'never adopt or remove legacy state\n')
            private_write(self.lab / 'evidence/registry.json', registry_bytes)
            private_write(self.out / 'registry.json', registry_bytes)
            self.receipt['registry_sha256'] = hashlib.sha256(registry_bytes).hexdigest()
            self.receipt['scratch'] = str(self.lab)
            self.receipt['inventory_before'] = inventory(self.lab)
            self.receipt['listeners_before'] = bounded_command(['/usr/sbin/lsof', '-nP', '-iTCP', '-sTCP:LISTEN'])
            sentinel = snapshot_files(self.lab / 'oldCBM')
            self.receipt['legacy_before'] = sentinel
            self.receipt['fixture_before'] = snapshot_files(self.lab / 'repo')
            self.env = {'HOME': str(self.lab / 'home'), 'XDG_CONFIG_HOME': str(self.lab / 'config'),
                        'TMPDIR': str(self.lab / 'tmp'), 'PATH': '/usr/bin:/bin', 'TERM': 'dumb',
                        'CBM_CACHE_DIR': str(self.lab / 'r'), 'CBM_RUNTIME_DIR': str(self.lab / 'r')}
            # Authorized builtin index write is confined to this newly allocated repository.
            self.cli('builtin-reconcile', 'reconcile')
            for index, (binary, digest) in enumerate(artifacts):
                commits = {r.get('engine_commit') for r in records if r.get('artifact_sha256') == digest}
                if len(commits) != 1:
                    raise ValueError('registry must identify exactly one commit per artifact')
                commit = commits.pop()
                if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
                    raise ValueError('registry commit is not a full identity')
                if index == 0 and commit != self.args.native_commit:
                    raise ValueError('registry/native commit mismatch')
                manifest = {'schema_version': 1, 'name': 'codebase-memory', 'digest': digest,
                            'platform': sys.platform + '-' + {'aarch64': 'arm64', 'amd64': 'x86_64'}.get(platform.machine().lower(), platform.machine().lower()),
                            'protocol': 'artifacts-v1', 'engine_commit': commit}
                data = json.dumps(manifest, sort_keys=True).encode()
                path = self.lab / f'evidence/manifest-{index}.json'
                private_write(path, data)
                private_write(self.out / f'manifest-{index}.json', data)
                self.engine('import', '--source', binary.resolve(), '--manifest', path)
                self.engine('promote', '--digest', digest)
                generation = 'sur12-' + str(index)
                self.config('register', generation)
                for action in ('prepare', 'probe', 'sync', 'search', 'runtime-status'):
                    self.managed(action, generation)
            before_recovery = snapshot_files(self.lab / 'repo')
            self.engine('rollback', '--digest', self.args.sha256)
            self.config('register', 'sur12-0')
            for action in ('prepare', 'probe', 'search', 'runtime-status'):
                self.managed(action, 'sur12-0')
            self.config('disable', 'sur12-0')
            before_uninstall = snapshot_files(self.lab / 'repo')
            # Current parser only deactivates the exact selected digest; staged
            # artifacts and runtime namespaces remain deliberately preserved.
            self.engine('uninstall', '--digest', self.args.sha256)
            if snapshot_files(self.lab / 'repo') != before_uninstall:
                raise RuntimeError('uninstall altered repository files')
            if snapshot_files(self.lab / 'oldCBM') != sentinel:
                raise RuntimeError('legacy sentinel changed')
            self.receipt['preservation'] = {'before_recovery': before_recovery,
                                            'before_uninstall': before_uninstall,
                                            'after_uninstall': snapshot_files(self.lab / 'repo'),
                                            'legacy_sentinel': sentinel}
            self.receipt['retention'] = 'Scratch, staged artifacts (including optional second generation), runtime namespaces and evidence intentionally retained; uninstall only deactivates selected digest.'
            self.receipt['rollback_kind'] = 'distinct-artifact' if len(artifacts) == 2 else 'same-artifact-selection-only'
            self.receipt['status'] = 'SUPPLEMENTAL_PASS'
            return 0
        except Exception as exc:
            self.receipt.update(status='FAILED', error=f'{type(exc).__name__}: {exc}')
            return 1
        finally:
            if self.lab is not None:
                self.receipt['inventory_after'] = inventory(self.lab)
                self.receipt['listeners_after'] = bounded_command(['/usr/sbin/lsof', '-nP', '-iTCP', '-sTCP:LISTEN'])
                self.receipt['legacy_after'] = snapshot_files(self.lab / 'oldCBM')
                fixtures = self.receipt.get('fixture_before', {})
                self.receipt['fixtures_preserved'] = all(
                    (self.lab / 'repo' / name).is_file()
                    and digest_file(self.lab / 'repo' / name) == digest
                    for name, digest in fixtures.items())
                if (self.receipt.get('legacy_before') != self.receipt['legacy_after']
                        or not self.receipt['fixtures_preserved']):
                    self.receipt['status'] = 'FAILED'
            self.receipt['source_after'] = source_identity()
            before = self.receipt.get('source_before', {}).get('files')
            self.receipt['source_drift'] = 'NOT_ASSESSED' if before is None else before != self.receipt['source_after']['files']
            if self.receipt['source_drift'] is True:
                self.receipt['status'] = 'FAILED'
            self.save()


def main(argv=None):
    runner = Runner(parser().parse_args(argv))
    result = runner.execute()
    return 1 if runner.receipt['status'] == 'FAILED' else result


if __name__ == '__main__':
    raise SystemExit(main())
