#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import subprocess
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

import jubilant_backports
import kubernetes
import yaml
from jubilant_backports import CLIError, Juju
from jubilant_backports.statustypes import Status
from lightkube.core.client import Client
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Endpoints, PersistentVolume, PersistentVolumeClaim, Pod
from tenacity import (
    RetryError,
    Retrying,
    retry,
    stop_after_attempt,
    stop_after_delay,
    wait_fixed,
)

from constants import (
    CONTAINER_NAME,
    MYSQLD_SERVICE,
    SERVER_CONFIG_USERNAME,
)

from .helpers import execute_queries_on_unit

CHARM_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MINUTE_SECS = 60
TEST_DATABASE_NAME = "testing"

JujuModelStatusFn = Callable[[Status], bool]
JujuAppsStatusFn = Callable[[Status, str], bool]


def check_mysql_instances_online(
    juju: Juju,
    app_name: str,
    app_units: list[str] | None = None,
) -> bool:
    """Checks whether all MySQL cluster instances are online.

    Args:
        juju: The Juju instance
        app_name: The name of the application
        app_units: The list of application units to check
    """
    if not app_units:
        app_units = get_app_units(juju, app_name)

    mysql_cluster_status = get_mysql_cluster_status(juju, app_units[0])
    mysql_cluster_topology = mysql_cluster_status["defaultreplicaset"]["topology"]

    for unit_name in app_units:
        unit_label = get_mysql_instance_label(unit_name)
        if mysql_cluster_topology[unit_label]["status"] != "online":
            return False

    return True


def check_mysql_units_writes_increment(
    juju: Juju,
    app_name: str,
    app_units: list[str] | None = None,
) -> None:
    """Ensure that continuous writes is incrementing on all units.

    Also, ensure that all continuous writes up to the max written value is available
    on all units (ensure that no committed data is lost).
    """
    if not app_units:
        app_units = get_app_units(juju, app_name)

    app_primary = get_mysql_primary_unit(juju, app_name, app_units[0])
    app_max_value = get_mysql_max_written_value(juju, app_name, app_primary)

    for unit_name in app_units:
        for attempt in Retrying(
            reraise=True,
            stop=stop_after_delay(5 * MINUTE_SECS),
            wait=wait_fixed(10),
        ):
            with attempt:
                unit_max_value = get_mysql_max_written_value(juju, app_name, unit_name)
                assert unit_max_value > app_max_value, "Writes not incrementing"
                app_max_value = unit_max_value


def delete_k8s_pod(juju: Juju, unit_name: str) -> None:
    """Delete the K8s pod associated with the unit name."""
    client = Client()
    client.delete(
        res=Pod,
        name=get_mysql_instance_label(unit_name),
        namespace=juju.model,
    )


def exec_k8s_container_command(
    juju: Juju, unit_name: str, container_name: str, command: str
) -> None:
    """Send the specified signal to a pod container process.

    Args:
        juju: The juju instance to use.
        unit_name: The name of the unit to send signal to
        container_name: The name of the container to send signal to
        command: The command to execute
    """
    kubernetes.config.load_kube_config()

    response = kubernetes.stream.stream(
        kubernetes.client.api.core_v1_api.CoreV1Api().connect_get_namespaced_pod_exec,
        get_mysql_instance_label(unit_name),
        juju.model,
        container=container_name,
        command=command.split(),
        stdin=False,
        stdout=True,
        stderr=True,
        tty=False,
        _preload_content=False,
    )
    response.run_forever(
        timeout=5,
    )

    if response.returncode != 0:
        raise RuntimeError("Failed to execute command")


def get_k8s_stateful_set_partitions(juju: Juju, app_name: str) -> int:
    """Get the number of partitions in a Kubernetes stateful set."""
    client = Client()
    stateful_set = client.get(
        res=StatefulSet,
        name=app_name,
        namespace=juju.model,
    )

    return stateful_set.spec.updateStrategy.rollingUpdate.partition


