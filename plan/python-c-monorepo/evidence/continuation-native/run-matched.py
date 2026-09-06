"""Sequential exploratory matched corpus measurement; no promotion claim."""
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
lab = Path(json.loads((EVIDENCE / 'sot-lifecycle-e2e.json').read_text())['scratch'])
repo = lab / 'repo'
base = [str(ROOT / '.venv/bin/python'), '-m', 'sot_graph.cli', '--root', str(repo)]
commands = {
    'builtin': ['search', 'greet', '--no-jit', '--json'],
    'managed': ['engine', '--store', str(lab / 'store'), 'search',
                '--runtime-root', str(lab / 'rt'), '--registry', str(lab / 'registry.json'),
                '--protocol', 'p4-release-2412e017-measured-v1', 'greet'],
}
protocol = {'n': 30, 'warmup': 1, 'corpus': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in repo.glob('*.py')}, 'commands': commands,
    'scope': 'Single synthetic Python cell, same frozen source, source-verifying SOT paths.',
    'cache': 'OS warm, no eviction', 'ordering': 'sequential alternating',
    'exclusions': ['No full/index/incremental distribution', 'No RSS/CPU measurement',
                   'No four-language quality matrix', 'No promotion evidence'],
    'thresholds': {'p50_improvement_min': 0.2, 'p95_regression_max': 0.1, 'rss_regression_max': 0.2}}
(EVIDENCE / 'matched-v2-protocol.json').write_text(json.dumps(protocol, indent=2))
rows = []
for iteration in range(31):
    for provider, arguments in commands.items():
        start = time.monotonic()
        result = subprocess.run(base + arguments, cwd=ROOT, capture_output=True, text=True, timeout=90)
        rows.append({'iteration': iteration, 'warmup': iteration == 0, 'provider': provider,
                     'seconds': time.monotonic() - start, 'exit_code': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr})
    (EVIDENCE / 'matched-v2-raw.json').write_text(json.dumps(rows, indent=2))
summary = {}
for provider in commands:
    samples = [r for r in rows if r['provider'] == provider and not r['warmup']]
    values = sorted(r['seconds'] for r in samples)
    summary[provider] = {'n': len(samples), 'p50': statistics.median(values), 'p95': values[28],
                         'failures': sum(r['exit_code'] != 0 for r in samples)}
(EVIDENCE / 'matched-v2-summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary))
