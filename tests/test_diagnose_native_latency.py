"""Isolated M1 runner checks: no native executable or provider is invoked."""

import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_native_latency.py"


@pytest.fixture
def runner(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("diagnose_latency_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = cast(Any, importlib.util.module_from_spec(spec))
    spec.loader.exec_module(module)
    binary = tmp_path / "native"
    binary.write_bytes(b"not an executable\n")
    registry = tmp_path / "registry.json"
    registry.write_text('{"records": []}')
    argv = [str(SCRIPT), "--exclusive-slot", "test-slot", "--binary", str(binary),
            "--sha256", hashlib.sha256(binary.read_bytes()).hexdigest(),
            "--native-commit", "a" * 40, "--registry", str(registry),
            "--protocol", "test-v1", "--output-dir", str(tmp_path / "output")]
    monkeypatch.setattr(module.sys, "argv", argv)
    monkeypatch.setattr(module.sys, "path", list(module.sys.path))
    monkeypatch.setattr(module.sys, "gettrace", lambda: None)
    monkeypatch.setattr(module.sys, "getprofile", lambda: None)
    monkeypatch.setattr(module, "os", SimpleNamespace(
        environ={}, chmod=module.os.chmod, cpu_count=module.os.cpu_count,
        walk=module.os.walk))
    monkeypatch.setattr(module.platform, "platform", lambda: "mock-platform")
    module.test_bounded_command = module.bounded_command
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=AssertionError("unmocked subprocess")))
    monkeypatch.setattr(module, "bounded_command", Mock(return_value={"status": "MOCKED"}))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    module.test_output = tmp_path / "output"
    module.test_registry = registry
    return module


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_output_is_never_overwritten(runner, tmp_path, kind):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("preserve me")
    if kind == "directory":
        runner.test_output.mkdir()
    elif kind == "file":
        runner.test_output.write_text("preserve me")
    else:
        runner.test_output.symlink_to(sentinel)
    with pytest.raises(FileExistsError):
        runner.main()
    assert sentinel.read_text() == "preserve me"
    if kind == "directory":
        assert list(runner.test_output.iterdir()) == []
    else:
        assert runner.test_output.read_text() == "preserve me"


@pytest.mark.parametrize("count", ["-1", "0", "1", "2"])
def test_requires_at_least_three_samples(runner, count, capsys):
    runner.sys.argv += ["--samples", count]
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert "at least three paired samples" in capsys.readouterr().err
    assert not runner.test_output.exists()


@pytest.mark.parametrize("hook", ["gettrace", "getprofile"])
def test_rejects_trace_and_profile_hooks(runner, monkeypatch, hook):
    monkeypatch.setattr(runner.sys, hook, lambda: object())
    with pytest.raises(SystemExit, match="Refusing traced/profiled"):
        runner.main()
    assert not runner.test_output.exists()


@pytest.mark.parametrize("key", ["COVERAGE_PROCESS_START", "MY_PROFILE", "PYTEST_CURRENT_TEST",
                                 "PYTHONPATH", "PYTHONSTARTUP", "coverage_lowercase"])
def test_rejects_instrumentation_environment_even_empty(runner, key):
    runner.os.environ[key] = ""
    with pytest.raises(SystemExit, match=key):
        runner.main()
    assert not runner.test_output.exists()


def test_rejects_optimized_python(runner, monkeypatch, capsys):
    monkeypatch.setattr(runner, "sys", SimpleNamespace(
        argv=runner.sys.argv, flags=SimpleNamespace(optimize=1),
        gettrace=lambda: None, getprofile=lambda: None))
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert "optimized Python disables diagnostic safety assertions" in capsys.readouterr().err
    assert not runner.test_output.exists()


