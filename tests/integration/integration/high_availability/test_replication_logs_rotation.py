# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path

import jubilant_backports
import pytest
from jubilant_backports import CLIError, Juju
from tenacity import (
    Retrying,
    stop_after_attempt,
    wait_fixed,
)

from constants import CONTAINER_NAME, MYSQL_LOG_DIR

from ...helpers_ha import (
    CHARM_METADATA,
    get_app_leader,
    get_mysql_instance_label,
    get_unit_process_id,
    wait_for_apps_status,
)

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_TEST_APP_NAME = "mysql-test-app"

MINUTE_SECS = 60


@pytest.mark.abort_on_fail
def test_deploy_highly_available_cluster(juju: Juju, charm: str) -> None:
    """Simple test to ensure that the MySQL and application charms get deployed."""
    logging.info("Deploying MySQL cluster")
    juju.deploy(
        charm=charm,
        app=MYSQL_APP_NAME,
        base="ubuntu@22.04",
        config={"profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        num_units=3,
    )
    juju.deploy(
        charm=MYSQL_TEST_APP_NAME,
        app=MYSQL_TEST_APP_NAME,
        base="ubuntu@22.04",
        channel="latest/edge",
        config={"sleep_interval": 300},
        num_units=1,
    )

    juju.integrate(
        f"{MYSQL_APP_NAME}:database",
        f"{MYSQL_TEST_APP_NAME}:database",
    )

    logging.info("Wait for applications to become active")
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, MYSQL_APP_NAME, MYSQL_TEST_APP_NAME
        ),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_log_rotation(juju: Juju) -> None:
    """Test the log rotation of text files."""
    log_types = ["error", "audit"]

    mysql_app_leader = get_app_leader(juju, MYSQL_APP_NAME)
    mysql_app_leader_label = get_mysql_instance_label(mysql_app_leader)

    logging.info("Overwriting the log rotate dispatcher script")
    write_unit_file(
        juju=juju,
        unit_name=mysql_app_leader,
        container="charm",
        file_path=f"/var/lib/juju/agents/unit-{mysql_app_leader_label}/charm/scripts/log_rotate_dispatcher.py",
        file_data="exit(0)\n",
    )

    logging.info("Stopping the log rotate dispatcher")
    stop_log_rotate_dispatcher(juju, mysql_app_leader)

    for log_type in log_types:
        logging.info("Removing existing archive directories")
        delete_unit_file(
            juju=juju,
            unit_name=mysql_app_leader,
            container=CONTAINER_NAME,
            file_path=f"{MYSQL_LOG_DIR}/archive_{log_type}",
        )

        logging.info("Writing some data to the text log files")
        write_unit_file(
            juju=juju,
            unit_name=mysql_app_leader,
            container=CONTAINER_NAME,
            file_path=f"{MYSQL_LOG_DIR}/{log_type}.log",
            file_data=f"{log_type} content",
        )

    logging.info("Dispatching custom event to rotate logs")
    start_log_rotate_dispatcher(juju, mysql_app_leader)

    logging.info("Ensuring log files were rotated")
    for log_type in log_types:
        active_log_file_data = read_unit_file(
            juju=juju,
            unit_name=mysql_app_leader,
            container=CONTAINER_NAME,
            file_path=f"{MYSQL_LOG_DIR}/{log_type}.log",
        )
        assert f"{log_type} content" not in active_log_file_data

        archive_log_dir = f"{MYSQL_LOG_DIR}/archive_{log_type}"
        archive_log_files_listed = list_unit_files(
            juju=juju,
            unit_name=mysql_app_leader,
            container=CONTAINER_NAME,
            file_path=archive_log_dir,
        )

        assert len(archive_log_files_listed) == 1


def delete_unit_file(juju: Juju, unit_name: str, container: str, file_path: str) -> None:
    """Delete a path in the provided unit.

    Args:
        juju: The Juju instance
        unit_name: The unit on which to delete the file
        container: The container on which to delete the file
        file_path: The path or file to delete
    """
    if file_path.strip() in ["/", "."]:
        return

    juju.ssh(
        command=f"find {file_path} -maxdepth 1 -delete",
        container=container,
        target=unit_name,
    )


def list_unit_files(juju: Juju, unit_name: str, container: str, file_path: str) -> list[str]:
    """Returns the list of files in the given path.

    Args:
        juju: The Juju instance
        unit_name: The unit in which to list the files
        container: The container in which to list the files
        file_path: The path at which to list the files
    """
    output = juju.ssh(
        command=f"ls -la {file_path}",
        container=container,
        target=unit_name,
    )

    output = output.split("\n")[1:]

    return [
        line.strip("\r")
        for line in output
        if len(line.strip()) > 0 and line.split()[-1] not in [".", ".."]
    ]


def read_unit_file(juju: Juju, unit_name: str, container: str, file_path: str) -> str:
    """Read contents from file in the provided unit.

    Args:
        juju: The Juju instance
        unit_name: The name of the unit to read the file from
        container: The name of the container to read the file from
        file_path: The path of the unit to read the file
    """
    pod_name = get_mysql_instance_label(unit_name)

    with tempfile.NamedTemporaryFile(mode="r+", dir=Path.home()) as temp_file:
        subprocess.run(
            [
                "microk8s.kubectl",
                "cp",
                f"--namespace={juju.model}",
                f"--container={container}",
                f"{pod_name}:{file_path}",
                f"{temp_file.name}",
            ],
        )
        contents = temp_file.read()

    return contents


def write_unit_file(juju: Juju, unit_name: str, container: str, file_path: str, file_data: str):
    """Write content to the file in the provided unit.

    Args:
        juju: The Juju instance
        unit_name: The name of the unit to write the file into
        container: The name of the container to write the file into
        file_path: The path of the container to write the file
        file_data: The data to write to the file.
    """
    pod_name = get_mysql_instance_label(unit_name)

    with tempfile.NamedTemporaryFile(mode="w", dir=Path.home()) as temp_file:
        temp_file.write(file_data)
        temp_file.flush()

        subprocess.check_call(
            [
                "microk8s.kubectl",
                "cp",
                f"--namespace={juju.model}",
                f"--container={container}",
                f"{temp_file.name}",
                f"{pod_name}:{file_path}",
            ],
        )


def start_log_rotate_dispatcher(juju: Juju, unit_name: str) -> None:
    """Start the logrotate dispatcher."""
    pod_name = get_mysql_instance_label(unit_name)

    dispatch_command = None
    for command in ("juju-exec", "juju-run"):
        with suppress(CLIError):
            dispatch_command = juju.ssh(command=f"which {command}", target=unit_name).strip()
        if dispatch_command is not None:
            break

    dispatch_hook = "hooks/rotate_mysql_logs"
    dispatch_path = f"/var/lib/juju/agents/unit-{pod_name}/charm/dispatch"

    juju.ssh(
        command=f"{dispatch_command} JUJU_DISPATCH_PATH={dispatch_hook} {dispatch_path}",
        target=unit_name,
    )


def stop_log_rotate_dispatcher(juju: Juju, unit_name: str) -> None:
    """Stop the logrotate dispatcher."""
    juju.exec(
        command="pkill -f log_rotate_dispatcher.py --signal SIGKILL",
        unit=unit_name,
    )

    # Hold execution until process is stopped
    for attempt in Retrying(stop=stop_after_attempt(45), wait=wait_fixed(2)):
        with attempt:
            process = "/usr/bin/python3 scripts/log_rotate_dispatcher.py"
            if get_unit_process_id(juju, unit_name, process) is not None:
                raise Exception("Failed to stop the flush_mysql_logs logrotate process")
