#!/usr/bin/env python3
"""Offline Python-wheel surface audit; no native execution or live harness claim.

Requires an existing local wheel. Supply its runtime dependencies as repeated
--dependency-wheel arguments; nothing is downloaded. Output must not exist.
This audits Python packaging only, not native upgrade races or OS process trees.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sot_graph.proc import run_command  # noqa: E402


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob('*')) if p.is_file()
    }


def audit_wheel(wheel: Path) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        entries = [n for n in names if n.endswith('.dist-info/entry_points.txt')]
        if len(entries) != 1:
            raise ValueError('expected one entry-point manifest')
        parser = configparser.ConfigParser()
        parser.optionxform = lambda optionstr: optionstr
        parser.read_string(archive.read(entries[0]).decode())
        if not parser.has_section('console_scripts'):
            raise ValueError('missing public console entry points')
        if dict(parser['console_scripts']) != {'sotgraph': 'sot_graph.cli:main'}:
            raise ValueError('unexpected public console entry points')
        forbidden = [n for n in names if (
            n.startswith('engines/') or '.data/scripts/' in n
            or 'completion' in n.lower() or 'codebase-memory-mcp' in n.lower()
        )]
        if forbidden:
            raise ValueError(f'unexpected public/native payload: {forbidden}')
        return {'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                'entries': dict(parser['console_scripts']), 'files': names}


def run_audit(wheel: Path, output: Path, dependencies: list[Path]) -> dict[str, object]:
    wheel = wheel.resolve(strict=True)
    dependencies = [p.resolve(strict=True) for p in dependencies]
    metadata = audit_wheel(wheel)
    output.mkdir(parents=True, exist_ok=False)
    home = output / 'home'
    home.mkdir()
    tmp = output / 'tmp'
    tmp.mkdir()
    foreign = home / 'bin' / 'codebase-memory-mcp'
    foreign.parent.mkdir()
    foreign.write_text('#!/bin/sh\nexit 97\n')
    foreign.chmod(0o700)
    completion = home / '.config' / 'fish' / 'completions' / 'codebase-memory-mcp.fish'
    completion.parent.mkdir(parents=True)
    completion.write_text('# preexisting user completion\n')
    env = {
        'HOME': str(home), 'USERPROFILE': str(home),
        'XDG_CONFIG_HOME': str(home / '.config'),
        'XDG_DATA_HOME': str(home / '.local/share'),
        'XDG_CACHE_HOME': str(home / '.cache'),
        'XDG_RUNTIME_DIR': str(home / '.run'),
        'TMPDIR': str(tmp), 'TEMP': str(tmp), 'TMP': str(tmp),
        'PATH': str(foreign.parent) + os.pathsep + '/usr/bin:/bin',
        'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'PIP_CONFIG_FILE': os.devnull, 'PIP_NO_INDEX': '1',
        'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_NO_CACHE_DIR': '1',
    }
    before = snapshot(home)
    records = []
    report: dict[str, object] = {
        'scope': 'offline Python wheel; generated configs, NOT live harness/native matrix',
        'platform': platform.platform(), 'python': sys.version,
        'wheel': metadata, 'commands': records, 'home_before': before,
        'native_engine_digest': None,
        'blocked': ['native upgrades/races/rollback', 'live harness loading',
                    'OS process/network/listener audit', 'upstream native installer execution',
                    'descendants that escape their process group'],
    }

    def run(args: list[str], cwd: Path) -> None:
        record: dict[str, object] = {'argv': args, 'state': 'started'}
        records.append(record)
        (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
        result = run_command(args, cwd=cwd, env=env, timeout_seconds=120,
                             max_output_bytes=2 * 1024 * 1024)
        record.update({'exit': result.returncode, 'stdout': result.stdout,
                       'stderr': result.stderr, 'timed_out': result.timed_out,
                       'truncated': result.truncated, 'error': result.error,
                       'state': 'finished'})
        if result.returncode != 0 or result.timed_out or result.truncated or result.error:
            raise RuntimeError(f'command failed ({result.returncode}): {args[0]}')

    try:
        runtime = output / 'venv'
        # Run venv creation in a child too: ensurepip inherits only scratch env.
        run([sys.executable, '-m', 'venv', str(runtime)], output)
        bindir = runtime / ('Scripts' if os.name == 'nt' else 'bin')
        python = bindir / ('python.exe' if os.name == 'nt' else 'python')
        before_bin = set(p.name for p in bindir.iterdir())
        run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps',
             *map(str, dependencies), str(wheel)], output)
        assert snapshot(home) == before, 'install mutated user HOME/config'
        added = set(p.name for p in bindir.iterdir()) - before_bin
        assert not any('cbm' in n.lower() or 'codebase-memory' in n.lower() for n in added)
        run([str(python), '-m', 'pip', 'check'], output)
        run([str(python), '-c',
             'import importlib.metadata as m; d=m.distribution("sot-graph"); '
             'print(d.read_text("RECORD"))'], output)
        run([str(bindir / ('sotgraph.exe' if os.name == 'nt' else 'sotgraph')), '--help'], output)
        report['bin_added'] = sorted(added)
        for harness in ('omp', 'opencode', 'antigravity', 'claude', 'zcode'):
            root = output / 'workspaces' / harness
            root.mkdir(parents=True)
            command = [str(bindir / ('sotgraph.exe' if os.name == 'nt' else 'sotgraph')),
                       'setup', '--harness', harness, '--workspace-only']
            run(command, root)
            first = snapshot(root)
            run(command, root)
            assert snapshot(root) == first, f'non-idempotent {harness} setup'
            report[harness] = first
        assert snapshot(home) == before, 'workspace setup mutated HOME/config'
        run([str(python), '-m', 'pip', 'uninstall', '--yes', 'sot-graph'], output)
        assert snapshot(home) == before, 'uninstall mutated user HOME/config'
        assert not (bindir / ('sotgraph.exe' if os.name == 'nt' else 'sotgraph')).exists()
        report['result'] = 'PASS_SCOPED'
    except Exception as exc:
        report['result'] = 'BLOCKED'
        report['failure'] = str(exc)
        raise
    finally:
        report['home_after'] = snapshot(home)
        (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--dependency-wheel', type=Path, action='append', default=[])
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run_audit(args.wheel, args.output_dir.resolve(), args.dependency_wheel)


if __name__ == '__main__':
    main()
