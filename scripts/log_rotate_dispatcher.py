# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Log rotate event dispatcher."""

import argparse
import shutil
import subprocess
import time


def dispatch(unit: str, charm_directory: str):
    """Dispatch custom event to flush mysql logs."""
    dispatch_sub_command = f"{charm_directory}/dispatch"

    juju_run = shutil.which("juju-run")
    juju_exec = shutil.which("juju-exec")
    command = juju_exec or juju_run or ""

    subprocess.run(  # noqa: S603
        [
            command,
            "-u",
            unit,
            "JUJU_DISPATCH_PATH=hooks/rotate_mysql_logs",
            dispatch_sub_command,
        ],
        check=True,
    )


def main():
    """Main watch and dispatch loop.

    Roughly every 60s at the top of the minute, dispatch the custom rotate_mysql_logs event.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("unit", help="name of unit")
    parser.add_argument("charm_directory", help="base directory of the charm")
    arguments = parser.parse_args()

    # wait till the top of the minute
    time.sleep(60 - (time.time() % 60))
    start_time = time.monotonic()

    while True:
        dispatch(arguments.unit, arguments.charm_directory)

        # wait again till the top of the next minute
        time.sleep(60.0 - ((time.monotonic() - start_time) % 60.0))


if __name__ == "__main__":
    main()
