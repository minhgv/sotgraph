"""Global hermetic test policy.

The suite must never touch the network or spawn services. Engine auto-bootstrap
(``_maybe_bootstrap_engine`` on ``sotgraph setup``) is therefore disabled by
default for every test; tests that exercise bootstrap explicitly call
``sot_graph.providers.bootstrap`` functions directly, which ignore this policy.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_engine_auto_bootstrap(monkeypatch):
    monkeypatch.setenv("SOT_ENGINE_BOOTSTRAP", "off")
