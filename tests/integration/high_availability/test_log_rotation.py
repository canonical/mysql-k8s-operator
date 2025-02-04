#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from ..helpers import (
    delete_file_or_directory_in_unit,
    dispatch_custom_event_for_logrotate,
    ls_in_unit,
    read_contents_from_file_in_unit,
    stop_running_flush_mysql_job,
    stop_running_log_rotate_dispatcher,
    write_content_to_file_in_unit,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]



@pytest.mark.abort_on_fail
async def test_log_rotation(
    ops_test: OpsTest, highly_available_cluster, continuous_writes
) -> None:
    """Test the log rotation of text files.

    Run continuous writes to ensure that audit log plugin is loaded and active
    when mysql-test-app runs start-continuous-writes (by logging into mysql).
    """
    unit = ops_test.model.applications[APP_NAME].units[0]
    logger.info(f"Using unit {unit.name}")

    logger.info("Extending update-status-hook-interval to 60m")
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})

    # Exclude slow log files as slow logs are not enabled by default
    log_types = ["error", "audit"]
    log_files = ["error.log", "audit.log"]
    archive_directories = [
        "archive_error",
        "archive_audit",
    ]

    logger.info("Overwriting the log rotate dispatcher script")
    unit_label = unit.name.replace("/", "-")
    await write_content_to_file_in_unit(
        ops_test,
        unit,
        f"/var/lib/juju/agents/unit-{unit_label}/charm/scripts/log_rotate_dispatcher.py",
        "exit(0)\n",
        container_name="charm",
    )

    logger.info("Stopping the log rotate dispatcher")
    await stop_running_log_rotate_dispatcher(ops_test, unit.name)

    logger.info("Stopping any running logrotate jobs")
    await stop_running_flush_mysql_job(ops_test, unit.name)

    logger.info("Removing existing archive directories")
    for archive_directory in archive_directories:
        await delete_file_or_directory_in_unit(
            ops_test,
            unit.name,
            f"/var/log/mysql/{archive_directory}/",
        )

    logger.info("Writing some data to the text log files")
    for log in log_types:
        log_path = f"/var/log/mysql/{log}.log"
        await write_content_to_file_in_unit(ops_test, unit, log_path, f"test {log} content\n")

    logger.info("Ensuring only log files exist")
    # Exclude archive directories, as handling any event would restart the
    # log_rotate_dispatcher (by the log_rotate_manager)
    ls_output = await ls_in_unit(
        ops_test, unit.name, "/var/log/mysql/", exclude_files=archive_directories
    )

    for file in log_files:
        # audit.log can be rotated and new file not created until access to db
        assert (
            file in ls_output or file == "audit.log"
        ), f"❌ files other than log files exist {ls_output}"

    logger.info("Dispatching custom event to rotate logs")
    await dispatch_custom_event_for_logrotate(ops_test, unit.name)

    logger.info("Ensuring log files were rotated")
    # Exclude checking slow log rotation as slow logs are disabled by default
    for log in set(log_types):
        file_contents = read_contents_from_file_in_unit(
            ops_test, unit, f"/var/log/mysql/{log}.log"
        )
        assert f"test {log} content" not in file_contents, f"❌ log file {log}.log not rotated"

        ls_output = await ls_in_unit(ops_test, unit.name, f"/var/log/mysql/archive_{log}/")
        assert len(ls_output) != 0, f"❌ archive directory is empty: {ls_output}"
