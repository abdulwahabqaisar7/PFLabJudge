"""Command-line interface for the CPJudge engine."""
import argparse
import json
from pathlib import Path
import sys
from typing import List

from cpjudge.engine.checker import CheckerType
from cpjudge.engine.judge import JudgeConfig, TestCase, judge_submission
from cpjudge.engine.scorer import ScoringMode


def load_tests_from_dir(tests_dir: Path) -> List[TestCase]:
    """Discovers test cases in a directory matching *.in with *.ans or *.out."""
    tests = []
    in_files = sorted(tests_dir.glob("*.in"))
    for idx, in_file in enumerate(in_files, start=1):
        stem = in_file.stem
        ans_file = tests_dir / f"{stem}.ans"
        if not ans_file.exists():
            ans_file = tests_dir / f"{stem}.out"

        expected = ans_file.read_text(encoding="utf-8") if ans_file.exists() else ""
        input_data = in_file.read_text(encoding="utf-8")
        is_hidden = stem.startswith("hidden") or stem.endswith("_hidden")
        tests.append(
            TestCase(
                id=stem,
                input_data=input_data,
                expected_output=expected,
                marks=10.0,
                is_hidden=is_hidden,
            )
        )
    return tests


def main() -> None:
    parser = argparse.ArgumentParser(description="CPJudge CLI - Run and evaluate code against test cases")
    parser.add_argument("--source", "-s", required=True, help="Path to student source code file")
    parser.add_argument("--lang", "-l", required=True, choices=["c", "cpp", "python"], help="Programming language")
    parser.add_argument("--tests-dir", "-t", required=True, help="Directory containing .in and .ans/.out test files")
    parser.add_argument("--time-limit", type=float, default=1.0, help="CPU time limit in seconds (default: 1.0)")
    parser.add_argument("--memory-limit", type=int, default=256, help="Memory limit in MB (default: 256)")
    parser.add_argument("--checker", default="token", choices=["exact", "token", "float", "custom"], help="Checker type")
    parser.add_argument("--custom-checker", default=None, help="Path to custom checker script")
    parser.add_argument("--float-tolerance", type=float, default=1e-6, help="Tolerance for float checker")
    parser.add_argument("--scoring", default="per_test", choices=["per_test", "all_or_nothing", "grouped"], help="Scoring mode")
    parser.add_argument("--late-penalty", type=float, default=0.0, help="Late penalty percentage (0-100)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    src_path = Path(args.source)
    if not src_path.exists():
        print(f"Error: Source file not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    tests_dir = Path(args.tests_dir)
    if not tests_dir.exists():
        print(f"Error: Tests directory not found: {tests_dir}", file=sys.stderr)
        sys.exit(1)

    source_code = src_path.read_text(encoding="utf-8")
    test_cases = load_tests_from_dir(tests_dir)

    if not test_cases:
        print(f"Error: No test cases (*.in) found in {tests_dir}", file=sys.stderr)
        sys.exit(1)

    config = JudgeConfig(
        time_limit=args.time_limit,
        memory_limit_mb=args.memory_limit,
        checker_type=CheckerType(args.checker),
        custom_checker_path=args.custom_checker,
        float_tolerance=args.float_tolerance,
        scoring_mode=ScoringMode(args.scoring),
        late_penalty_percent=args.late_penalty,
    )

    result = judge_submission(source_code, args.lang, test_cases, config)

    if args.json:
        data = {
            "verdict": result.verdict.value,
            "total_score": result.total_score,
            "raw_score": result.raw_score,
            "max_score": result.max_score,
            "late_penalty_deduction": result.late_penalty_deduction,
            "compile_error": result.compile_error,
            "compile_time": result.compile_time,
            "max_time": result.max_time,
            "max_memory_kb": result.max_memory_kb,
            "test_results": [
                {
                    "test_id": tr.test_id,
                    "verdict": tr.verdict.value,
                    "marks_awarded": tr.marks_awarded,
                    "cpu_time": tr.cpu_time,
                    "memory_kb": tr.memory_kb,
                    "is_hidden": tr.is_hidden,
                    "diff": tr.diff,
                    "feedback": tr.feedback,
                }
                for tr in result.test_results
            ],
        }
        print(json.dumps(data, indent=2))
        return

    # Formatted console output
    print(f"\n================ CPJUDGE EVALUATION ================")
    print(f"Overall Verdict: {result.verdict.value} ({result.verdict.description})")
    print(f"Score:           {result.total_score} / {result.max_score} (Raw: {result.raw_score}, Late Penalty: -{result.late_penalty_deduction})")
    print(f"Max Time:        {result.max_time:.3f}s | Max Memory: {result.max_memory_kb} KB")

    if result.compile_error:
        print(f"\n[Compilation Error]\n{result.compile_error}\n")
        sys.exit(0)

    print("\nTest Results:")
    print("-" * 65)
    print(f"{'Test':<12} {'Verdict':<8} {'Marks':<10} {'CPU Time':<12} {'Memory (KB)':<12}")
    print("-" * 65)
    for tr in result.test_results:
        hidden_tag = " (H)" if tr.is_hidden else ""
        print(
            f"{str(tr.test_id) + hidden_tag:<12} "
            f"{tr.verdict.value:<8} "
            f"{tr.marks_awarded:<10.1f} "
            f"{tr.cpu_time:<12.3f} "
            f"{tr.memory_kb:<12}"
        )
        if tr.diff:
            print("  Diff:")
            for line in tr.diff.splitlines()[:10]:
                print(f"    {line}")
    print("-" * 65)


if __name__ == "__main__":
    main()
