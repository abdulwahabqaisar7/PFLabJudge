import io
from pathlib import Path
import sys
import tarfile
import types

import pytest

from cpjudge.engine.checker import Checker, CheckerType
from cpjudge.engine.compiler import Compiler
from cpjudge.engine.docker_sandbox import DockerRunResult, DockerSandbox
from cpjudge.engine.runner import Runner
from cpjudge.engine.verdicts import Verdict


class FakeAPIError(Exception):
    status_code = 404


class FakeContainer:
    id = "sandbox-container"

    def __init__(self):
        self.archive = None
        self.removed = False
        self.killed = False
        self.attrs = {"State": {"Status": "running", "ExitCode": 0, "OOMKilled": False}}

    def put_archive(self, path, archive):
        self.archive = (path, archive)
        return True

    def start(self):
        pass

    def reload(self):
        pass

    def kill(self):
        self.killed = True
        self.attrs["State"]["Status"] = "exited"

    def wait(self, timeout=None):
        return {"StatusCode": 0}

    def remove(self, force=False):
        self.removed = force


class FakeVolume:
    name = "sandbox-work-volume"

    def __init__(self):
        self.removed = False

    def remove(self):
        self.removed = True


class FakeVolumes:
    def __init__(self):
        self.volume = FakeVolume()
        self.create_options = None

    def create(self, **options):
        self.create_options = options
        return self.volume


class FakeDockerClient:
    def __init__(self):
        self.staging_container = FakeContainer()
        self.container = FakeContainer()
        self.create_options = []
        self.closed = False
        self.containers = self
        self.images = self
        self.api = self
        self.volumes = FakeVolumes()

    def ping(self):
        return True

    def get(self, image):
        return image

    def create(self, image, **options):
        self.create_options.append({"image": image, **options})
        return (self.staging_container if len(self.create_options) == 1
                else self.container)

    def get_archive(self, container_id, path):
        files = {
            "/work/.cpjudge_stdout": b"student output\n",
            "/work/.cpjudge_stderr": b"",
            "/work/.cpjudge_metrics": b"0.12 0.03 2048",
            "/work/.cpjudge_exit": b"0",
            "/work/solution.out": b"compiled binary",
        }
        name = path.rsplit("/", 1)[-1]
        data = files.get(path)
        if data is None:
            raise FakeAPIError("not found")
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        return [stream.getvalue()], {}

    def close(self):
        self.closed = True


def install_fake_docker(monkeypatch, client):
    docker_module = types.ModuleType("docker")
    docker_module.from_env = lambda: client
    errors_module = types.ModuleType("docker.errors")
    errors_module.APIError = FakeAPIError
    errors_module.ImageNotFound = type("ImageNotFound", (Exception,), {})
    docker_module.errors = errors_module
    monkeypatch.setitem(sys.modules, "docker", docker_module)
    monkeypatch.setitem(sys.modules, "docker.errors", errors_module)


def test_docker_sandbox_runs_with_restrictions_and_collects_artifacts(tmp_path, monkeypatch):
    script = tmp_path / "solution.py"
    script.write_text("print('student output')", encoding="utf-8")
    client = FakeDockerClient()
    install_fake_docker(monkeypatch, client)

    result = DockerSandbox("cpjudge:local").run(
        command=["python3", str(script)],
        work_dir=tmp_path,
        stdin="input\n",
        timeout=2.0,
        cpu_limit_seconds=1.5,
        memory_limit_bytes=128 * 1024 * 1024,
        output_limit_bytes=4096,
        nproc_limit=12,
        collect_files=["solution.out"],
    )

    staging_options, options = client.create_options
    assert options["network_mode"] == "none"
    assert options["read_only"] is True
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["user"] == "10001:10001"
    assert options["pids_limit"] == 12
    assert options["mem_limit"] == 128 * 1024 * 1024
    assert options["tmpfs"] == {"/tmp": "rw,nosuid,nodev,size=16m,mode=1777"}
    assert options["volumes"] == {
        "sandbox-work-volume": {"bind": "/work", "mode": "rw"}
    }
    assert client.volumes.create_options == {
        "driver": "local",
        "driver_opts": {
            "type": "tmpfs",
            "device": "tmpfs",
            "o": "size=128m,exec,nosuid,nodev,mode=1777",
        },
    }
    assert staging_options["volumes"] == options["volumes"]
    assert staging_options["network_mode"] == "none"
    assert staging_options["cap_drop"] == ["ALL"]
    assert "/var/run/docker.sock" not in repr(options)
    assert "/work/solution.py" in options["command"][2]
    assert staging_options["command"] == ["/bin/sh", "-c", "sleep 30"]
    assert options["stdin_open"] is False
    assert options["command"][2].endswith("sleep 30")
    assert client.staging_container.archive[0] == "/work"
    with tarfile.open(fileobj=io.BytesIO(client.staging_container.archive[1]), mode="r:") as archive:
        assert archive.extractfile("solution.py").read() == b"print('student output')"
        assert archive.extractfile(".cpjudge_stdin").read() == b"input\n"
    assert result.stdout == "student output\n"
    assert result.cpu_time == pytest.approx(0.15)
    assert result.memory_kb == 2048
    assert result.artifacts["solution.out"] == b"compiled binary"
    assert client.staging_container.removed is True
    assert client.container.killed is True
    assert client.container.removed is True
    assert client.volumes.volume.removed is True
    assert client.closed is True


