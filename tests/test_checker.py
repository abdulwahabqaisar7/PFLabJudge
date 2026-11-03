"""Unit tests for the CPJudge checker module."""
from pathlib import Path
import pytest

from cpjudge.engine.checker import Checker, CheckerType, generate_diff
from cpjudge.engine.verdicts import Verdict


def test_checker_exact():
    checker = Checker(checker_type=CheckerType.EXACT)

    # Identical with newline difference
    res1 = checker.check("", "hello world\r\n", "hello world\n")
    assert res1.verdict == Verdict.AC

    # Mismatch
    res2 = checker.check("", "hello world\n", "hello  world\n")
    assert res2.verdict == Verdict.WA


def test_checker_token():
    checker = Checker(checker_type=CheckerType.TOKEN)

    # Different whitespace, same tokens
    res1 = checker.check("", "1 2  3\n4 5\r\n", "1\n2\n3 4 5")
    assert res1.verdict == Verdict.AC

    # Extra token
    res2 = checker.check("", "1 2 3", "1 2 3 4")
    assert res2.verdict == Verdict.WA

    # Different token
    res3 = checker.check("", "apple banana", "apple orange")
    assert res3.verdict == Verdict.WA


def test_checker_float():
    checker = Checker(checker_type=CheckerType.FLOAT, float_tolerance=1e-4)

    # Within tolerance
    res1 = checker.check("", "3.1415926", "3.1415900")
    assert res1.verdict == Verdict.AC

    # Exceeding tolerance
    res2 = checker.check("", "3.14159", "3.14999")
    assert res2.verdict == Verdict.WA

    # Mixed float and string
    res3 = checker.check("", "ans: 10.5000001", "ans: 10.5000002")
    assert res3.verdict == Verdict.AC


def test_checker_custom():
    custom_script = Path(__file__).parent.parent / "selftest" / "custom_checker.py"
    checker = Checker(
        checker_type=CheckerType.CUSTOM,
        custom_checker_path=str(custom_script),
    )

    # Correct
    res1 = checker.check("10 20", "30", "30")
    assert res1.verdict == Verdict.AC

    # Incorrect
    res2 = checker.check("10 20", "30", "31")
    assert res2.verdict == Verdict.WA
    assert res2.feedback is not None


def test_generate_diff_visible():
    checker = Checker(checker_type=CheckerType.EXACT)
    res = checker.check("", "line1\nline2\n", "line1\nline_different\n", is_visible=True)
    assert res.verdict == Verdict.WA
    assert res.diff is not None
    assert "-line2" in res.diff
    assert "+line_different" in res.diff
