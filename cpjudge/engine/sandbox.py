"""Sandboxing and isolation module for CPJudge.

Enforces:
- CPU time limit (RLIMIT_CPU)
- Memory limit (RLIMIT_AS)
- File output limit (RLIMIT_FSIZE)
- Max processes / thread limit (RLIMIT_NPROC)
- Prevention of core dumps (RLIMIT_CORE = 0)
- Execution in fresh isolated directory as low-privilege user
- Process group isolation (os.setsid) for clean teardown of child processes/fork bombs
- Optional bubblewrap (bwrap) isolation with network namespace isolation (--unshare-net)
"""
import logging
import os
import math
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("cpjudge.engine.sandbox")

try:
    import pwd
    import resource
    HAS_POSIX = True
except ImportError:
    HAS_POSIX = False
    resource = None
    pwd = None


def get_sandbox_user_ids(username: str = "judge_sandbox") -> Tuple[Optional[int], Optional[int]]:
    """Gets uid and gid for the low-privilege sandbox user."""
    if not HAS_POSIX or not pwd:
        return None, None
    try:
        user_entry = pwd.getpwnam(username)
        return user_entry.pw_uid, user_entry.pw_gid
    except KeyError:
        # Fallback to 'nobody' or current user
        try:
            nobody_entry = pwd.getpwnam("nobody")
            return nobody_entry.pw_uid, nobody_entry.pw_gid
        except KeyError:
            return None, None


@lru_cache(maxsize=8)
def is_bwrap_available(sandbox_user: Optional[str] = "judge_sandbox") -> bool:
    """Checks if bubblewrap (bwrap) is installed and functional."""
    bwrap_path = shutil.which("bwrap")
    if not bwrap_path or not all(os.path.exists(path) for path in ("/usr", "/bin", "/lib")):
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="cpjudge_bwrap_check_", dir="/tmp") as work_dir:
            os.chmod(work_dir, 0o755)
            command = build_bwrap_args(["true"], work_dir, sandbox_user=sandbox_user)
            command[0] = bwrap_path
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0,
                check=False,
            )
            if result.returncode != 0:
                err_text = result.stderr.decode("utf-8", errors="replace").strip()
                logger.warning(f"Bubblewrap availability check failed (exit {result.returncode}): {err_text}")
            return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"Bubblewrap availability check encountered exception: {exc}")
        return False


def build_bwrap_args(
    command: List[str],
    work_dir: str | Path,
    read_only_root: bool = True,
    sandbox_user: Optional[str] = "judge_sandbox",
) -> List[str]:
    """Wraps an execution command inside bubblewrap sandbox with network disabled."""
    work_dir = str(Path(work_dir).resolve())
    bwrap_cmd = [
        "bwrap",
        "--unshare-net",      # Disable all network access
        "--unshare-pid",      # New PID namespace
        "--unshare-ipc",      # New IPC namespace
        "--unshare-uts",      # New UTS namespace
        "--die-with-parent",  # Kill child if parent exits
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]
    bind_option = "--ro-bind" if read_only_root else "--bind"
    for system_path in ("/usr", "/bin", "/lib", "/lib64"):
        if os.path.exists(system_path):
            bwrap_cmd.extend([bind_option, system_path, system_path])
    if HAS_POSIX and os.geteuid() == 0:
        target_uid, target_gid = get_sandbox_user_ids(sandbox_user or "judge_sandbox")
        if target_uid is None or target_gid is None:
            raise RuntimeError(f"Sandbox user '{sandbox_user}' does not exist.")
        bwrap_cmd.extend(["--unshare-user", "--uid", str(target_uid), "--gid", str(target_gid)])
    bwrap_cmd.extend([
        "--bind", work_dir, work_dir,
        "--chdir", work_dir,
        "--",
    ])
    bwrap_cmd.extend(command)
    return bwrap_cmd


def create_preexec_fn(
    cpu_limit_seconds: float,
    memory_limit_bytes: int,
    output_limit_bytes: int,
    nproc_limit: int = 32,
    sandbox_user: Optional[str] = "judge_sandbox",
    drop_privileges: bool = True,
) -> Optional[Callable[[], None]]:
    """Creates a POSIX preexec_fn that sets resource limits and drops privileges."""
    if not HAS_POSIX or resource is None:
        return None

    target_uid, target_gid = get_sandbox_user_ids(sandbox_user or "judge_sandbox") if drop_privileges else (None, None)
    current_uid = os.geteuid() if hasattr(os, "geteuid") else -1

    def preexec() -> None:
        # Create a new session and process group so process tree can be killed cleanly
        os.setsid()

        # RLIMIT_CPU has one-second granularity; the parent also enforces fractional limits.
        cpu_soft = max(1, math.ceil(cpu_limit_seconds))
        cpu_hard = cpu_soft + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_hard))

        if memory_limit_bytes > 0:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))

        if output_limit_bytes > 0:
            resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit_bytes, output_limit_bytes))

        if nproc_limit > 0:
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc_limit, nproc_limit))

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        if current_uid == 0 and target_uid is not None and target_gid is not None:
            os.setgid(target_gid)
            os.setuid(target_uid)

    return preexec


def build_child_environment() -> dict[str, str]:
    """Returns a minimal environment that does not inherit application secrets."""
    return {
        "PATH": os.defpath,
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }
