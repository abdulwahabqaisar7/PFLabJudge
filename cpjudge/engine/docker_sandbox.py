"""Disposable Docker-container execution for the judge worker."""
from dataclasses import dataclass, field
from io import BytesIO
import math
from pathlib import Path, PurePosixPath
import shlex
import tarfile
import time
from typing import Dict, Iterable


class DockerSandboxError(RuntimeError):
    """Raised when the Docker-backed sandbox cannot safely run a command."""


@dataclass
class DockerRunResult:
    exit_code: int
    stdout: str
    stderr: str
    cpu_time: float
    memory_kb: int
    wall_time: float
    timed_out: bool = False
    cpu_limit_exceeded: bool = False
    out_of_memory: bool = False
    output_limit_exceeded: bool = False
    artifacts: Dict[str, bytes] = field(default_factory=dict)


class DockerSandbox:
    def __init__(self, image: str):
        if not image:
            raise ValueError("A sandbox image must be configured.")
        self.image = image

    def validate(self) -> None:
        """Fail at worker startup if the daemon or required image is unavailable."""
        try:
            import docker

            client = docker.from_env()
            try:
                client.ping()
                client.images.get(self.image)
            finally:
                client.close()
        except Exception as exc:
            raise DockerSandboxError(
                f"Docker sandbox is unavailable (image {self.image!r}): {exc}"
            ) from exc

    def run(
        self,
        command: Iterable[str],
        work_dir: str | Path,
        stdin: str = "",
        timeout: float = 10.0,
        cpu_limit_seconds: float = 10.0,
        memory_limit_bytes: int = 1024 * 1024 * 1024,
        output_limit_bytes: int = 64 * 1024 * 1024,
        nproc_limit: int = 32,
        collect_files: Iterable[str] = (),
    ) -> DockerRunResult:
        """Run one command in a fresh container and return bounded output."""
        import docker
        from docker.errors import APIError, ImageNotFound

        work_path = Path(work_dir).resolve()
        if not work_path.is_dir():
            raise DockerSandboxError(f"Sandbox work directory does not exist: {work_path}")
        if timeout <= 0 or cpu_limit_seconds <= 0 or memory_limit_bytes <= 0:
            raise ValueError("Sandbox time and memory limits must be positive.")
        if output_limit_bytes <= 0 or nproc_limit <= 0:
            raise ValueError("Sandbox output and process limits must be positive.")

        command = list(command)
        if not command or any(not isinstance(arg, str) for arg in command):
            raise ValueError("Sandbox command must contain string arguments.")
        remote_command = self._map_command(command, work_path)
        artifact_names = tuple(self._validate_relative_path(path) for path in collect_files)
        archive = self._build_archive(work_path, stdin.encode("utf-8"))
        wall_timeout = max(timeout, 0.1)
        cpu_soft = max(1, math.ceil(cpu_limit_seconds))
        cpu_hard = cpu_soft + 1
        output_limit = max(1, int(output_limit_bytes))
        file_size_limit = max(output_limit + 1, 65536)
        wrapper = self._build_wrapper(
            remote_command,
            cpu_soft,
            cpu_hard,
            file_size_limit,
            nproc_limit,
            memory_limit_bytes,
        )

        client = docker.from_env()
        work_volume = None
        staging_container = None
        container = None
        timed_out = False
        cpu_limit_exceeded = False
        out_of_memory = False
        execution_completed = False
        cpu_time = 0.0
        exit_code = -1
        try:
            client.ping()
            try:
                client.images.get(self.image)
            except ImageNotFound as exc:
                raise DockerSandboxError(
                    f"Required Docker sandbox image {self.image!r} is not available."
                ) from exc

            work_volume = client.volumes.create(
                driver="local",
                driver_opts={
                    "type": "tmpfs",
                    "device": "tmpfs",
                    "o": "size=128m,exec,nosuid,nodev,mode=1777",
                },
            )
            staging_container = client.containers.create(
                self.image,
                command=["/bin/sh", "-c", "sleep 30"],
                working_dir="/work",
                user="0:0",
                network_mode="none",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=2,
                mem_limit=64 * 1024 * 1024,
                volumes={work_volume.name: {"bind": "/work", "mode": "rw"}},
                detach=True,
                stdin_open=False,
                tty=False,
                labels={"cpjudge.sandbox": "true", "cpjudge.sandbox.staging": "true"},
            )
            staging_container.start()
            if not staging_container.put_archive("/work", archive):
                raise DockerSandboxError("Docker failed to stage files into the sandbox.")

            container = client.containers.create(
                self.image,
                command=["/bin/sh", "-c", wrapper],
                working_dir="/work",
                user="10001:10001",
                network_mode="none",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=nproc_limit,
                mem_limit=memory_limit_bytes,
                memswap_limit=memory_limit_bytes,
                tmpfs={"/tmp": "rw,nosuid,nodev,size=16m,mode=1777"},
                volumes={work_volume.name: {"bind": "/work", "mode": "rw"}},
                detach=True,
                stdin_open=False,
                tty=False,
                labels={"cpjudge.sandbox": "true"},
            )
            container.start()
            started = time.monotonic()
            staging_container.remove(force=True)
            staging_container = None

            deadline = started + wall_timeout
            while True:
                container.reload()
                state = container.attrs.get("State", {})
                status = state.get("Status")
                if status == "exited":
                    exit_code = int(state.get("ExitCode", -1))
                    out_of_memory = bool(state.get("OOMKilled", False))
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    try:
                        container.kill()
                    except APIError as exc:
                        if exc.status_code != 409:
                            raise
                    container.wait(timeout=5)
                    container.reload()
                    state = container.attrs.get("State", {})
                    exit_code = int(state.get("ExitCode", -1))
                    out_of_memory = bool(state.get("OOMKilled", False))
                    break
                if status != "running":
                    time.sleep(0.025)
                    continue
                completion_marker = self._read_container_file(
                    client,
                    container.id,
                    "/work/.cpjudge_exit",
                    16,
                    optional=True,
                )
                if completion_marker:
                    try:
                        exit_code = int(completion_marker.decode("ascii"))
                    except ValueError as exc:
                        raise DockerSandboxError("Sandbox produced an invalid exit status.") from exc
                    execution_completed = True
                    break
                stats = container.stats(stream=False)
                try:
                    usage_ns = stats["cpu_stats"]["cpu_usage"]["total_usage"]
                except (KeyError, TypeError) as exc:
                    raise DockerSandboxError(
                        "Docker Engine did not provide CPU usage for the sandbox container."
                    ) from exc
                cpu_time = max(cpu_time, usage_ns / 1_000_000_000)
                if cpu_time >= cpu_limit_seconds:
                    cpu_limit_exceeded = True
                    try:
                        container.kill()
                    except APIError as exc:
                        if exc.status_code != 409:
                            raise
                    container.wait(timeout=5)
                    container.reload()
                    state = container.attrs.get("State", {})
                    exit_code = int(state.get("ExitCode", -1))
                    out_of_memory = bool(state.get("OOMKilled", False))
                    break
                time.sleep(0.025)

            output_files_optional = timed_out or out_of_memory
            stdout = self._read_container_file(
                client,
                container.id,
                "/work/.cpjudge_stdout",
                file_size_limit,
                optional=output_files_optional,
            )
            stderr = self._read_container_file(
                client,
                container.id,
                "/work/.cpjudge_stderr",
                file_size_limit,
                optional=output_files_optional,
            )[:65536]
            metrics = self._read_container_file(
                client,
                container.id,
                "/work/.cpjudge_metrics",
                256,
                optional=True,
            )
            metrics_text = metrics.decode("ascii", errors="replace").strip().split()
            memory_kb = 0
            if len(metrics_text) >= 3:
                try:
                    cpu_time = max(
                        cpu_time,
                        float(metrics_text[0]) + float(metrics_text[1]),
                    )
                    memory_kb = int(metrics_text[2])
                except ValueError:
                    pass

            artifacts = {}
            for name in artifact_names:
                data = self._read_container_file(
                    client,
                    container.id,
                    f"/work/{name}",
                    128 * 1024 * 1024,
                    optional=True,
                )
                if data:
                    artifacts[name] = data

            if execution_completed:
                try:
                    container.kill()
                except APIError as exc:
                    if exc.status_code != 409:
                        raise
                container.wait(timeout=5)

            output_limit_exceeded = (
                len(stdout) > output_limit or exit_code in (25, 153, -25)
            )
            stdout = stdout[:output_limit + 1]
            return DockerRunResult(
                exit_code=exit_code,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                cpu_time=cpu_time,
                memory_kb=memory_kb,
                wall_time=time.monotonic() - started,
                timed_out=timed_out,
                cpu_limit_exceeded=cpu_limit_exceeded,
                out_of_memory=out_of_memory,
                output_limit_exceeded=output_limit_exceeded,
                artifacts=artifacts,
            )
        except DockerSandboxError:
            raise
        except Exception as exc:
            raise DockerSandboxError(f"Docker sandbox execution failed: {exc}") from exc
        finally:
            try:
                if container is not None:
                    try:
                        container.remove(force=True)
                    except APIError as exc:
                        if exc.status_code != 404:
                            raise
            finally:
                try:
                    if staging_container is not None:
                        try:
                            staging_container.remove(force=True)
                        except APIError as exc:
                            if exc.status_code != 404:
                                raise
                finally:
                    try:
                        if work_volume is not None:
                            work_volume.remove()
                    finally:
                        client.close()

    @staticmethod
    def _map_command(command: list[str], work_dir: Path) -> list[str]:
        mapped = []
        for arg in command:
            try:
                candidate = Path(arg)
                if candidate.is_absolute():
                    relative = candidate.resolve(strict=False).relative_to(work_dir)
                    arg = "/work/" + relative.as_posix()
            except (OSError, ValueError):
                pass
            mapped.append(arg)
        return mapped

    @staticmethod
    def _validate_relative_path(path: str) -> str:
        pure = PurePosixPath(path)
        if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
            raise ValueError(f"Sandbox artifact path must be relative: {path!r}")
        return pure.as_posix()

    @staticmethod
    def _build_archive(work_dir: Path, stdin: bytes) -> bytes:
        archive_data = BytesIO()
        total_size = 0
        staging_limit = 96 * 1024 * 1024
        with tarfile.open(fileobj=archive_data, mode="w") as archive:
            for path in sorted(work_dir.rglob("*")):
                relative = path.relative_to(work_dir)
                if relative.parts[0].startswith(".cpjudge_"):
                    continue
                if path.is_symlink():
                    raise DockerSandboxError(f"Sandbox input contains a symbolic link: {path}")
                if path.is_dir():
                    info = tarfile.TarInfo(relative.as_posix() + "/")
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    archive.addfile(info)
                    continue
                if not path.is_file():
                    raise DockerSandboxError(f"Unsupported sandbox input file: {path}")
                total_size += path.stat().st_size
                if total_size > staging_limit:
                    raise DockerSandboxError("Sandbox input exceeds the 96 MiB staging limit.")
                info = archive.gettarinfo(str(path), arcname=relative.as_posix())
                info.uid = info.gid = 10001
                info.uname = info.gname = ""
                with path.open("rb") as source:
                    archive.addfile(info, source)

            total_size += len(stdin)
            if total_size > staging_limit:
                raise DockerSandboxError("Sandbox input and stdin exceed the 96 MiB staging limit.")
            info = tarfile.TarInfo(".cpjudge_stdin")
            info.size = len(stdin)
            info.mode = 0o600
            info.uid = info.gid = 10001
            archive.addfile(info, BytesIO(stdin))
        return archive_data.getvalue()

    @staticmethod
    def _build_wrapper(
        command: list[str],
        cpu_soft: int,
        cpu_hard: int,
        output_limit: int,
        nproc_limit: int,
        memory_limit_bytes: int,
    ) -> str:
        command_text = shlex.join(command)
        return (
            "set +e; "
            f"/usr/bin/prlimit --cpu={cpu_soft}:{cpu_hard} "
            f"--fsize={output_limit}:{output_limit} "
            f"--nproc={nproc_limit}:{nproc_limit} "
            f"--as={memory_limit_bytes}:{memory_limit_bytes} "
            "/usr/bin/time -f '%U %S %M' -o /work/.cpjudge_metrics -- "
            f"/bin/sh -c {shlex.quote(command_text)} "
            "</work/.cpjudge_stdin "
            ">/work/.cpjudge_stdout 2>/work/.cpjudge_stderr; "
            "status=$?; "
            "printf '%s' \"$status\" >/work/.cpjudge_exit; "
            "sleep 30"
        )

    @staticmethod
    def _read_container_file(
        client,
        container_id: str,
        path: str,
        limit: int,
        optional: bool = False,
    ) -> bytes:
        from docker.errors import APIError

        try:
            chunks, _ = client.api.get_archive(container_id, path)
        except APIError as exc:
            if exc.status_code == 404 and optional:
                return b""
            if exc.status_code == 404:
                raise DockerSandboxError(f"Expected sandbox output file was not created: {path}") from exc
            raise
        archive_data = BytesIO(b"".join(chunks))
        with tarfile.open(fileobj=archive_data, mode="r:*") as archive:
            members = [member for member in archive.getmembers() if member.isfile()]
            if len(members) != 1 or members[0].size > limit:
                raise DockerSandboxError(f"Sandbox output file is invalid or exceeds {limit} bytes.")
            stream = archive.extractfile(members[0])
            if stream is None:
                return b""
            return stream.read(limit + 1)