def test_docker_sandbox_rejects_artifact_path_traversal(tmp_path, monkeypatch):
    client = FakeDockerClient()
    install_fake_docker(monkeypatch, client)
    (tmp_path / "solution.py").write_text("pass", encoding="utf-8")

    try:
        DockerSandbox("cpjudge:local").run(
            command=["python3", str(tmp_path / "solution.py")],
            work_dir=tmp_path,
            collect_files=["../outside"],
        )
    except ValueError as exc:
        assert "must be relative" in str(exc)
    else:
        raise AssertionError("Expected artifact path traversal to be rejected")


def test_docker_sandbox_marks_and_truncates_excess_output(tmp_path, monkeypatch):
    client = FakeDockerClient()
    install_fake_docker(monkeypatch, client)
    (tmp_path / "solution.py").write_text("pass", encoding="utf-8")

    result = DockerSandbox("cpjudge:local").run(
        command=["python3", str(tmp_path / "solution.py")],
        work_dir=tmp_path,
        output_limit_bytes=5,
    )

    assert result.output_limit_exceeded is True
    assert result.stdout == "studen"


def test_compiler_uses_docker_for_compilation_and_python_syntax_checks(tmp_path, monkeypatch):
    calls = []

    def fake_run(sandbox, **kwargs):
        calls.append(kwargs)
        if kwargs.get("collect_files"):
            return DockerRunResult(
                exit_code=0,
                stdout="",
                stderr="",
                cpu_time=0.1,
                memory_kb=2048,
                wall_time=0.2,
                artifacts={"solution.out": b"compiled"},
            )
        return DockerRunResult(
            exit_code=0,
            stdout="",
            stderr="",
            cpu_time=0.01,
            memory_kb=1024,
            wall_time=0.1,
        )

    monkeypatch.setattr("cpjudge.engine.compiler.DockerSandbox.run", fake_run)
    compiler = Compiler(sandbox_backend="docker")

    c_result = compiler.compile("int main(void) { return 0; }", "c", tmp_path)
    python_result = compiler.compile("print('ok')", "python", tmp_path)

    assert c_result.success is True
    assert (tmp_path / "solution.out").read_bytes() == b"compiled"
    assert python_result.success is True
    assert calls[0]["command"][0] == "gcc"
    assert calls[1]["command"][1:3] == ["-m", "py_compile"]


def test_runner_and_custom_checker_use_docker(tmp_path, monkeypatch):
    calls = []
    checker_inputs = []

    def fake_run(sandbox, **kwargs):
        calls.append(kwargs)
        if any(Path(arg).name == "checker.py" for arg in kwargs["command"]):
            checker_inputs.append(
                kwargs["work_dir"].joinpath("input.txt").read_text(encoding="utf-8")
            )
        return DockerRunResult(
            exit_code=0,
            stdout="42\n",
            stderr="",
            cpu_time=0.01,
            memory_kb=1024,
            wall_time=0.1,
        )

    monkeypatch.setattr("cpjudge.engine.runner.DockerSandbox.run", fake_run)
    monkeypatch.setattr("cpjudge.engine.checker.DockerSandbox.run", fake_run)
    program = tmp_path / "program"
    program.write_text("placeholder", encoding="utf-8")

    run_result = Runner(sandbox_backend="docker").run_test(
        [str(program)],
        "c",
        "",
        time_limit=1.0,
        memory_limit_mb=64,
        output_limit_bytes=1024,
    )
    checker_script = tmp_path / "checker.py"
    checker_script.write_text("pass", encoding="utf-8")
    check_result = Checker(
        checker_type=CheckerType.CUSTOM,
        custom_checker_path=str(checker_script),
        sandbox_backend="docker",
    ).check("input", "42", "42")

    assert run_result.verdict is None
    assert run_result.stdout == "42\n"
    assert check_result.verdict == Verdict.AC
    assert calls[0]["stdin"] == ""
    assert calls[1]["timeout"] == 5.0
    assert checker_inputs == ["input"]
