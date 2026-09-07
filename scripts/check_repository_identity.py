"""Check tracked repository identities; historical exceptions bind exact bytes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY = re.compile(
    r"minhgv/" + r"sot-graph(?![\w-])|"
    r"(?:/Users/|/home/)[^\s\"\'<>`]+/" + r"sot-graph(?![\w-])|"
    r"\bcd " + r"sot-graph\b"
)

# Match executable usage only, not .sot storage, sot:// resources, or sot_* tools.
LEGACY_CLI = re.compile(
    r"(?<![\w.-])" + r"so" + r"t" + r"(?=\s+(?:search|explore|reconcile|setup|providers|engine|mcp|--help|--version)\b)|"
    r"[\"']" + r"so" + r"t" + r"[\"']|(?:/bin/|bin/)" + r"so" + r"t" + r"(?![\w.-])"
)
ACTIVE_CLI_ROOTS = ('src/', 'scripts/', '.github/', '.claude/', '.gemini/',
                    '.omp/', '.opencode/', '.zcode/', 'bin/')


def check(root=ROOT):
    """Return failures, using exact-file hashes rather than directory exclusions."""
    actual = subprocess.check_output(
        ['git', '-C', str(root), 'rev-parse', '--show-toplevel'], text=True
    ).strip()
    if Path(actual).resolve() != root.resolve():
        return ['Refusing to audit a different git root']
    exceptions = json.loads((root / 'scripts/repository_reference_exceptions.json').read_text())
    files = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '-z'], text=True
    ).split('\0')
    errors = []
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if name in exceptions:
            if hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != exceptions[name]['sha256']:
                errors.append(f'{name}: historical exception changed; review provenance')
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if LEGACY.search(line):
                errors.append(f'{name}:{number}: active legacy repository reference')
            if name.startswith(ACTIVE_CLI_ROOTS) and LEGACY_CLI.search(line):
                errors.append(f'{name}:{number}: obsolete executable usage')
    for name in exceptions:
        if name not in files:
            errors.append(f'{name}: stale exception')
    return errors


if __name__ == '__main__':
    failures = check()
    print('\n'.join(failures[:30]) if failures else 'Repository identity audit passed')
    sys.exit(bool(failures))
