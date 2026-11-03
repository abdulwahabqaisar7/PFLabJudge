"""Compiler module for CPJudge.

Supports:
- C: gcc -O2 -lm
- C++: g++ -O2 -std=c++17 -lm
- Python: py_compile syntax check
"""
from dataclasses import dataclass
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import time
from typing import List, Optional

from cpjudge.engine.sandbox import (
    build_child_environment,
    build_bwrap_args,
    create_preexec_fn,
    is_bwrap_available,
)
from cpjudge.engine.verdicts import Verdict


@dataclass
class CompileResult:
    success: bool
    run_cmd: List[str]
    executable_path: Optional[str] = None
    error_message: Optional[str] = None
    verdict: Optional[Verdict] = None
    compile_time: float = 0.0


class Compiler:
    def __init__(
        self,
        compile_timeout: float = 10.0,
        use_bwrap: bool = False,
        sandbox_user: Optional[str] = "judge_sandbox",
    ):
        self.compile_timeout = compile_timeout
        self.use_bwrap = use_bwrap
        self.sandbox_user = sandbox_user
        if use_bwrap and not is_bwrap_available(sandbox_user):
            raise RuntimeError("Bubblewrap is required for sandboxed compilation but is unavailable.")

    def compile(
        self,
        source_code: str,
        language: str,
        work_dir: str | Path,
    ) -> CompileResult:
        """Compiles or syntax-checks source code in the given directory.

        Args:
            source_code: Raw source code string.
            language: Language identifier ('c', 'cpp', or 'python').
            work_dir: Directory where source file and binary are stored.

        Returns:
            CompileResult detailing success, command to run, and any errors.
        """
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        lang = language.strip().lower()

        if lang in ("c", "gcc"):
            return self._compile_c(source_code, work_dir)
        elif lang in ("cpp", "c++", "g++"):
            return self._compile_cpp(source_code, work_dir)
        elif lang in ("py", "python", "python3"):
            return self._check_python(source_code, work_dir)
        else:
            return CompileResult(
                success=False,
                run_cmd=[],
                error_message=f"Unsupported language: {language}",
                verdict=Verdict.CE,
            )

    def _compile_c(self, source_code: str, work_dir: Path) -> CompileResult:
        src_path = work_dir / "solution.c"
        bin_path = work_dir / "solution.out"
        src_path.write_text(source_code, encoding="utf-8")
        try:
            os.chmod(str(src_path), 0o755)
        except OSError:
            pass

        cmd = [
            "gcc",
            "-O2",
            "-std=c11",
            str(src_path),
            "-o",
            str(bin_path),
            "-lm",
        ]
        res = self._run_compiler_cmd(cmd, bin_path)
        if res.success and bin_path.exists():
            try:
                os.chmod(str(bin_path), 0o755)
            except OSError:
                pass
        return res

    def _compile_cpp(self, source_code: str, work_dir: Path) -> CompileResult:
        src_path = work_dir / "solution.cpp"
        bin_path = work_dir / "solution.out"
        src_path.write_text(source_code, encoding="utf-8")
        try:
            os.chmod(str(src_path), 0o755)
        except OSError:
            pass

        cmd = [
            "g++",
            "-O2",
            "-std=c++17",
            str(src_path),
            "-o",
            str(bin_path),
            "-lm",
        ]
        res = self._run_compiler_cmd(cmd, bin_path)
        if res.success and bin_path.exists():
            try:
                os.chmod(str(bin_path), 0o755)
            except OSError:
                pass
        return res

    def _run_compiler_cmd(self, cmd: List[str], bin_path: Path) -> CompileResult:
        start_time = time.perf_counter()
        work_dir = bin_path.parent.resolve()
        if self.use_bwrap:
            cmd = build_bwrap_args(cmd, work_dir, sandbox_user=self.sandbox_user)
        preexec = create_preexec_fn(
            cpu_limit_seconds=self.compile_timeout,
            memory_limit_bytes=1024 * 1024 * 1024,
            output_limit_bytes=64 * 1024 * 1024,
            nproc_limit=32,
            sandbox_user=self.sandbox_user,
            drop_privileges=False,
        )
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.compile_timeout,
                cwd=str(work_dir),
                env=build_child_environment(),
                preexec_fn=preexec,
                check=False,
            )
            elapsed = time.perf_counter() - start_time
            if proc.returncode == 0 and bin_path.exists():
                return CompileResult(
                    success=True,
                    run_cmd=[str(bin_path)],
                    executable_path=str(bin_path),
                    compile_time=elapsed,
                )
            else:
                stderr_output = proc.stderr.strip() or proc.stdout.strip()
                return CompileResult(
                    success=False,
                    run_cmd=[],
                    error_message=stderr_output or f"Compiler failed with exit code {proc.returncode}",
                    verdict=Verdict.CE,
                    compile_time=elapsed,
                )
        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                run_cmd=[],
                error_message=f"Compilation timed out after {self.compile_timeout:.1f}s",
                verdict=Verdict.CE,
                compile_time=self.compile_timeout,
            )
        except FileNotFoundError as e:
            return CompileResult(
                success=False,
                run_cmd=[],
                error_message=f"Compiler not found on system: {e}",
                verdict=Verdict.CE,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return CompileResult(
                success=False,
                run_cmd=[],
                error_message=f"Compilation error: {e}",
                verdict=Verdict.CE,
            )

    def _check_python(self, source_code: str, work_dir: Path) -> CompileResult:
        src_path = work_dir / "solution.py"
        src_path.write_text(source_code, encoding="utf-8")
        try:
            os.chmod(str(src_path), 0o755)
        except OSError:
            pass

        start_time = time.perf_counter()
        try:
            # First, compile() in Python to check syntax and get clean error
            compile(source_code, str(src_path), "exec")
            # Also compile to pyc via py_compile to ensure byte-compilability
            py_compile.compile(str(src_path), doraise=True)
            elapsed = time.perf_counter() - start_time
            return CompileResult(
                success=True,
                run_cmd=[sys.executable, str(src_path)],
                executable_path=str(src_path),
                compile_time=elapsed,
            )
        except SyntaxError as e:
            elapsed = time.perf_counter() - start_time
            msg = f"SyntaxError in line {e.lineno}: {e.msg}\n  {e.text or ''}"
            return CompileResult(
                success=False,
                run_cmd=[],
                error_message=msg,
                verdict=Verdict.CE,
                compile_time=elapsed,
            )
        except (py_compile.PyCompileError, OSError, UnicodeError) as e:
            elapsed = time.perf_counter() - start_time
            return CompileResult(
                success=False,
                run_cmd=[],
                error_message=f"Compilation Error: {e}",
                verdict=Verdict.CE,
                compile_time=elapsed,
            )
