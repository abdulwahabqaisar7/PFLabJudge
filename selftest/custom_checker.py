#!/usr/bin/env python3
"""Custom test checker script.

Receives 3 arguments:
    sys.argv[1]: path to test input file
    sys.argv[2]: path to expected output file
    sys.argv[3]: path to student actual output file

Exits with code 0 on AC, non-zero on WA.
Outputs feedback message to stdout.
"""
from pathlib import Path
import sys


def main():
    if len(sys.argv) < 4:
        print("Usage: custom_checker.py <input> <expected> <actual>")
        sys.exit(2)

    in_path = Path(sys.argv[1])
    exp_path = Path(sys.argv[2])
    act_path = Path(sys.argv[3])

    if not in_path.exists() or not exp_path.exists() or not act_path.exists():
        print("Error: Input, expected, or actual file missing")
        sys.exit(2)

    in_text = in_path.read_text(encoding="utf-8").strip()
    exp_text = exp_path.read_text(encoding="utf-8").strip()
    act_text = act_path.read_text(encoding="utf-8").strip()

    # Custom rule: verify answer equals expected
    if exp_text == act_text:
        print("Custom checker: Valid solution verified!")
        sys.exit(0)
    else:
        print(f"Custom checker: Discrepancy detected! Expected '{exp_text}', received '{act_text}'")
        sys.exit(1)


if __name__ == "__main__":
    main()
