"""Frozen sequential synthetic four-cell measurement; never promotes provider."""
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]
E = Path(__file__).resolve().parent
protocol = json.loads((E / 'four-corpus-frozen.json').read_text())
lab = Path(json.loads((E / 'sot-lifecycle-e2e.json').read_text())['scratch'])
raw_path = E / 'four-corpus-v2-raw.json'
records = json.loads(raw_path.read_text()) if raw_path.exists() else []
completed = {(row['corpus'], row['ordinal']) for row in records}
for cell_index, corpus in enumerate(protocol['corpora']):
    repo = Path(corpus['root'])
    for name, digest in corpus['files'].items():
        assert hashlib.sha256((repo / name).read_bytes()).hexdigest() == digest
    base = [str(ROOT / '.venv/bin/python'), '-m', 'sot_graph.cli', '--root', str(repo)]
    native = ['engine', '--store', str(lab / 'store')]
    options = ['--runtime-root', str(repo.parent / ('r' + str(cell_index))),
               '--registry', str(lab / 'registry.json'), '--protocol', 'p4-release-2412e017-measured-v1']
    tasks = [('prepare', native + ['prepare'] + options)]
    for iteration in range(5):
        tasks += [('builtin-index', ['reconcile']), ('managed-index', native + ['sync'] + options)]
    for iteration in range(31):
        tasks += [('builtin-query', ['search', 'greet', '--no-jit', '--json']),
                  ('managed-query', native + ['search'] + options + ['greet'])]
    for ordinal, (kind, args) in enumerate(tasks):
        if (corpus['name'], ordinal) in completed:
            continue
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.monotonic()
        result = subprocess.run(['/usr/bin/time', '-l'] + base + args, cwd=ROOT,
                                capture_output=True, text=True, timeout=180)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        records.append({'corpus': corpus['name'], 'ordinal': ordinal, 'kind': kind,
            'seconds': time.monotonic() - start, 'exit_code': result.returncode,
            'cpu_user_seconds': after.ru_utime - before.ru_utime,
            'cpu_system_seconds': after.ru_stime - before.ru_stime,
            'stdout': result.stdout, 'stderr_time_and_diagnostics': result.stderr})
        (E / 'four-corpus-v2-raw.json').write_text(json.dumps(records, indent=2))
    print(corpus['name'], 'finished', flush=True)
(E / 'four-corpus-v2-exit.json').write_text(json.dumps({'exit_code': 0,
    'records': len(records), 'command_failures': sum(r['exit_code'] != 0 for r in records),
    'limitations': ['First index empty cache; later indices unchanged incremental, not 5 independent cold builds.',
                    'OS page cache not evicted.', 'Native daemon child resource accounting may not include detached descendants.',
                    'Synthetic cells do not certify language support.']}))
