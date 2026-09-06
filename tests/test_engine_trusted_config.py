"""Public admin surface exercises real persisted configuration, no native runs."""
import json

import pytest

from sot_graph.cli import main
from sot_graph.providers import trusted_config as config
from test_trusted_managed_config import trusted_lab as _trusted_lab

trusted_lab = _trusted_lab


def test_cli_register_status_disable_persist_without_native(trusted_lab, capsys):
    lab = trusted_lab
    prefix = ["--root", str(lab.repo), "engine"]
    assert main(prefix + ["--store", str(lab.store.root), "--name", lab.artifact.name,
                          "register", "--runtime-root", str(lab.runtime),
                          "--registry", str(lab.registry), "--protocol", "cbm-cli-json-v1"]) == 0
    assert lab.path.exists()
    assert config.load_managed_installation(lab.repo, config_path=lab.path) is not None
    assert main(prefix + ["config-status"]) == 0
    assert isinstance(json.loads(capsys.readouterr().out.splitlines()[-1]), dict)
    assert main(prefix + ["disable"]) == 0
    assert config.load_managed_installation(lab.repo, config_path=lab.path) is None
    assert not lab.runtime.exists()
    assert not (lab.repo / ".sot").exists()


def test_cli_default_off_does_not_create_config(trusted_lab):
    lab = trusted_lab
    prefix = ["--root", str(lab.repo), "engine"]
    assert main(prefix + ["disable"]) == 0
    assert main(prefix + ["config-status"]) in (0, 1)
    assert not lab.path.exists()
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
