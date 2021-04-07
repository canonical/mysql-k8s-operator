#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""
Very simple module to check unit tests coverage.

If you are using github actions you can add something like this:

    - name: Unit tests
      run: |
        coverage run -m unittest
    - name: Test coverage
      run: |
        coverage report src/*.py | python tests/check_coverage.py


"""

import sys

MIN_COVERAGE = 80


def check() -> None:
    """
    This function reads coverage module standard output and check if
    TOTAL test coverage is better or worst than MIN_COVERAGE
    """
    coverage_report = sys.stdin.read()
    if "TOTAL" not in coverage_report:
        print("No coverage data found in stdin. -> FAILING")
        print(coverage_report)
        sys.exit(1)
    # extract coverag (last element after whitspace without the `%` sign)
    # TOTAL                                        116     22    81%
    try:
        coverage_value = int(coverage_report.split()[-1][:-1])
    except ValueError:
        print("Unable to convert TOTAL coverage to integer")
        print(coverage_report)
        sys.exit(1)

    exit_status = 0
    exit_status = int(coverage_value < MIN_COVERAGE)
    msg = [f"Current test coverage is {coverage_value}%"]

    if exit_status == 1:
        msg.append(f"Required test coverage is {MIN_COVERAGE}%")

    print(*msg, sep="\n")
    sys.exit(exit_status)


if __name__ == "__main__":
    check()
