"""Checker module for CPJudge.

Supports checker types:
- exact: byte/string matching (normalizing line endings)
- token: whitespace-insensitive token-by-token comparison
- float: token comparison with relative/absolute floating-point tolerance
- custom: runs a script receiving (input_file, expected_file, actual_file)
"""
from dataclasses import dataclass
import difflib
from enum import Enum
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

from cpjudge.engine.sandbox import (
    build_child_environment,
    build_bwrap_args,
    create_preexec_fn,
    is_bwrap_available,
)
from cpjudge.engine.docker_sandbox import DockerSandbox
from cpjudge.engine.verdicts import Verdict


class CheckerType(str, Enum):
    EXACT = "exact"
    TOKEN = "token"
    FLOAT = "float"
    CUSTOM = "custom"


@dataclass
class CheckResult:
    verdict: Verdict
    feedback: Optional[str] = None
    diff: Optional[str] = None


def generate_diff(expected: str, actual: str, max_lines: int = 100) -> str:
    """Generates unified diff between expected and actual strings."""
    expected_lines = expected.replace("\r\n", "\n").splitlines(keepends=True)
    actual_lines = actual.replace("\r\n", "\n").splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected",
            tofile="actual",
            lineterm="\n",
        )
    )

    if not diff_lines:
        return ""

    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines] + [f"\n... diff truncated after {max_lines} lines ...\n"]

    return "".join(diff_lines)