def get_k8s_endpoint_addresses(juju: Juju, endpoint_name: str) -> list[str]:
    """Retrieve the addresses selected by a K8s endpoint."""
    client = Client()
    endpoint = client.get(
        res=Endpoints,
        name=endpoint_name,
        namespace=juju.model,
    )

    return [address.ip for subset in endpoint.subsets for address in subset.addresses]


def get_k8s_pod(juju: Juju, unit_name: str) -> Pod:
    """Retrieve the K8s pod associated with the unit name."""
    client = Client()

    return client.get(
        res=Pod,
        name=get_mysql_instance_label(unit_name),
        namespace=juju.model,
    )


def get_k8s_pod_pvcs(juju: Juju, unit_name: str) -> list[PersistentVolumeClaim]:
    """Retrieve the PVCs of a K8s pod."""
    client = Client()
    pod = client.get(
        res=Pod,
        name=get_mysql_instance_label(unit_name),
        namespace=juju.model,
    )

    pod_pvcs = []
    if pod.spec is None:
        return pod_pvcs

    for volume in pod.spec.volumes:
        if volume.persistentVolumeClaim is None:
            continue

        pod_pvcs.append(
            client.get(
                res=PersistentVolumeClaim,
                name=volume.persistentVolumeClaim.claimName,
                namespace=pod.metadata.namespace,
            )
        )

    return pod_pvcs


def get_k8s_pod_pvs(juju: Juju, unit_name: str) -> list[PersistentVolume]:
    """Retrieve the PVs of a K8s pod."""
    client = Client()
    pod = client.get(
        res=Pod,
        name=get_mysql_instance_label(unit_name),
        namespace=juju.model,
    )

    pod_pvs = []
    if pod.spec is None:
        return pod_pvs

    for volume in client.list(res=PersistentVolume, namespace=pod.metadata.namespace):
        if volume.spec.claimRef.name.endswith(pod.metadata.name):
            pod_pvs.append(volume)

    return pod_pvs


def get_app_leader(juju: Juju, app_name: str) -> str:
    """Get the leader unit for the given application."""
    model_status = juju.status()
    app_status = model_status.apps[app_name]
    for name, status in app_status.units.items():
        if status.leader:
            return name

    raise Exception("No leader unit found")


def get_app_name(juju: Juju, charm_name: str) -> str | None:
    """Get the application name for the given charm."""
    model_status = juju.status()
    app_statuses = model_status.apps
    for name, status in app_statuses.items():
        if status.charm_name == charm_name:
            return name

    raise Exception("No application name found")


def get_app_units(juju: Juju, app_name: str) -> list[str]:
    """Get the units for the given application."""
    model_status = juju.status()
    app_status = model_status.apps[app_name]
    return list(app_status.units)


def scale_app_units(juju: Juju, app_name: str, num_units: int) -> None:
    """Scale a given application to a number of units."""
    app_units = get_app_units(juju, app_name)
    app_units_diff = num_units - len(app_units)

    scale_func = None
    if app_units_diff > 0:
        scale_func = juju.add_unit
    if app_units_diff < 0:
        scale_func = juju.remove_unit
    if app_units_diff == 0:
        return

    scale_func(app_name, num_units=abs(app_units_diff))

    juju.wait(
        ready=lambda status: len(status.apps[app_name].units) == num_units,
        timeout=20 * MINUTE_SECS,
    )
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, app_name),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )


def get_model_debug_logs(juju: Juju, log_level: str, log_lines: int = 100) -> str:
    """Return the juju logs from a specific model.

    Args:
        juju: The juju instance to use.
        log_level: The logging level to return messages from
        log_lines: The maximum lines to return at once
    """
    return subprocess.check_output(
        [
            "juju",
            "debug-log",
            f"--model={juju.model}",
            f"--level={log_level}",
            f"--limit={log_lines}",
        ],
        text=True,
    )


def get_unit_address(juju: Juju, app_name: str, unit_name: str) -> str:
    """Get the application unit IP."""
    model_status = juju.status()
    app_status = model_status.apps[app_name]
    for name, status in app_status.units.items():
        if name == unit_name:
            return status.address

    raise Exception("No application unit found")


