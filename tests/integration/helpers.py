# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import itertools
import json
import secrets
import string
import subprocess
import tempfile
from typing import Dict, List, Optional

import mysql.connector
import yaml
from juju.unit import Unit
from mysql.connector.errors import (
    DatabaseError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, retry, stop_after_attempt, wait_fixed

from constants import CONTAINER_NAME, MYSQLD_SAFE_SERVICE, SERVER_CONFIG_USERNAME

from . import juju_
from .connector import MySQLConnector


def generate_random_string(length: int) -> str:
    """Generate a random string of the provided length.

    Args:
        length: the length of the random string to generate

    Returns:
        A random string comprised of letters and digits
    """
    choices = string.ascii_letters + string.digits
    return "".join([secrets.choice(choices) for i in range(length)])


async def get_unit_address(ops_test: OpsTest, unit_name: str) -> str:
    """Get unit IP address.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        IP address of the unit
    """
    status = await ops_test.model.get_status()
    return status["applications"][unit_name.split("/")[0]].units[unit_name]["address"]


async def get_cluster_status(ops_test: OpsTest, unit: Unit) -> Dict:
    """Get the cluster status by running the get-cluster-status action.

    Args:
        ops_test: The ops test framework
        unit: The unit on which to execute the action on

    Returns:
        A dictionary representing the cluster status
    """
    results = await juju_.run_action(unit, "get-cluster-status")
    return results.get("status", {})


async def get_leader_unit(ops_test: OpsTest, app_name: str) -> Optional[Unit]:
    leader_unit = None
    for unit in ops_test.model.applications[app_name].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
            break

    return leader_unit


async def get_relation_data(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
) -> list:
    """Returns a list that contains the relation-data.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        relation_name: name of the relation to get connection data from
    Returns:
        a list that contains the relation-data
    """
    # get available unit id for the desired application
    unit_names = [
        app_unit.name for app_unit in ops_test.model.applications[application_name].units
    ]
    assert len(unit_names) > 0
    unit_name = unit_names[0]

    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    assert raw_data, f"no unit info could be grabbed for {unit_name}"

    data = yaml.safe_load(raw_data)
    # Filter the data based on the relation name.
    relation_data = [v for v in data[unit_name]["relation-info"] if v["endpoint"] == relation_name]
    assert (
        relation_data
    ), f"no relation data could be grabbed on relation with endpoint {relation_name}"

    return relation_data


async def get_primary_unit(
    ops_test: OpsTest,
    unit: Unit,
    app_name: str,
) -> Optional[Unit]:
    """Helper to retrieve the primary unit.

    Args:
        ops_test: The ops test object passed into every test case
        unit: A unit on which to execute commands/queries/actions on
        app_name: The name of the test application

    Returns:
        A juju unit that is a MySQL primary
    """
    cluster_status = await get_cluster_status(ops_test, unit)

    primary_label = [
        label
        for label, member in cluster_status["defaultreplicaset"]["topology"].items()
        if member["mode"] == "r/w"
    ][0]
    primary_name = "/".join(primary_label.rsplit("-", 1))

    for unit in ops_test.model.applications[app_name].units:
        if unit.name == primary_name:
            return unit

    return None


async def execute_queries_on_unit(
    unit_address: str,
    username: str,
    password: str,
    queries: List[str],
    commit: bool = False,
) -> List:
    """Execute given MySQL queries on a unit.

    Args:
        unit_address: The public IP address of the unit to execute the queries on
        username: The MySQL username
        password: The MySQL password
        queries: A list of queries to execute
        commit: A keyword arg indicating whether there are any writes queries

    Returns:
        A list of rows that were potentially queried
    """
    connection = mysql.connector.connect(
        host=unit_address,
        user=username,
        password=password,
    )
    cursor = connection.cursor()

    for query in queries:
        cursor.execute(query)

    if commit:
        connection.commit()

    output = list(itertools.chain(*cursor.fetchall()))

    cursor.close()
    connection.close()

    return output


async def get_server_config_credentials(unit: Unit) -> Dict:
    """Helper to run an action to retrieve server config credentials.

    Args:
        unit: The juju unit on which to run the get-password action for server-config credentials

    Returns:
        A dictionary with the server config username and password
    """
    return await juju_.run_action(unit, "get-password", username=SERVER_CONFIG_USERNAME)


async def fetch_credentials(unit: Unit, username: str = None) -> Dict:
    """Helper to run an action to fetch credentials.

    Args:
        unit: The juju unit on which to run the get-password action for credentials

    Returns:
        A dictionary with the server config username and password
    """
    if username is None:
        return await juju_.run_action(unit, "get-password")
    else:
        return await juju_.run_action(unit, "get-password", username=username)


async def rotate_credentials(unit: Unit, username: str = None, password: str = None) -> Dict:
    """Helper to run an action to rotate credentials.

    Args:
        unit: The juju unit on which to run the set-password action for credentials

    Returns:
        A dictionary with the action result
    """
    if username is None:
        return await juju_.run_action(unit, "set-password")
    elif password is None:
        return await juju_.run_action(unit, "set-password", username=username)
    else:
        return await juju_.run_action(unit, "set-password", username=username, password=password)


async def scale_application(
    ops_test: OpsTest, application_name: str, desired_count: int, wait: bool = True
) -> None:
    """Scale a given application to the desired unit count.

    Args:
        ops_test: The ops test framework
        application_name: The name of the application
        desired_count: The number of units to scale to
        wait: Boolean indicating whether to wait until units
            reach desired count
    """
    await ops_test.model.applications[application_name].scale(desired_count)

    if desired_count > 0 and wait:
        async with ops_test.fast_forward("60s"):
            await ops_test.model.wait_for_idle(
                apps=[application_name],
                status="active",
                timeout=(15 * 60),
                wait_for_exact_units=desired_count,
                raise_on_blocked=True,
            )


def is_relation_joined(ops_test: OpsTest, endpoint_one: str, endpoint_two: str) -> bool:
    """Check if a relation is joined.

    Args:
        ops_test: The ops test object passed into every test case
        endpoint_one: The first endpoint of the relation
        endpoint_two: The second endpoint of the relation
    """
    for rel in ops_test.model.relations:
        endpoints = [endpoint.name for endpoint in rel.endpoints]
        if endpoint_one in endpoints and endpoint_two in endpoints:
            return True
    return False


def is_relation_broken(ops_test: OpsTest, endpoint_one: str, endpoint_two: str) -> bool:
    """Check if a relation is broken.

    Args:
        ops_test: The ops test object passed into every test case
        endpoint_one: The first endpoint of the relation
        endpoint_two: The second endpoint of the relation
    """
    for rel in ops_test.model.relations:
        endpoints = [endpoint.name for endpoint in rel.endpoints]
        if endpoint_one not in endpoints and endpoint_two not in endpoints:
            return True
    return False


async def app_name(ops_test: OpsTest) -> str:
    """Returns the name of the application running MySQL.

    This is important since not all deployments of the MySQL charm have the application name
    "mysql-k8s".

    Note: if multiple clusters are running MySQL this will return the one first found.
    """
    status = await ops_test.model.get_status()
    for app in ops_test.model.applications:
        # note that format of the charm field is not exactly "mysql-k8s" but instead takes the form
        # of `local:focal/mysql-6`
        if "mysql-k8s" in status["applications"][app]["charm"]:
            return app

    return None


@retry(stop=stop_after_attempt(8), wait=wait_fixed(15), reraise=True)
def is_connection_possible(credentials: Dict, **extra_opts) -> bool:
    """Test a connection to a MySQL server.

    Args:
        credentials: A dictionary with the credentials to test
        extra_opts: extra options for mysql connection
    """
    config = {
        "user": credentials["username"],
        "password": credentials["password"],
        "host": credentials["host"],
        "raise_on_warnings": False,
        "connection_timeout": 10,
        **extra_opts,
    }

    try:
        with MySQLConnector(config) as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0] == 1
    except (DatabaseError, InterfaceError, OperationalError, ProgrammingError):
        # Errors raised when the connection is not possible
        return False


