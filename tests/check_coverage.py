# This script checks the coverage and test if it keeps at least the same
# Add this to your .gitlab-ci.yml
#
# coveragetest:
#  ...
#  cache:
#    paths:
#    - coverage_value.txt
#  script:
#   - bin/coverage run bin/test
#   - bin/coverage report
#   - bin/coverage report | python check_coverage.py

import sys

MIN_COVERAGE = 80


def main():
    coverage_report = sys.stdin.read()
    if "TOTAL" not in coverage_report:
        print("No coverage data found in stdin. -> FAILING")
        print(coverage_report)
        sys.exit(1)
    # extract coverag (last element after whitspace without the `%` sign)
    # TOTAL                                        116     22    81%
    coverage_value = int(coverage_report.split()[-1][:-1])
    exit_status = 0
    exit_status = int(coverage_value < MIN_COVERAGE)
    msg = [f"Current test coverage is {coverage_value}%"]

    if exit_status == 1:
        msg.append(f"Required test coverage is {MIN_COVERAGE}%")

    print(*msg, sep="\n")
    sys.exit(exit_status)


if __name__ == "__main__":
    main()
