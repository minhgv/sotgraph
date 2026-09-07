"""Public admin surface exercises real persisted configuration, no native runs."""
import json
import sys

import pytest

from sot_graph.cli import main
from sot_graph.providers import trusted_config as config
from test_trusted_managed_config import trusted_lab as _trusted_lab

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="managed artifact/runtime gate is POSIX-only by design (artifacts.py:75,155)")

trusted_lab = _trusted_lab


def test_cli_register_status_disable_persist_without_native(trusted_lab, capsys):
    lab = trusted_lab
    prefix = ["--root", str(lab.repo), "engine"]
    assert main(prefix + ["--store", str(lab.store.root), "--name", lab.artifact.name,
                          "register", "--runtime-root", str(lab.runtime),
                          "--registry", str(lab.registry), "--protocol", "cbm-cli-json-v1"]) == 0
    assert lab.path.exists()
    assert config.load_managed_installation(lab.repo, config_path=lab.path) is not None
    for action in ("config-status", "config-doctor"):
        assert main(prefix + [action]) == 1
        status = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert status["schema_version"] == 2
        assert status["status"] == "enabled"
        assert status["registration"] == "enabled"
        assert status["runtime_status"] == "UNINITIALIZED"
        assert status["reason"] == "runtime_uninitialized"
        assert status["ready"] is False
        assert status["query_permission"] == "not_assessed"
        assert status["remediation"] == ["sotgraph engine prepare", "sotgraph engine probe", "sotgraph engine sync"]
    assert main(prefix + ["disable"]) == 0
    assert config.load_managed_installation(lab.repo, config_path=lab.path) is None
    assert not lab.runtime.exists()
    assert not (lab.repo / ".sot").exists()


def test_cli_default_off_does_not_create_config(trusted_lab, capsys):
    lab = trusted_lab
    prefix = ["--root", str(lab.repo), "engine"]
    assert main(prefix + ["disable"]) == 0
    assert main(prefix + ["config-status"]) == 0
    assert main(prefix + ["config-doctor"]) == 0
    status = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert status["schema_version"] == 2
    assert status["status"] == "disabled"
    assert status["registration"] == "missing"
    assert status["ready"] is False
    assert status["query_permission"] == "not_assessed"
    assert not lab.path.exists()
    lab.path.write_bytes(b"{corrupt authority")
    lab.path.chmod(0o600)
    for action in ("config-status", "config-doctor"):
        assert main(prefix + [action]) == 2
        status = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert status["schema_version"] == 2
        assert status["status"] == "refused"
        assert status["reason"] == "config_refused"
        assert status["ready"] is False
        assert status["query_permission"] == "not_assessed"
        assert lab.path.read_bytes() == b"{corrupt authority"
    assert not lab.runtime.exists()
    assert not (lab.repo / ".sot").exists()


def test_cli_register_rejects_real_protocol_mismatch(trusted_lab):
    lab = trusted_lab
    assert main(["--root", str(lab.repo), "engine", "--store", str(lab.store.root),
                 "register", "--runtime-root", str(lab.runtime),
                 "--registry", str(lab.registry), "--protocol", "artifacts-v1"]) == 2
    assert not lab.path.exists()
    assert not lab.runtime.exists()


def test_cli_cannot_select_trusted_config_path(trusted_lab):
    lab = trusted_lab
    with pytest.raises(SystemExit):
        main(["--root", str(lab.repo), "engine", "config-status",
              "--config-path", str(lab.repo / "managed.json")])
    assert not lab.path.exists()
