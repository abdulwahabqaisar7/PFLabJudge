"""Comprehensive integration tests running all selftest/ programs against CPJudge engine."""
from pathlib import Path
import sys
import pytest

from cpjudge.engine.checker import CheckerType
from cpjudge.engine.judge import JudgeConfig, TestCase, judge_submission
from cpjudge.engine.runner import Runner
from cpjudge.engine.sandbox import is_bwrap_available
from cpjudge.engine.verdicts import Verdict

SELFTEST_DIR = Path(__file__).parent.parent / "selftest"
requires_bwrap = pytest.mark.skipif(
    not is_bwrap_available(),
    reason="Bubblewrap user namespaces are unavailable in this environment.",
)


def get_standard_test_cases():
    return [
        TestCase(id="1", input_data="10 20\n", expected_output="30\n", marks=10.0, is_hidden=False),
        TestCase(id="2", input_data="500 250\n", expected_output="750\n", marks=20.0, is_hidden=False),
        TestCase(id="3_hidden", input_data="-10 10\n", expected_output="0\n", marks=20.0, is_hidden=True),
    ]


@requires_bwrap
def test_correct_cpp():
    code = (SELFTEST_DIR / "correct.cpp").read_text(encoding="utf-8")
    tests = get_standard_test_cases()
    result = judge_submission(code, "cpp", tests)

    assert result.verdict == Verdict.AC
    assert result.total_score == 50.0
    assert result.raw_score == 50.0
    assert len(result.test_results) == 3
    for tr in result.test_results:
        assert tr.verdict == Verdict.AC
        assert tr.marks_awarded > 0


@requires_bwrap
def test_correct_c():
    code = (SELFTEST_DIR / "correct.c").read_text(encoding="utf-8")
    tests = get_standard_test_cases()
    result = judge_submission(code, "c", tests)

    assert result.verdict == Verdict.AC
    assert result.total_score == 50.0


@requires_bwrap
def test_correct_python():
    code = (SELFTEST_DIR / "correct.py").read_text(encoding="utf-8")
    tests = get_standard_test_cases()
    result = judge_submission(code, "python", tests)

    assert result.verdict == Verdict.AC
    assert result.total_score == 50.0


@requires_bwrap
def test_wrong_answer_cpp_and_diff_hiding():
    code = (SELFTEST_DIR / "wrong_answer.cpp").read_text(encoding="utf-8")
    tests = get_standard_test_cases()
    result = judge_submission(code, "cpp", tests)

    assert result.verdict == Verdict.WA
    assert result.total_score == 0.0

    # Test 1 is visible: diff must be present
    tr1 = next(t for t in result.test_results if t.test_id == "1")
    assert tr1.verdict == Verdict.WA
    assert tr1.diff is not None
    assert "-30" in tr1.diff
    assert "+31" in tr1.diff
    assert tr1.student_output is not None

    # Test 3 is hidden: diff and student output MUST BE HIDDEN (None)
    tr3 = next(t for t in result.test_results if t.test_id == "3_hidden")
    assert tr3.verdict == Verdict.WA
    assert tr3.diff is None
    assert tr3.student_output is None


@requires_bwrap
def test_infinite_loop_tle():
    code = (SELFTEST_DIR / "infinite_loop.cpp").read_text(encoding="utf-8")
    tests = [TestCase(id="1", input_data="1 2\n", expected_output="3\n", marks=10.0)]
    config = JudgeConfig(time_limit=0.5)

    result = judge_submission(code, "cpp", tests, config)
    assert result.verdict == Verdict.TLE
    assert result.test_results[0].verdict == Verdict.TLE
    assert result.total_score == 0.0


@requires_bwrap
def test_mle_cpp():
    code = (SELFTEST_DIR / "mle.cpp").read_text(encoding="utf-8")
    tests = [TestCase(id="1", input_data="", expected_output="Allocated 2048 MB successfully\n", marks=10.0)]
    # Set limit to 64 MB so 2 GB allocation triggers MLE
    config = JudgeConfig(time_limit=2.0, memory_limit_mb=64)

    result = judge_submission(code, "cpp", tests, config)
    assert result.verdict == Verdict.MLE
    assert result.total_score == 0.0


@requires_bwrap
def test_segfault_re():
    code = (SELFTEST_DIR / "segfault.cpp").read_text(encoding="utf-8")
    tests = [TestCase(id="1", input_data="", expected_output="", marks=10.0)]

    result = judge_submission(code, "cpp", tests)
    assert result.verdict == Verdict.RE
    assert result.total_score == 0.0


@requires_bwrap
def test_ole_output_limit():
    code = (SELFTEST_DIR / "ole.cpp").read_text(encoding="utf-8")
    tests = [TestCase(id="1", input_data="", expected_output="", marks=10.0)]
    # Cap output at 64 KB
    config = JudgeConfig(time_limit=1.5, output_limit_bytes=64 * 1024)

    result = judge_submission(code, "cpp", tests, config)
    assert result.verdict == Verdict.OLE
    assert result.total_score == 0.0


def test_output_limit_caps_captured_stdout():
    output_limit = 4096
    result = Runner(use_bwrap=False).run_test(
        run_cmd=[sys.executable, "-c", "import sys; sys.stdout.write('x' * 10_000_000)"],
        language="python",
        test_input="",
        time_limit=2.0,
        output_limit_bytes=output_limit,
    )

    assert result.verdict == Verdict.OLE
    assert result.output_truncated
    assert len(result.stdout.encode("utf-8")) <= output_limit + 1


@requires_bwrap
def test_fork_bomb_survival():
    code = (SELFTEST_DIR / "fork_bomb.cpp").read_text(encoding="utf-8")
    tests = [TestCase(id="1", input_data="", expected_output="done", marks=10.0)]
    config = JudgeConfig(time_limit=0.8)

    # The judge must survive the fork bomb without hanging or crashing
    result = judge_submission(code, "cpp", tests, config)
    assert result.verdict in (Verdict.TLE, Verdict.RE)
    assert result.total_score == 0.0


@requires_bwrap
def test_malicious_read_passwd():
    code = (SELFTEST_DIR / "read_passwd.cpp").read_text(encoding="utf-8")
    tests = [TestCase(id="1", input_data="10 20\n", expected_output="30\n", marks=10.0)]

    result = judge_submission(code, "cpp", tests)
    # Must not receive Accepted verdict
    assert result.verdict != Verdict.AC


@requires_bwrap
def test_malicious_read_test_files():
    code = (SELFTEST_DIR / "read_test_files.cpp").read_text(encoding="utf-8")
    tests = [TestCase(id="1", input_data="10 20\n", expected_output="30\n", marks=10.0)]

    result = judge_submission(code, "cpp", tests)
    # Must not receive Accepted verdict
    assert result.verdict != Verdict.AC