def install_fake_native(runner, monkeypatch, tmp_path, *, bad_env=False, returncode=0):
    import sot_graph.providers as providers

    lab = tmp_path / "lab"
    lab.mkdir()
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **kwargs: str(lab))
    cache, transport_dir = lab / "cache", lab / "tmp"
    cache.mkdir()
    transport_dir.mkdir()
    (cache / "index").write_bytes(b"stable cache")

    class Profile:
        namespace = lab
        paths = {"cache": cache, "tmp": transport_dir}

        def status(self):
            return {"state": "READY"}

        def environment(self):
            env: dict[str, str] = dict.fromkeys(("HOME", "CBM_CACHE_DIR", "CBM_RUNTIME_DIR",
                                 "XDG_CONFIG_HOME", "TMPDIR"), str(lab))
            env.update(PATH="/usr/bin:/bin", TERM="dumb")
            if bad_env:
                env["SECRET"] = "must not reach native"
            return env

    class Runtime:
        def _guard_ready(self, **kwargs):
            return None

        def _config_fingerprint(self):
            return "config"

        def _gate(self, operation):
            return None

        def prepare(self):
            return SimpleNamespace(status="ok", error=None)

        def sync(self, repo):
            return self.prepare()

        def query(self, operation, arguments):
            transport = transport_dir / "args.json"
            transport.write_text(json.dumps(arguments))
            try:
                managed.run_command(["fake-native", operation, "--args-file", str(transport)],
                                    env=Profile().environment(), cwd=str(lab / "repo"))
            finally:
                transport.unlink()
            return self.prepare()

    class Store:
        def __init__(self, *args, **kwargs):
            pass

        _streaming_sha256 = staticmethod(lambda path: runner.digest_file(path))
        import_artifact = Mock()
        promote = Mock()
        resolve = Mock()

    managed = SimpleNamespace(ManagedNativeRuntime=Runtime)
    factory = Mock(side_effect=lambda *args, **kwargs:
                   SimpleNamespace(runtime=Runtime(), profile=Profile()))
    modules = {
        "artifacts": SimpleNamespace(ArtifactStore=Store, host_platform=lambda: "test"),
        "codebase_memory": SimpleNamespace(_file_sha256=runner.digest_file),
        "installation": SimpleNamespace(create_managed_installation=factory),
        "runtime": SimpleNamespace(ManagedRuntimeProfile=Profile),
        "managed": managed,
    }
    for name, module in modules.items():
        monkeypatch.setattr(providers, name, module, raising=False)
        monkeypatch.setitem(runner.sys.modules, f"sot_graph.providers.{name}", module)
    monkeypatch.setitem(runner.sys.modules, "sot_graph.providers.compatibility",
                        SimpleNamespace(CompatibilityRegistry=Mock,
                                        TestedCompatibilityRecord=SimpleNamespace(from_dict=Mock())))
    transports = []

    def command(argv, **kwargs):
        transports.append(Path(argv[argv.index("--args-file") + 1]).read_text())
        return SimpleNamespace(returncode=returncode, timed_out=False, stdout="{}", stderr="")

    native = Mock(side_effect=command)
    monkeypatch.setitem(runner.sys.modules, "sot_graph.proc", SimpleNamespace(run_command=native))
    return native, transports, factory


