"""Unit tests for the CPJudge compiler module."""
import tempfile
import pytest

from cpjudge.engine.compiler import Compiler
from cpjudge.engine.sandbox import build_bwrap_args, build_child_environment
from cpjudge.engine.verdicts import Verdict


def test_sandbox_does_not_mount_the_host_root(tmp_path):
    args = build_bwrap_args(["true"], tmp_path)
    assert ["--ro-bind", "/", "/"] not in [args[index:index + 3] for index in range(len(args) - 2)]
    assert ["--ro-bind", "/usr", "/usr"] in [
        args[index:index + 3] for index in range(len(args) - 2)
    ]


def test_bwrap_enters_user_namespace_before_dropping_root(monkeypatch, tmp_path):
    monkeypatch.setattr("cpjudge.engine.sandbox.HAS_POSIX", True)
    monkeypatch.setattr("cpjudge.engine.sandbox.os.geteuid", lambda: 0, raising=False)
    monkeypatch.setattr("cpjudge.engine.sandbox.get_sandbox_user_ids", lambda _user: (10001, 10001))

    args = build_bwrap_args(["true"], tmp_path)

    assert ["--unshare-user", "--uid", "10001", "--gid", "10001"] == args[
        args.index("--unshare-user"):args.index("--unshare-user") + 5
    ]


def test_student_environment_does_not_inherit_application_secrets(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "application-secret")
    assert "SECRET_KEY" not in build_child_environment()


def test_sandboxed_compiler_fails_closed_when_bubblewrap_is_unavailable(monkeypatch):
    monkeypatch.setattr("cpjudge.engine.compiler.is_bwrap_available", lambda *_args: False)
    with pytest.raises(RuntimeError, match="Bubblewrap is required"):
        Compiler(use_bwrap=True)


def test_compile_c_success():
    compiler = Compiler()
    c_code = """
    #include <stdio.h>
    int main() {
        printf("Hello C\\n");
        return 0;
    }
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = compiler.compile(c_code, "c", tmp_dir)
        assert res.success is True
        assert res.verdict is None
        assert res.executable_path is not None
        assert len(res.run_cmd) >= 1


def test_compile_cpp_success():
    compiler = Compiler()
    cpp_code = """
    #include <iostream>
    #include <vector>
    int main() {
        std::vector<int> v = {1, 2, 3};
        std::cout << "Size: " << v.size() << "\\n";
        return 0;
    }
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = compiler.compile(cpp_code, "cpp", tmp_dir)
        assert res.success is True
        assert res.verdict is None
        assert res.executable_path is not None


def test_compile_python_success():
    compiler = Compiler()
    py_code = """
import sys
print("Hello Python")
"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = compiler.compile(py_code, "python", tmp_dir)
        assert res.success is True
        assert res.verdict is None
        assert res.executable_path is not None


def test_compile_cpp_error():
    compiler = Compiler()
    bad_code = """
    #include <iostream>
    int main() {
        this_is_a_syntax_error();
        return 0;
    }
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = compiler.compile(bad_code, "cpp", tmp_dir)
        assert res.success is False
        assert res.verdict == Verdict.CE
        assert res.error_message is not None
        assert "this_is_a_syntax_error" in res.error_message


def test_compile_python_syntax_error():
    compiler = Compiler()
    bad_code = "def invalid_func(:\n    pass\n"
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = compiler.compile(bad_code, "python", tmp_dir)
        assert res.success is False
        assert res.verdict == Verdict.CE
        assert "SyntaxError" in res.error_message