def get_unit_by_number(juju: Juju, app_name: str, unit_number: int) -> str:
    """Get unit by number."""
    model_status = juju.status()
    app_status = model_status.apps[app_name]
    for name in app_status.units:
        if name == f"{app_name}/{unit_number}":
            return name

    raise Exception("No application unit found")


def get_unit_info(juju: Juju, unit_name: str) -> dict:
    """Return a dictionary with the show-unit data."""
    output = subprocess.check_output(
        ["juju", "show-unit", f"--model={juju.model}", "--format=json", unit_name],
        text=True,
    )

    return json.loads(output)


def get_unit_process_id(juju: Juju, unit_name: str, process_name: str) -> int | None:
    """Return the pid of a process running in a given unit."""
    try:
        output = juju.ssh(
            command=f"pgrep -x {process_name}",
            target=unit_name,
            container=CONTAINER_NAME,
        )

        return int(output.strip())
    except CLIError:
        return None


def get_relation_data(juju: Juju, app_name: str, rel_name: str) -> list[dict]:
    """Returns a list that contains the relation-data.

    Args:
        juju: The juju instance to use.
        app_name: The name of the application
        rel_name: name of the relation to get connection data from

    Returns:
        A list that contains the relation-data
    """
    app_leader = get_app_leader(juju, app_name)
    app_leader_info = get_unit_info(juju, app_leader)
    if not app_leader_info:
        raise ValueError(f"No unit info could be grabbed for unit {app_leader}")

    relation_data = [
        value
        for value in app_leader_info[app_leader]["relation-info"]
        if value["endpoint"] == rel_name
    ]
    if not relation_data:
        raise ValueError(f"No relation data could be grabbed for relation {rel_name}")

    return relation_data


@retry(stop=stop_after_attempt(30), wait=wait_fixed(5), reraise=True)
def get_mysql_cluster_status(juju: Juju, unit: str, cluster_set: bool = False) -> dict:
    """Get the cluster status by running the get-cluster-status action.

    Args:
        juju: The juju instance to use.
        unit: The unit on which to execute the action on
        cluster_set: Whether to get the cluster-set instead (optional)

    Returns:
        A dictionary representing the cluster status
    """
    task = juju.run(
        unit=unit,
        action="get-cluster-status",
        params={"cluster-set": cluster_set},
        wait=5 * MINUTE_SECS,
    )
    task.raise_on_failure()

    return task.results["status"]


def get_mysql_instance_label(unit_name: str) -> str:
    """Builds a MySQL instance label out of a Juju unit name."""
    return "-".join(unit_name.rsplit("/", 1))


def get_mysql_unit_name(instance_label: str) -> str:
    """Builds a Juju unit name out of a MySQL instance label."""
    return "/".join(instance_label.rsplit("-", 1))


def get_mysql_primary_unit(juju: Juju, app_name: str, unit_name: str | None = None) -> str:
    """Get the current primary node of the cluster."""
    if unit_name is None:
        unit_name = get_app_leader(juju, app_name)

    mysql_cluster_status = get_mysql_cluster_status(juju, unit_name)
    mysql_cluster_topology = mysql_cluster_status["defaultreplicaset"]["topology"]

    for label, value in mysql_cluster_topology.items():
        if value["memberrole"] == "primary":
            return get_mysql_unit_name(label)

    raise Exception("No MySQL primary node found")


def get_mysql_server_credentials(
    juju: Juju, unit_name: str, username: str = SERVER_CONFIG_USERNAME
) -> dict[str, str]:
    """Helper to run an action to retrieve server config credentials.

    Args:
        juju: The Juju model
        unit_name: The juju unit on which to run the get-password action for server-config credentials
        username: The username to use

    Returns:
        A dictionary with the server config username and password
    """
    credentials_task = juju.run(
        unit=unit_name,
        action="get-password",
        params={"username": username},
    )
    credentials_task.raise_on_failure()

    return credentials_task.results


