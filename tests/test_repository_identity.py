"""Repository migration invariants, without changing public package identity."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repository_identity', ROOT / 'scripts/check_repository_identity.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_repository_identity_audit():
    assert audit.check() == []


def test_reference_classifier_preserves_package_identity():
    assert audit.LEGACY.search('https://github.com/minhgv/' + 'sot-graph.git')
    assert audit.LEGACY.search('/Users/developer/code/' + 'sot-graph/src')
    assert audit.LEGACY.search('/home/developer/' + 'sot-graph/src')
    for text in ['pip install sot-graph', 'import sot_graph', '.config/sot-graph/managed.json',
                 'https://github.com/minhgv/sotgraph', 'sotgraph --help']:
        assert audit.LEGACY.search(text) is None


def test_native_credentials_are_explicit_and_ephemeral():
    workflow = yaml.safe_load((ROOT / '.github/workflows/native-experimental.yml').read_text())
    steps = workflow['jobs']['darwin-arm64-experimental']['steps']
    assert 'exit 1' in steps[0]['run']
    assert steps[1]['with']['persist-credentials'] is False
    assert steps[1]['with']['token'] == '${{ secrets.NATIVE_SOURCE_READ_TOKEN }}'
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        if path.name == 'native-experimental.yml':
            continue
        config = yaml.safe_load(path.read_text())
        for job in config['jobs'].values():
            for step in job.get('steps', []):
                assert not step.get('with', {}).get('submodules')


def test_metadata_and_action_use_new_repository():
    metadata = (ROOT / 'pyproject.toml').read_text()
    assert 'name = "sot-graph"' in metadata
    assert 'sotgraph = "sot_graph.cli:main"' in metadata
    assert metadata.count('https://github.com/minhgv/sotgraph') == 4
    action = (ROOT / '.github/actions/diff-impact/action.yml').read_text()
    assert '[ "${{ github.repository }}" = "minhgv/sotgraph" ]' in action
    assert 'SOURCE="checkout"' in action


def test_quality_audits_project_and_ci_smokes_built_artifact():
    gates = (ROOT / 'scripts/quality_gates.sh').read_text()
    assert 'pip-audit --path "$SITE_PACKAGES" --skip-editable' in gates
    workflow = (ROOT / '.github/workflows/ci.yml').read_text()
    assert workflow.count("'--no-project', '--isolated', '--with'") == 2
    smoke = (ROOT / 'scripts/ci_smoke.py').read_text()
    assert smoke.count('"--no-project", "--isolated"') == 2
    assert '"mcp>=1.3,<2"' in smoke


def test_new_console_contract_and_old_usage_detection():
    import importlib.metadata
    import subprocess
    import sys

    entries = importlib.metadata.distribution('sot-graph').entry_points
    assert {e.name: e.value for e in entries if e.group == 'console_scripts'} == {
        'sotgraph': 'sot_graph.cli:main'
    }
    command = ROOT / '.venv/bin/sotgraph'
    if command.exists():
        assert not command.with_name('sot').exists()
    result = subprocess.run([sys.executable, '-m', 'sot_graph', '--help'],
                            capture_output=True, text=True, check=True)
    assert 'usage: sotgraph' in result.stdout
    assert audit.LEGACY_CLI.search('sot' + ' reconcile')
    for value in ['.sot/sot.db', 'sot://node/id', 'sot_search', 'pip install sot-graph']:
        assert audit.LEGACY_CLI.search(value) is None