class Checker:
    def __init__(
        self,
        checker_type: CheckerType = CheckerType.TOKEN,
        float_tolerance: float = 1e-6,
        custom_checker_path: Optional[str] = None,
        use_bwrap: bool = False,
        sandbox_user: Optional[str] = "judge_sandbox",
        sandbox_backend: Optional[str] = None,
        docker_image: str = "cpjudge:local",
    ):
        self.checker_type = checker_type
        self.float_tolerance = float_tolerance
        self.custom_checker_path = custom_checker_path
        self.sandbox_backend = sandbox_backend or ("bwrap" if use_bwrap else "process")
        if self.sandbox_backend not in ("process", "bwrap", "docker"):
            raise ValueError(f"Unknown sandbox backend: {self.sandbox_backend}")
        self.use_bwrap = self.sandbox_backend == "bwrap"
        self.sandbox_user = sandbox_user
        self.docker_image = docker_image
        if self.use_bwrap and not is_bwrap_available(sandbox_user):
            raise RuntimeError("Bubblewrap is required for sandboxed checking but is unavailable.")

    def check(
        self,
        input_data: str,
        expected_output: str,
        student_output: str,
        is_visible: bool = False,
    ) -> CheckResult:
        """Evaluates student output against expected output using configured checker."""
        if self.checker_type == CheckerType.EXACT:
            res = self._check_exact(expected_output, student_output)
        elif self.checker_type == CheckerType.TOKEN:
            res = self._check_token(expected_output, student_output)
        elif self.checker_type == CheckerType.FLOAT:
            res = self._check_float(expected_output, student_output)
        elif self.checker_type == CheckerType.CUSTOM:
            res = self._check_custom(input_data, expected_output, student_output)
        else:
            res = CheckResult(verdict=Verdict.WA, feedback=f"Unknown checker type: {self.checker_type}")

        # Attach diff if visible test case and verdict is WA
        if is_visible and res.verdict != Verdict.AC:
            res.diff = generate_diff(expected_output, student_output)

        return res

    def _check_exact(self, expected: str, actual: str) -> CheckResult:
        norm_expected = expected.replace("\r\n", "\n").rstrip()
        norm_actual = actual.replace("\r\n", "\n").rstrip()

        if norm_expected == norm_actual:
            return CheckResult(verdict=Verdict.AC)
        return CheckResult(verdict=Verdict.WA, feedback="Output does not match expected output exactly")

    def _check_token(self, expected: str, actual: str) -> CheckResult:
        expected_tokens = expected.replace("\r\n", "\n").split()
        actual_tokens = actual.replace("\r\n", "\n").split()

        if len(expected_tokens) != len(actual_tokens):
            return CheckResult(
                verdict=Verdict.WA,
                feedback=f"Token count mismatch: expected {len(expected_tokens)}, got {len(actual_tokens)} tokens",
            )

        for i, (exp, act) in enumerate(zip(expected_tokens, actual_tokens)):
            if exp != act:
                return CheckResult(
                    verdict=Verdict.WA,
                    feedback=f"Token mismatch at position {i + 1}: expected '{exp}', got '{act}'",
                )

        return CheckResult(verdict=Verdict.AC)

    def _check_float(self, expected: str, actual: str) -> CheckResult:
        expected_tokens = expected.replace("\r\n", "\n").split()
        actual_tokens = actual.replace("\r\n", "\n").split()

        if len(expected_tokens) != len(actual_tokens):
            return CheckResult(
                verdict=Verdict.WA,
                feedback=f"Token count mismatch: expected {len(expected_tokens)}, got {len(actual_tokens)} tokens",
            )

        for i, (exp, act) in enumerate(zip(expected_tokens, actual_tokens)):
            try:
                exp_f = float(exp)
                act_f = float(act)
                if not math.isclose(exp_f, act_f, rel_tol=self.float_tolerance, abs_tol=self.float_tolerance):
                    return CheckResult(
                        verdict=Verdict.WA,
                        feedback=f"Float mismatch at position {i + 1}: expected {exp_f}, got {act_f} (tolerance {self.float_tolerance})",
                    )
            except ValueError:
                # Fallback to direct token comparison for non-floats
                if exp != act:
                    return CheckResult(
                        verdict=Verdict.WA,
                        feedback=f"Token mismatch at position {i + 1}: expected '{exp}', got '{act}'",
                    )

        return CheckResult(verdict=Verdict.AC)

    def _check_custom(self, input_data: str, expected: str, actual: str) -> CheckResult:
        if not self.custom_checker_path or not Path(self.custom_checker_path).exists():
            return CheckResult(
                verdict=Verdict.WA,
                feedback=f"Custom checker executable not found: {self.custom_checker_path}",
            )

        with tempfile.TemporaryDirectory(prefix="cpjudge_checker_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            in_file = tmp_path / "input.txt"
            exp_file = tmp_path / "expected.txt"
            act_file = tmp_path / "actual.txt"
            source_checker = Path(self.custom_checker_path).resolve()
            checker_file = tmp_path / source_checker.name

            in_file.write_text(input_data, encoding="utf-8")
            exp_file.write_text(expected, encoding="utf-8")
            act_file.write_text(actual, encoding="utf-8")
            shutil.copyfile(source_checker, checker_file)
            for path in (in_file, exp_file, act_file):
                path.chmod(0o644)
            checker_file.chmod(0o644 if source_checker.suffix == ".py" else 0o755)
            tmp_path.chmod(0o755)

            if source_checker.suffix == ".py":
                cmd = [sys.executable, str(checker_file), str(in_file), str(exp_file), str(act_file)]
            else:
                cmd = [str(checker_file), str(in_file), str(exp_file), str(act_file)]

            if self.sandbox_backend == "docker":
                result = DockerSandbox(self.docker_image).run(
                    command=cmd,
                    work_dir=tmp_path,
                    timeout=5.0,
                    cpu_limit_seconds=5.0,
                    memory_limit_bytes=256 * 1024 * 1024,
                    output_limit_bytes=1024 * 1024,
                    nproc_limit=16,
                )
                output = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
                if result.exit_code == 0 and not result.timed_out:
                    return CheckResult(verdict=Verdict.AC, feedback=output or None)
                if result.timed_out:
                    return CheckResult(verdict=Verdict.WA, feedback="Custom checker timed out after 5.0s")
                return CheckResult(
                    verdict=Verdict.WA,
                    feedback=output or f"Custom checker exited with code {result.exit_code}",
                )

            if self.use_bwrap:
                cmd = build_bwrap_args(cmd, tmp_path, sandbox_user=self.sandbox_user)
            preexec = create_preexec_fn(
                cpu_limit_seconds=5.0,
                memory_limit_bytes=256 * 1024 * 1024,
                output_limit_bytes=1024 * 1024,
                nproc_limit=16,
                sandbox_user=self.sandbox_user,
                drop_privileges=False,
            )

            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5.0,
                    cwd=tmp_dir,
                    env=build_child_environment(),
                    preexec_fn=preexec,
                    check=False,
                )
                output = (proc.stdout.strip() + "\n" + proc.stderr.strip()).strip()
                if proc.returncode == 0:
                    return CheckResult(verdict=Verdict.AC, feedback=output or None)
                else:
                    return CheckResult(
                        verdict=Verdict.WA,
                        feedback=output or f"Custom checker exited with code {proc.returncode}",
                    )
            except subprocess.TimeoutExpired:
                return CheckResult(verdict=Verdict.WA, feedback="Custom checker timed out after 5.0s")
            except (OSError, subprocess.SubprocessError) as e:
                return CheckResult(verdict=Verdict.WA, feedback=f"Custom checker error: {e}")