def rotate_mysql_server_credentials(
    juju: Juju,
    unit_name: str,
    username: str = SERVER_CONFIG_USERNAME,
    password: str | None = None,
) -> None:
    """Helper to run an action to rotate server config credentials.

    Args:
        juju: The Juju model
        unit_name: The juju unit on which to run the rotate-password action for server-config credentials
        username: The username to rotate the password for
        password: The new password to set
    """
    params = {"username": username}
    if password is not None:
        params["password"] = password

    rotate_task = juju.run(
        unit=unit_name,
        action="set-password",
        params=params,
    )
    rotate_task.raise_on_failure()


def get_mysql_max_written_value(juju: Juju, app_name: str, unit_name: str) -> int:
    """Retrieve the max written value in the MySQL database.

    Args:
        juju: The Juju model.
        app_name: The application name.
        unit_name: The unit name.
    """
    credentials = get_mysql_server_credentials(juju, unit_name)

    output = execute_queries_on_unit(
        get_unit_address(juju, app_name, unit_name),
        credentials["username"],
        credentials["password"],
        ["SELECT MAX(number) FROM `continuous_writes`.`data`;"],
    )
    return output[0]


def get_mysql_variable_value(juju: Juju, app_name: str, unit_name: str, variable_name: str) -> str:
    """Retrieve a database variable value as a string.

    Args:
        juju: The Juju model.
        app_name: The application name.
        unit_name: The unit name.
        variable_name: The variable name.
    """
    credentials = get_mysql_server_credentials(juju, unit_name)

    output = execute_queries_on_unit(
        get_unit_address(juju, app_name, unit_name),
        credentials["username"],
        credentials["password"],
        [f"SELECT @@{variable_name};"],
    )
    return output[0]


@contextmanager
def update_interval(juju: Juju, interval: str) -> Generator:
    """Temporarily speed up update-status firing rate for the current model."""
    update_interval_key = "update-status-hook-interval"
    update_interval_val = juju.model_config()[update_interval_key]

    juju.model_config({update_interval_key: interval})
    try:
        yield
    finally:
        juju.model_config({update_interval_key: update_interval_val})


