"""Fresh version-bound release acceptance; historical harness/pins are immutable.

Reuse the measured-operation capture protocol, not its historical registry.
The harness creates a fresh registry from this artifact's actual operation output.
Run with the repository venv; no native binary discovery or downloads.
"""
from pathlib import Path
import hashlib
import runpy
import sys

HERE = Path(__file__).resolve().parent
BINARY = Path('/tmp/sot-p0-scratch/rel-extract/codebase-memory-mcp')
ARCHIVE = Path('/tmp/sot-p0-scratch/cbm-darwin-arm64-v0.10.8.tar.gz')
PIN = '2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf'
ARCHIVE_PIN = '9bd840dfb3ec7eaef4f310382057adaa5b0e904df883104d03ffcf39836afd07'


def main():
    for path, expected in ((BINARY, PIN), (ARCHIVE, ARCHIVE_PIN)):
        digest = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
        if digest != expected:
            raise SystemExit(f'Identity verification failed: {path.name}')
    module = runpy.run_path(str(HERE.parent / 'p2-managed-acceptance-harness.py'),
                            run_name='historical_protocol_reuse')
    runner = module['main']
    runner.__globals__.update(PINNED_SHA=PIN, EVIDENCE_DIR=HERE,
                             PROTO='p4-release-2412e017-measured-v1',
                             NATIVE_BUDGET_S=240.0)
    sys.argv = [str(Path(__file__)), '--binary', str(BINARY)]
    return runner()


if __name__ == '__main__':
    raise SystemExit(main())