async def get_process_pid(
    ops_test: OpsTest, unit_name: str, container_name: str, process: str
) -> Optional[int]:
    """Return the pid of a process running in a given unit.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit
        container_name: The name of the container in the unit
        process: The process name to search for

    Returns:
        A integer for the process id
    """
    get_pid_commands = [
        "ssh",
        "--container",
        container_name,
        unit_name,
        "pgrep",
        "-x",
        process,
    ]
    return_code, pid, _ = await ops_test.juju(*get_pid_commands)

    if return_code == 1:
        return None

    assert (
        return_code == 0
    ), f"Failed getting pid, unit={unit_name}, container={container_name}, process={process}"

    stripped_pid = pid.strip()
    if not stripped_pid:
        return -1

    return int(stripped_pid)


async def get_tls_ca(
    ops_test: OpsTest,
    unit_name: str,
) -> str:
    """Returns the TLS CA used by the unit.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        TLS CA or an empty string if there is no CA.
    """
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)
    # Filter the data based on the relation name.
    relation_data = [
        v for v in data[unit_name]["relation-info"] if v["endpoint"] == "certificates"
    ]
    if len(relation_data) == 0:
        return ""
    return json.loads(relation_data[0]["application-data"]["certificates"])[0].get("ca")


async def unit_file_md5(ops_test: OpsTest, unit_name: str, file_path: str) -> str:
    """Return md5 hash for given file.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit
        file_path: The path to the file

    Returns:
        md5sum hash string
    """
    try:
        _, md5sum_raw, _ = await ops_test.juju(
            "ssh", "--container", CONTAINER_NAME, unit_name, "md5sum", file_path
        )

        return md5sum_raw.strip().split()[0]

    except Exception:
        return None