def insert_mysql_test_data(juju: Juju, app_name: str, table_name: str, value: str) -> None:
    """Insert data into the MySQL database.

    Args:
        juju: The Juju model.
        app_name: The application name.
        table_name: The database table name.
        value: The value to insert.
    """
    mysql_leader = get_app_leader(juju, app_name)
    mysql_primary = get_mysql_primary_unit(juju, app_name)

    credentials = get_mysql_server_credentials(juju, mysql_leader)

    insert_queries = [
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DATABASE_NAME}`",
        f"CREATE TABLE IF NOT EXISTS `{TEST_DATABASE_NAME}`.`{table_name}` (id VARCHAR(255), PRIMARY KEY (id))",
        f"INSERT INTO `{TEST_DATABASE_NAME}`.`{table_name}` (id) VALUES ('{value}')",
    ]

    execute_queries_on_unit(
        get_unit_address(juju, app_name, mysql_primary),
        credentials["username"],
        credentials["password"],
        insert_queries,
        commit=True,
    )


def remove_mysql_test_data(juju: Juju, app_name: str, table_name: str) -> None:
    """Remove data into the MySQL database.

    Args:
        juju: The Juju model.
        app_name: The application name.
        table_name: The database table name.
    """
    mysql_leader = get_app_leader(juju, app_name)
    mysql_primary = get_mysql_primary_unit(juju, app_name)

    credentials = get_mysql_server_credentials(juju, mysql_leader)

    remove_queries = [
        f"DROP TABLE IF EXISTS `{TEST_DATABASE_NAME}`.`{table_name}`",
        f"DROP DATABASE IF EXISTS `{TEST_DATABASE_NAME}`",
    ]

    execute_queries_on_unit(
        get_unit_address(juju, app_name, mysql_primary),
        credentials["username"],
        credentials["password"],
        remove_queries,
        commit=True,
    )


def verify_mysql_test_data(juju: Juju, app_name: str, table_name: str, value: str) -> None:
    """Verifies data into the MySQL database.

    Args:
        juju: The Juju model.
        app_name: The application name.
        table_name: The database table name.
        value: The value to check against.
    """
    mysql_app_leader = get_app_leader(juju, app_name)
    mysql_app_units = get_app_units(juju, app_name)

    credentials = get_mysql_server_credentials(juju, mysql_app_leader)

    select_queries = [
        f"SELECT id FROM `{TEST_DATABASE_NAME}`.`{table_name}` WHERE id = '{value}'",
    ]

    for unit_name in mysql_app_units:
        for attempt in Retrying(
            reraise=True,
            stop=stop_after_delay(5 * MINUTE_SECS),
            wait=wait_fixed(10),
        ):
            with attempt:
                output = execute_queries_on_unit(
                    get_unit_address(juju, app_name, unit_name),
                    credentials["username"],
                    credentials["password"],
                    select_queries,
                )
                assert output[0] == value


def start_mysqld_service(juju: Juju, unit_name: str) -> None:
    """Start the mysqld service.

    Args:
        juju: The Juju model.
        unit_name: The name of the unit
    """
    juju.ssh(
        command=f"pebble start {MYSQLD_SERVICE}",
        target=unit_name,
        container=CONTAINER_NAME,
    )

    # Hold execution until process is started
    for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(5)):
        with attempt:
            if get_unit_process_id(juju, unit_name, MYSQLD_SERVICE) is None:
                raise Exception("Failed to start the mysqld process")


def stop_mysqld_service(juju: Juju, unit_name: str) -> None:
    """Stop the mysqld service.

    Args:
        juju: The Juju model.
        unit_name: The name of the unit
    """
    juju.ssh(
        command=f"pebble stop {MYSQLD_SERVICE}",
        target=unit_name,
        container=CONTAINER_NAME,
    )

    # Hold execution until process is stopped
    for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(5)):
        with attempt:
            if get_unit_process_id(juju, unit_name, MYSQLD_SERVICE) is not None:
                raise Exception("Failed to stop the mysqld process")


def insert_mysql_data_and_validate_replication(
    juju: Juju,
    app_name: str,
    database_name: str,
    table_name: str,
    value: str,
    credentials: dict,
) -> None:
    """Inserts data into the mysql cluster and validates its replication.

    Args:
        juju: The Juju model.
        app_name: The application name.
        database_name: The database name.
        table_name: The table name.
        value: The value to insert.
        credentials: The credentials to authenticate.
    """
    primary_unit_name = get_mysql_primary_unit(juju, app_name)

    insert_value_sql = [
        f"CREATE DATABASE IF NOT EXISTS `{database_name}`",
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{table_name}` (id varchar(255), primary key (id))",
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{value}')",
    ]

    execute_queries_on_unit(
        get_unit_address(juju, app_name, primary_unit_name),
        credentials["username"],
        credentials["password"],
        insert_value_sql,
        commit=True,
    )

    select_value_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{value}'",
    ]

    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
            with attempt:
                for unit_name in get_app_units(juju, app_name):
                    unit_address = get_unit_address(juju, app_name, unit_name)

                    output = execute_queries_on_unit(
                        unit_address,
                        credentials["username"],
                        credentials["password"],
                        select_value_sql,
                    )
                    assert output[0] == value
    except RetryError as exc:
        raise RuntimeError("Cannot query inserted data from all units") from exc


def wait_for_apps_status(jubilant_status_func: JujuAppsStatusFn, *apps: str) -> JujuModelStatusFn:
    """Waits for Juju agents to be idle, and for applications to reach a certain status.

    Args:
        jubilant_status_func: The Juju apps status function to wait for.
        apps: The applications to wait for.

    Returns:
        Juju model status function.
    """
    return lambda status: all((
        jubilant_backports.all_agents_idle(status, *apps),
        jubilant_status_func(status, *apps),
    ))


def wait_for_unit_status(app_name: str, unit_name: str, unit_status: str) -> JujuModelStatusFn:
    """Returns whether a Juju unit to have a specific status."""
    return lambda status: (
        status.apps[app_name].units[unit_name].workload_status.current == unit_status
    )


def wait_for_unit_message(app_name: str, unit_name: str, unit_message: str) -> JujuModelStatusFn:
    """Returns whether a Juju unit to have a specific message."""
    return lambda status: (
        status.apps[app_name].units[unit_name].workload_status.message == unit_message
    )