@pytest.mark.parametrize("samples", [3, 4])
def test_paired_samples_hashes_timestamps_and_atomic_output(runner, monkeypatch, tmp_path, capsys, samples):
    native, transports, factory = install_fake_native(runner, monkeypatch, tmp_path)
    runner.sys.argv += ["--samples", str(samples)]
    runner.os.environ.update(LANG="C", SECRET="not recorded", PYTHONMALLOC="malloc",
                             PYTHONHASHSEED="42", PYTHONWARNINGS="default")
    monkeypatch.setattr(runner.sys, "_xoptions", {"dev": True, "utf8": "1", "private": "secret"})
    runner.main()
    result_path = runner.test_output / "diagnostic-result.json"
    result = json.loads(result_path.read_text())
    assert result["status"] == "complete"
    assert result["verdict"] == "PENDING_ANALYSIS"
    assert result["n"] == len(result["samples"]) == samples
    assert native.call_count == 2 * samples
    assert factory.call_count == samples + 1
    assert all(transports[i] == transports[i + 1] for i in range(0, len(transports), 2))
    assert [row["sample"] for row in result["samples"]] == list(range(samples))
    assert result["registry_sha256"] == hashlib.sha256(runner.test_registry.read_bytes()).hexdigest()
    assert result["script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert result["binary_sha256"] == hashlib.sha256((tmp_path / "native").read_bytes()).hexdigest()
    assert result["cache_before"] == result["cache_after"] == {
        "cache/index": {"bytes": 12, "sha256": hashlib.sha256(b"stable cache").hexdigest()}}
    assert result["parent_env_allowlist"] == {
        "LANG": "C", "PYTHONMALLOC": "malloc", "PYTHONHASHSEED": "42", "PYTHONWARNINGS": "default"}
    assert result["python_xoptions"] == {"dev": True, "utf8": "1"}
    assert result["python_xoption_names"] == ["dev", "private", "utf8"]
    assert result["source_identity"]["git_head"] == {"status": "MOCKED"}
    assert [(row.get("sample"), row["boundary"]) for row in result["inventories"]] == [
        pair for sample in range(samples) for pair in [(sample, "before"), (sample, "after")]
    ] + [(None, "finally")]
    assert all(row["inventory"]["scratch"] == result["scratch"] for row in result["inventories"])
    assert all(row["inventory"]["coverage"].startswith("POINT_IN_TIME_PARTIAL")
               for row in result["inventories"])
    assert result["instrumentation_env"] == {}
    for event in result["events"]:
        utc_offset = datetime.fromisoformat(event["start_utc"]).utcoffset()
        assert utc_offset is not None
        assert utc_offset.total_seconds() == 0
        assert datetime.fromisoformat(event["end_utc"]) >= datetime.fromisoformat(event["start_utc"])
        assert event["end_monotonic_s"] >= event["start_monotonic_s"]
        assert event["wall_s"] == event["end_monotonic_s"] - event["start_monotonic_s"]
    assert list(runner.test_output.iterdir()) == [result_path]
    assert not (tmp_path / "lab/tmp/diagnostic-query.json").exists()
    assert json.loads(capsys.readouterr().out)["result"] == str(result_path)


@pytest.mark.parametrize("failure", ["hash", "environment", "direct"])
def test_failures_save_evidence_and_reraise(runner, monkeypatch, tmp_path, failure):
    native, _, _ = install_fake_native(runner, monkeypatch, tmp_path,
                                       bad_env=failure == "environment",
                                       returncode=1 if failure == "direct" else 0)
    if failure == "hash":
        runner.sys.argv[runner.sys.argv.index("--sha256") + 1] = "0" * 64
    with pytest.raises(AssertionError):
        runner.main()
    result = json.loads((runner.test_output / "diagnostic-result.json").read_text())
    assert result["status"] == "failed"
    assert result["error"].startswith("AssertionError:")
    assert "Traceback (most recent call last)" in result["traceback"]
    assert result["inventories"][-1]["boundary"] == "finally"
    receipt = json.loads((runner.test_output / "failure.json").read_text())
    assert receipt["error"] == result["error"]
    assert receipt["leftover_inventory"]["scratch"] == result["scratch"]
    assert receipt["events"] == result["events"]
    assert result["samples"] == []
    assert native.call_count == (2 if failure == "direct" else 0)
    assert not (tmp_path / "lab/tmp/diagnostic-query.json").exists()
    assert not (runner.test_output / "diagnostic-result.tmp").exists()


def test_cache_snapshot_excludes_symlinks(runner, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "index").write_bytes(b"abc")
    (cache / "link").symlink_to(cache / "index")
    snapshot = runner.fingerprint_cache(SimpleNamespace(namespace=tmp_path, paths={"cache": cache}))
    assert snapshot == {"cache/index": {"bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}}


def test_span_records_nested_failure_and_unwinds(runner):
    with pytest.raises(RuntimeError, match="failure"):
        with runner.span("outer"):
            with runner.span("inner"):
                raise RuntimeError("failure")
    assert runner.STACK == []
    assert [row["parent"] for row in runner.EVENTS] == [None, 0]
    assert all(row["exception"] == "RuntimeError" for row in runner.EVENTS)


@pytest.mark.parametrize("stage", ["import", "stat", "registry_digest"])
def test_post_mkdir_setup_failure_is_durable(runner, monkeypatch, tmp_path, stage):
    import builtins

    install_fake_native(runner, monkeypatch, tmp_path)
    if stage == "import":
        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "sot_graph.providers":
                raise ImportError("injected import failure")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_import)
        expected = ImportError
    elif stage == "stat":
        original_stat = Path.stat

        def fail_stat(path, *args, **kwargs):
            if path == tmp_path / "native" and runner.test_output.exists():
                raise OSError("injected stat failure")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", fail_stat)
        expected = OSError
    else:
        original_digest = runner.digest_file

        def fail_digest(path):
            if path == runner.test_registry:
                raise OSError("injected registry digest failure")
            return original_digest(path)

        monkeypatch.setattr(runner, "digest_file", fail_digest)
        expected = OSError
    with pytest.raises(expected, match="injected"):
        runner.main()
    receipt = json.loads((runner.test_output / "failure.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["context"] == {
        "output_dir": str(runner.test_output), "binary": str(tmp_path / "native"),
        "sha256": hashlib.sha256((tmp_path / "native").read_bytes()).hexdigest(),
        "native_commit": "a" * 40, "protocol": "test-v1",
        "registry": str(runner.test_registry), "slot": "test-slot", "samples": 3}
    assert "injected" in receipt["error"]
    assert "Traceback (most recent call last)" in receipt["traceback"]
    assert receipt["events"] == []
    assert not (runner.test_output / "diagnostic-result.json").exists()
    if stage == "import":
        assert receipt["leftover_inventory"]["scratch"] is None
    else:
        assert receipt["leftover_inventory"]["scratch"] == str(tmp_path / "lab")


def test_source_identity_hashes_python_and_records_git(runner, tmp_path):
    source = tmp_path / "src/sot_graph"
    source.mkdir(parents=True)
    (source / "a.py").write_bytes(b"value = 1\n")
    (source / "ignored.txt").write_text("not python")
    (source / "alias.py").symlink_to(source / "a.py")
    identity = runner.source_identity()
    assert identity["files"] == {
        "src/sot_graph/a.py": hashlib.sha256(b"value = 1\n").hexdigest()}
    assert identity["git_head"] == identity["git_status"] == {"status": "MOCKED"}
    assert runner.bounded_command.call_args_list[0].args[0] == [
        "git", "-C", str(tmp_path), "rev-parse", "HEAD"]
    assert runner.bounded_command.call_args_list[1].args[0] == [
        "git", "-C", str(tmp_path), "status", "--porcelain=v1", "--untracked-files=normal"]


@pytest.mark.parametrize("size", [65536, 65537])
def test_bounded_command_caps_output_and_sets_deadline(runner, monkeypatch, size):
    def command(argv, **kwargs):
        assert argv == ["mock-inspector"]
        assert kwargs["timeout"] == 5
        assert kwargs["check"] is False
        assert "shell" not in kwargs
        assert kwargs["stderr"] == runner.subprocess.STDOUT
        kwargs["stdout"].write(b"x" * size)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(runner.subprocess, "run", command)
    receipt = runner.test_bounded_command(["mock-inspector"])
    assert receipt == {"argv": ["mock-inspector"], "exit_code": 7,
                       "text": "x" * 65536, "truncated": size > 65536}


@pytest.mark.parametrize("kind", ["timeout", "missing"])
def test_bounded_command_inspection_failure_is_unknown(runner, monkeypatch, kind):
    error = (runner.subprocess.TimeoutExpired("mock", 5) if kind == "timeout"
             else FileNotFoundError("mock"))
    monkeypatch.setattr(runner.subprocess, "run", Mock(side_effect=error))
    assert runner.test_bounded_command(["mock"]) == {
        "argv": ["mock"], "status": "UNKNOWN", "error": type(error).__name__}


def test_inventory_is_scratch_scoped_and_does_not_follow_symlinks(runner, tmp_path):
    lab = tmp_path / "scratch"
    lab.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("private")
    (lab / "file").write_text("data")
    (lab / "link").symlink_to(outside, target_is_directory=True)
    receipt = runner.inventory(lab)
    assert {row["path"] for row in receipt["files"]} == {"file", "link"}
    assert receipt["files_truncated"] is False
    assert receipt["scratch"] == str(lab)
    utc_offset = datetime.fromisoformat(receipt["utc"]).utcoffset()
    assert utc_offset is not None
    assert utc_offset.total_seconds() == 0
    assert runner.bounded_command.call_args_list[0].args[0] == [
        "/bin/ps", "-axo", "pid=,ppid=,pgid=,comm="]
    assert runner.bounded_command.call_args_list[1].args[0] == [
        "/usr/sbin/lsof", "-nP", "+D", str(lab)]
    assert "UNKNOWN" in receipt["coverage"]


def test_inventory_without_scratch_skips_lsof(runner):
    receipt = runner.inventory(None)
    assert receipt["files"] == []
    assert receipt["scratch_open_files"]["status"] == "UNKNOWN"
    assert runner.bounded_command.call_count == 1


def test_inventory_bounds_file_rows(runner, tmp_path):
    for index in range(257):
        (tmp_path / f"entry-{index:03}").touch()
    receipt = runner.inventory(tmp_path)
    assert len(receipt["files"]) == 256
    assert receipt["files_truncated"] is True