async def stop_mysqld_service(ops_test: OpsTest, unit_name: str) -> None:
    """Stop the mysqld service.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit
    """
    await ops_test.juju(
        "ssh", "--container", CONTAINER_NAME, unit_name, "pebble", "stop", MYSQLD_SAFE_SERVICE
    )


async def start_mysqld_service(ops_test: OpsTest, unit_name: str) -> None:
    """Start the mysqld service.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit
    """
    await ops_test.juju(
        "ssh", "--container", CONTAINER_NAME, unit_name, "pebble", "start", MYSQLD_SAFE_SERVICE
    )


async def retrieve_database_variable_value(
    ops_test: OpsTest, unit: Unit, variable_name: str
) -> str:
    """Retrieve a database variable value as a string.

    Args:
        ops_test: The ops test framework instance
        unit: The unit to retrieve the variable
        variable_name: The name of the variable to retrieve
    Returns:
        The variable value (str)
    """
    unit_ip = await get_unit_address(ops_test, unit.name)

    server_config_creds = await get_server_config_credentials(unit)
    queries = [f"SELECT @@{variable_name};"]

    output = await execute_queries_on_unit(
        unit_ip, server_config_creds["username"], server_config_creds["password"], queries
    )

    return output[0]


async def start_mysqld_exporter(ops_test: OpsTest, unit: Unit) -> None:
    """Start mysqld exporter pebble service on the provided unit.

    Args:
        ops_test: The ops test framework
        unit: The unit to start mysqld exporter on
    """
    await ops_test.juju(
        "ssh",
        "--container",
        CONTAINER_NAME,
        unit.name,
        "pebble",
        "start",
        "mysqld_exporter",
    )


def get_unit_by_index(app_name: str, units: list, index: int):
    """Get unit by index.

    Args:
        app_name: Name of the application
        units: List of units
        index: index of the unit to get
    """
    for unit in units:
        if unit.name == f"{app_name}/{index}":
            return unit


async def delete_file_or_directory_in_unit(
    ops_test: OpsTest, unit_name: str, path: str, container_name: str = CONTAINER_NAME
) -> bool:
    """Delete a file in the provided unit.

    Args:
        ops_test: The ops test framework
        unit_name: The name unit on which to delete the file from
        container_name: The name of the container where the file or directory is
        path: The path of file or directory to delete

    Returns:
        boolean indicating success
    """
    if path.strip() in ["/", "."]:
        return

    try:
        return_code, _, _ = await ops_test.juju(
            "ssh",
            "--container",
            container_name,
            unit_name,
            "find",
            path,
            "-maxdepth",
            "1",
            "-delete",
        )

        return return_code == 0
    except Exception:
        return False


