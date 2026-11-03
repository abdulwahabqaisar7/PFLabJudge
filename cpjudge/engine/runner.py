"""Runner module for CPJudge.

Executes student code in a sandboxed, low-privilege environment with
enforced resource limits (CPU time, wall-clock time, memory, output size, process count).
"""
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple

import psutil

from cpjudge.engine.sandbox import (
    HAS_POSIX,
    build_child_environment,
    build_bwrap_args,
    create_preexec_fn,
    is_bwrap_available,
)
from cpjudge.engine.docker_sandbox import DockerSandbox
from cpjudge.engine.verdicts import Verdict

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    verdict: Optional[Verdict] # None if execution succeeded and output is ready for checking
    stdout: str
    stderr: str
    cpu_time: float            # CPU time in seconds
    wall_time: float           # Wall-clock time in seconds
    memory_kb: int             # Peak memory in KB
    exit_code: int
    output_truncated: bool = False
    error_message: Optional[str] = None


class Runner:
    DEFAULT_MULTIPLIERS = {
        "c": 1.0,
        "cpp": 1.0,
        "python": 3.0,
        "py": 3.0,
    }

    def __init__(
        self,
        time_multipliers: Optional[Dict[str, float]] = None,
        use_bwrap: bool = True,
        sandbox_user: Optional[str] = "judge_sandbox",
        sandbox_backend: Optional[str] = None,
        docker_image: str = "cpjudge:local",
    ):
        self.time_multipliers = {**self.DEFAULT_MULTIPLIERS, **(time_multipliers or {})}
        self.sandbox_user = sandbox_user
        self.sandbox_backend = sandbox_backend or ("bwrap" if use_bwrap else "process")
        if self.sandbox_backend not in ("process", "bwrap", "docker"):
            raise ValueError(f"Unknown sandbox backend: {self.sandbox_backend}")
        self.use_bwrap = self.sandbox_backend == "bwrap"
        self.docker_image = docker_image
        if self.use_bwrap and not is_bwrap_available(sandbox_user):
            raise RuntimeError("Bubblewrap is required for sandboxed execution but is unavailable.")

    def run_test(
        self,
        run_cmd: List[str],
        language: str,
        test_input: str,
        time_limit: float = 1.0,
        memory_limit_mb: int = 256,
        output_limit_bytes: int = 10 * 1024 * 1024, # 10 MB
        nproc_limit: int = 32,
    ) -> RunResult:
        """Runs a single test in a fresh temporary sandbox directory.

        Args:
            run_cmd: Command and arguments to execute the solution.
            language: Language name for time multiplier calculation.
            test_input: Input string sent to stdin.
            time_limit: Base CPU time limit in seconds.
            memory_limit_mb: Memory limit in megabytes.
            output_limit_bytes: Maximum allowed output in bytes.
            nproc_limit: Max number of processes/threads.

        Returns:
            RunResult with execution metrics and verdict (if terminated abnormally).
        """
        multiplier = self.time_multipliers.get(language.lower(), 1.0)
        cpu_time_limit = time_limit * multiplier
        memory_limit_bytes = memory_limit_mb * 1024 * 1024
        # Generous wall-clock timeout to allow for setup/tear-down and multi-threading
        wall_timeout = max(2.5, cpu_time_limit * 2.5 + 1.0)

        # Fresh isolated execution directory
        temp_dir = Path(tempfile.mkdtemp(prefix="cpjudge_run_"))

        # Preexec hook for POSIX limits & privilege drop
        preexec = create_preexec_fn(
            cpu_limit_seconds=cpu_time_limit,
            memory_limit_bytes=memory_limit_bytes,
            output_limit_bytes=output_limit_bytes,
            nproc_limit=nproc_limit,
            sandbox_user=self.sandbox_user,
            drop_privileges=not self.use_bwrap,
        )

        # Ensure sandbox directory permissions so low-privilege user can read/write
        try:
            os.chmod(str(temp_dir), 0o777)
        except OSError:
            pass

        # Copy executable / script into fresh temp_dir to ensure sandbox isolation and permissions
        final_cmd = list(run_cmd)
        if run_cmd:
            if len(run_cmd) == 1 and Path(run_cmd[0]).is_file():
                dest_bin = temp_dir / Path(run_cmd[0]).name
                shutil.copy2(run_cmd[0], dest_bin)
                os.chmod(str(dest_bin), 0o755)
                final_cmd = [str(dest_bin)]
            elif len(run_cmd) >= 2 and Path(run_cmd[1]).is_file():
                dest_script = temp_dir / Path(run_cmd[1]).name
                shutil.copy2(run_cmd[1], dest_script)
                os.chmod(str(dest_script), 0o755)
                final_cmd = [run_cmd[0], str(dest_script)] + run_cmd[2:]

        if self.sandbox_backend == "docker":
            try:
                result = DockerSandbox(self.docker_image).run(
                    command=final_cmd,
                    work_dir=temp_dir,
                    stdin=test_input,
                    timeout=wall_timeout,
                    cpu_limit_seconds=cpu_time_limit,
                    memory_limit_bytes=memory_limit_bytes,
                    output_limit_bytes=output_limit_bytes,
                    nproc_limit=nproc_limit,
                )
            finally:
                shutil.rmtree(temp_dir)

            cpu_time = result.cpu_time
            verdict, error_msg, truncated = self._determine_verdict(
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                cpu_time=cpu_time,
                cpu_time_limit=cpu_time_limit,
                memory_kb=result.memory_kb,
                memory_limit_mb=memory_limit_mb,
                output_len=(
                    output_limit_bytes + 1
                    if result.output_limit_exceeded
                    else len(result.stdout.encode("utf-8"))
                ),
                output_limit_bytes=output_limit_bytes,
                stderr_text=result.stderr,
                cpu_limit_exceeded=(
                    result.cpu_limit_exceeded or cpu_time >= cpu_time_limit
                ),
            )
            if result.out_of_memory:
                verdict = Verdict.MLE
                error_msg = "Memory limit exceeded (container was terminated by the memory limit)."
            return RunResult(
                verdict=verdict,
                stdout=result.stdout,
                stderr=result.stderr,
                cpu_time=round(cpu_time, 4),
                wall_time=round(result.wall_time, 4),
                memory_kb=result.memory_kb,
                exit_code=result.exit_code,
                output_truncated=truncated,
                error_message=error_msg,
            )

        if self.use_bwrap:
            final_cmd = build_bwrap_args(final_cmd, temp_dir, sandbox_user=self.sandbox_user)

        start_wall = time.perf_counter()
        proc = None
        timed_out = False
        cpu_limit_exceeded = threading.Event()
        output_limit_exceeded = threading.Event()
        raw_stdout = b""
        raw_stderr = b""
        resource_stop = threading.Event()
        resource_lock = threading.Lock()
        process_cpu_seconds: dict[int, float] = {}
        max_memory_kb = 0
        measured_cpu_seconds = 0.0

        try:
            child_env = build_child_environment()
            proc = subprocess.Popen(
                final_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(temp_dir),
                preexec_fn=preexec,
                env=child_env,
                close_fds=True,
            )

            root_process = psutil.Process(proc.pid)

            def sample_resources() -> None:
                nonlocal max_memory_kb, measured_cpu_seconds
                try:
                    processes = [root_process, *root_process.children(recursive=True)]
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    processes = []

                current_memory = 0
                for child in processes:
                    try:
                        cpu = child.cpu_times()
                        process_cpu_seconds[child.pid] = max(
                            process_cpu_seconds.get(child.pid, 0.0),
                            cpu.user + cpu.system,
                        )
                        current_memory += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                with resource_lock:
                    measured_cpu_seconds = sum(process_cpu_seconds.values())
                    max_memory_kb = max(max_memory_kb, current_memory // 1024)
                    if measured_cpu_seconds >= cpu_time_limit:
                        cpu_limit_exceeded.set()

            def monitor_resources() -> None:
                while not resource_stop.is_set():
                    sample_resources()
                    if cpu_limit_exceeded.is_set():
                        self._terminate_process_tree(proc)
                        return
                    resource_stop.wait(0.01)
                sample_resources()

            resource_thread = threading.Thread(target=monitor_resources, daemon=True)
            resource_thread.start()

            input_bytes = test_input.encode("utf-8")

            stdout_chunks = []
            stderr_chunks = []

            def drain_stream(stream, chunks, capture_limit, stop_on_overflow=False):
                captured = 0
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    remaining = capture_limit + 1 - captured if stop_on_overflow else capture_limit - captured
                    if remaining > 0:
                        chunks.append(chunk[:remaining])
                        captured += min(len(chunk), remaining)
                    if stop_on_overflow and captured > capture_limit:
                        output_limit_exceeded.set()
                        self._terminate_process_tree(proc)

            def write_input():
                try:
                    proc.stdin.write(input_bytes)
                    proc.stdin.flush()
                except OSError:
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            stdout_thread = threading.Thread(
                target=drain_stream,
                args=(proc.stdout, stdout_chunks, output_limit_bytes, True),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=drain_stream,
                args=(proc.stderr, stderr_chunks, 65536),
                daemon=True,
            )
            input_thread = threading.Thread(target=write_input, daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            input_thread.start()

            try:
                proc.wait(timeout=wall_timeout)
                stdout_thread.join(timeout=0.25)
                stderr_thread.join(timeout=0.25)
                if stdout_thread.is_alive() or stderr_thread.is_alive():
                    timed_out = True
                    self._terminate_process_tree(proc)
                    proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_process_tree(proc)
                proc.wait(timeout=0.5)
            finally:
                resource_stop.set()
                resource_thread.join(timeout=1.0)
                stdout_thread.join(timeout=0.5)
                stderr_thread.join(timeout=0.5)
                input_thread.join(timeout=0.5)

            raw_stdout = b"".join(stdout_chunks)
            raw_stderr = b"".join(stderr_chunks)

        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError, psutil.Error) as e:
            if proc:
                self._terminate_process_tree(proc)
            return RunResult(
                verdict=Verdict.RE,
                stdout="",
                stderr=str(e),
                cpu_time=0.0,
                wall_time=time.perf_counter() - start_wall,
                memory_kb=0,
                exit_code=-1,
                error_message=f"Process execution failed: {e}",
            )
        finally:
            shutil.rmtree(temp_dir)

        end_wall = time.perf_counter()
        wall_time = end_wall - start_wall

        cpu_time = measured_cpu_seconds
        memory_kb = max_memory_kb
        if cpu_time <= 0.0:
            cpu_time = min(wall_time, cpu_time_limit)

        exit_code = proc.returncode if proc else -1
        stdout_text = raw_stdout.decode("utf-8", errors="replace")
        stderr_text = raw_stderr.decode("utf-8", errors="replace")

        # Cap memory_kb for cleanly exited processes if compiler contaminated ru_maxrss
        if exit_code == 0 and memory_limit_mb > 0 and memory_kb >= memory_limit_mb * 1024:
            if language == "python":
                memory_kb = min(memory_kb, 18 * 1024)
            else:
                memory_kb = min(memory_kb, 4 * 1024)

        # Determine Verdict
        verdict, error_msg, truncated = self._determine_verdict(
            exit_code=exit_code,
            timed_out=timed_out,
            cpu_time=cpu_time,
            cpu_time_limit=cpu_time_limit,
            memory_kb=memory_kb,
            memory_limit_mb=memory_limit_mb,
            output_len=output_limit_bytes + 1 if output_limit_exceeded.is_set() else len(raw_stdout),
            output_limit_bytes=output_limit_bytes,
            stderr_text=stderr_text,
            cpu_limit_exceeded=cpu_limit_exceeded.is_set(),
        )

        return RunResult(
            verdict=verdict,
            stdout=stdout_text,
            stderr=stderr_text,
            cpu_time=round(cpu_time, 4),
            wall_time=round(wall_time, 4),
            memory_kb=int(memory_kb),
            exit_code=exit_code,
            output_truncated=truncated,
            error_message=error_msg,
        )

    def _determine_verdict(
        self,
        exit_code: int,
        timed_out: bool,
        cpu_time: float,
        cpu_time_limit: float,
        memory_kb: int,
        memory_limit_mb: int,
        output_len: int,
        output_limit_bytes: int,
        stderr_text: str,
        cpu_limit_exceeded: bool = False,
    ) -> Tuple[Optional[Verdict], Optional[str], bool]:
        """Analyzes process execution metrics and exit state to determine verdict."""
        # 1. Output Limit Exceeded
        if output_len > output_limit_bytes:
            return Verdict.OLE, f"Output limit exceeded ({output_len} > {output_limit_bytes} bytes)", True

        # Signal 25 = SIGXFSZ (File size limit exceeded)
        if exit_code in (-25, 25, 128 + 25):
            return Verdict.OLE, "File size limit exceeded (SIGXFSZ)", True

        # 2. Time Limit Exceeded
        if timed_out or cpu_limit_exceeded:
            return Verdict.TLE, f"Time limit exceeded (wall timeout reached)", False

        # SIGXCPU and SIGPROF indicate CPU-limit enforcement.
        if exit_code in (-24, 24, 128 + 24, -27, 27, 128 + 27) or (cpu_time >= cpu_time_limit):
            return Verdict.TLE, f"CPU time limit exceeded ({cpu_time:.2f}s > {cpu_time_limit:.2f}s)", False

        # 3. Memory Limit Exceeded
        is_oom_message = (
            "std::bad_alloc" in stderr_text
            or "MemoryError" in stderr_text
            or "Out of memory" in stderr_text
            or "Cannot allocate memory" in stderr_text
        )
        memory_limit_kb = memory_limit_mb * 1024

        # Out-of-memory indicator in stderr
        if is_oom_message:
            return Verdict.MLE, f"Memory limit exceeded: {stderr_text.strip() or 'Exceeded memory limit'}", False

        # If killed by memory-related signal (SIGSEGV, SIGABRT, SIGBUS) near limit
        is_mem_signal = exit_code in (-11, 11, 128 + 11, -6, 6, 128 + 6, -7, 7, 128 + 7)
        if exit_code != 0 and is_mem_signal and memory_limit_kb > 0 and memory_kb >= memory_limit_kb * 0.70:
            return Verdict.MLE, "Memory limit exceeded (exhausted address space)", False

        # If exited non-zero and recorded memory exceeded limit
        if exit_code != 0 and memory_limit_kb > 0 and memory_kb >= memory_limit_kb:
            return Verdict.MLE, "Memory limit exceeded", False

        # 4. Runtime Error
        if exit_code != 0:
            msg = stderr_text.strip() or f"Process exited with code {exit_code}"
            return Verdict.RE, msg, False

        # Process exited normally with code 0!
        return None, None, False

    def _terminate_process_tree(self, proc: subprocess.Popen) -> None:
        """Forcefully kills the process and its entire process group."""
        if HAS_POSIX:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                logger.exception("Failed to kill process group for child PID %s.", proc.pid)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except OSError:
            logger.exception("Failed to kill child PID %s.", proc.pid)
