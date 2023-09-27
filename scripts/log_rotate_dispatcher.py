# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Log rotate event dispatcher."""

import shutil
import subprocess
import sys
import time


def dispatch(unit: str, charm_directory: str):
    """Dispatch custom event to flush mysql logs."""
    dispatch_sub_command = f"JUJU_DISPATCH_PATH=hooks/rotate_mysql_logs {charm_directory}/dispatch"

    juju_run = shutil.which("juju-run")
    juju_exec = shutil.which("juju-exec")
    command = juju_exec if juju_exec else juju_run

    subprocess.run([command, "-u", unit, dispatch_sub_command], check=True)


def main():
    """Main watch and dispatch loop.

    Roughly every 60s at the top of the minute, dispatch the custom rotate_mysql_logs event.
    """
    unit, charm_directory = sys.argv[1:]

    # wait till the top of the minute
    time.sleep(60 - (time.time() % 60))
    start_time = time.monotonic()

    while True:
        dispatch(unit, charm_directory)

        # wait again till the top of the next minute
        time.sleep(60.0 - ((time.monotonic() - start_time) % 60.0))


if __name__ == "__main__":
    main()