async def write_content_to_file_in_unit(
    ops_test: OpsTest, unit: Unit, path: str, content: str, container_name: str = CONTAINER_NAME
) -> None:
    """Write content to the file in the provided unit.

    Args:
        ops_test: The ops test framework
        unit: THe unit in which to write to file in
        path: The path at which to write the content to
        content: The content to write to the file
        container_name: The container where to write the file
    """
    pod_name = unit.name.replace("/", "-")

    with tempfile.NamedTemporaryFile(mode="w") as temp_file:
        temp_file.write(content)
        temp_file.flush()

        subprocess.run(
            [
                "microk8s.kubectl",
                "cp",
                "-n",
                ops_test.model.info.name,
                "-c",
                container_name,
                temp_file.name,
                f"{pod_name}:{path}",
            ],
            check=True,
        )


async def read_contents_from_file_in_unit(
    ops_test: OpsTest, unit: Unit, path: str, container_name: str = CONTAINER_NAME
) -> str:
    """Read contents from file in the provided unit.

    Args:
        ops_test: The ops test framework
        unit: The unit in which to read file from
        path: The path from which to read content from
        container_name: The container where the file exists

    Returns:
        the contents of the file
    """
    pod_name = unit.name.replace("/", "-")

    with tempfile.NamedTemporaryFile(mode="r+") as temp_file:
        subprocess.run(
            [
                "microk8s.kubectl",
                "cp",
                "-n",
                ops_test.model.info.name,
                "-c",
                container_name,
                f"{pod_name}:{path}",
                temp_file.name,
            ],
            check=True,
        )

        temp_file.seek(0)

        contents = ""
        for line in temp_file:
            contents += line
            contents += "\n"

    return contents


async def ls_la_in_unit(
    ops_test: OpsTest, unit_name: str, directory: str, container_name: str = CONTAINER_NAME
) -> list[str]:
    """Returns the output of ls -la in unit.

    Args:
        ops_test: The ops test framework
        unit_name: The name of unit in which to run ls -la
        path: The path from which to run ls -la
        container_name: The container where to run ls -la

    Returns:
        a list of files returned by ls -la
    """
    return_code, output, _ = await ops_test.juju(
        "ssh", "--container", container_name, unit_name, "ls", "-la", directory
    )
    assert return_code == 0

    ls_output = output.split("\n")[1:]

    return [
        line.strip("\r")
        for line in ls_output
        if len(line.strip()) > 0 and line.split()[-1] not in [".", ".."]
    ]


async def stop_running_log_rotate_dispatcher(ops_test: OpsTest, unit_name: str):
    """Stop running the log rotate dispatcher script.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested
    """
    # send KILL signal to log rotate dispatcher, which trigger shutdown process
    await ops_test.juju(
        "ssh",
        unit_name,
        "pkill",
        "-9",
        "-f",
        "/usr/bin/python3 scripts/log_rotate_dispatcher.py",
    )


async def stop_running_flush_mysql_job(
    ops_test: OpsTest, unit_name: str, container_name: str = CONTAINER_NAME
) -> None:
    """Stop running any logrotate jobs that may have been triggered by cron.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested
        container_name: The name of the container to be tested
    """
    # send KILL signal to log rotate process, which trigger shutdown process
    await ops_test.juju(
        "ssh",
        "--container",
        container_name,
        unit_name,
        "pkill",
        "-9",
        "-f",
        "logrotate -f /etc/logrotate.d/flush_mysql_logs",
    )

    # hold execution until process is stopped
    try:
        for attempt in Retrying(stop=stop_after_attempt(45), wait=wait_fixed(2)):
            with attempt:
                if await get_process_pid(ops_test, unit_name, container_name, "logrotate"):
                    raise Exception
    except RetryError:
        raise Exception("Failed to stop the flush_mysql_logs logrotate process.")


async def dispatch_custom_event_for_logrotate(ops_test: OpsTest, unit_name: str) -> None:
    """Dispatch the custom event to run logrotate.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested
    """
    _, juju_run, _ = await ops_test.juju(
        "ssh",
        unit_name,
        "which",
        "juju-run",
    )

    _, juju_exec, _ = await ops_test.juju(
        "ssh",
        unit_name,
        "which",
        "juju-exec",
    )

    dispatch_command = juju_exec.strip() or juju_run.strip()
    unit_label = unit_name.replace("/", "-")

    return_code, stdout, stderr = await ops_test.juju(
        "ssh",
        unit_name,
        dispatch_command,
        "JUJU_DISPATCH_PATH=hooks/rotate_mysql_logs",
        f"/var/lib/juju/agents/unit-{unit_label}/charm/dispatch",
    )

    assert return_code == 0
