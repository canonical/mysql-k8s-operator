#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from collections.abc import Callable

import jubilant
import kubernetes
from jubilant import Juju
from jubilant.statustypes import Status, UnitStatus
from lightkube.core.client import Client
from lightkube.resources.apps_v1 import StatefulSet
from tenacity import Retrying, stop_after_delay, wait_fixed

from constants import SERVER_CONFIG_USERNAME

from ..helpers import execute_queries_on_unit

MINUTE_SECS = 60

JujuModelStatusFn = Callable[[Status], bool]
JujuAppsStatusFn = Callable[[Status, str], bool]


def check_mysql_units_writes_increment(juju: Juju, app_name: str) -> None:
    """Ensure that continuous writes is incrementing on all units.

    Also, ensure that all continuous writes up to the max written value is available
    on all units (ensure that no committed data is lost).
    """
    mysql_app_units = get_app_units(juju, app_name)
    mysql_app_primary = get_mysql_primary_unit(juju, app_name)

    app_max_value = get_mysql_max_written_value(juju, app_name, mysql_app_primary)

    juju.model_config({"update-status-hook-interval": "15s"})
    for unit_name in mysql_app_units:
        for attempt in Retrying(
            reraise=True,
            stop=stop_after_delay(5 * MINUTE_SECS),
            wait=wait_fixed(10),
        ):
            with attempt:
                unit_max_value = get_mysql_max_written_value(juju, app_name, unit_name)
                assert unit_max_value > app_max_value, "Writes not incrementing"
                app_max_value = unit_max_value


def exec_k8s_container_command(
    juju: Juju, unit_name: str, container_name: str, command: str
) -> int:
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

    return response.returncode


def get_k8s_stateful_set_partitions(juju: Juju, app_name: str) -> int:
    """Get the number of partitions in a Kubernetes stateful set."""
    client = Client()
    stateful_set = client.get(
        res=StatefulSet,
        namespace=juju.model,
        name=app_name,
    )

    return stateful_set.spec.updateStrategy.rollingUpdate.partition


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


def get_app_units(juju: Juju, app_name: str) -> dict[str, UnitStatus]:
    """Get the units for the given application."""
    model_status = juju.status()
    app_status = model_status.apps[app_name]
    return app_status.units


def get_unit_address(juju: Juju, app_name: str, unit_name: str) -> str:
    """Get the application unit IP."""
    model_status = juju.status()
    app_status = model_status.apps[app_name]
    for name, status in app_status.units.items():
        if name == unit_name:
            return status.address

    raise Exception("No application unit found")


def get_unit_by_index(juju: Juju, app_name: str, index: int) -> str:
    """Get unit by index."""
    model_status = juju.status()
    app_status = model_status.apps[app_name]
    for name in app_status.units:
        if name == f"{app_name}/{index}":
            return name

    raise Exception("No application unit found")


def get_mysql_cluster_status(juju: Juju, unit: str, cluster_set: bool | None = False) -> dict:
    """Get the cluster status by running the get-cluster-status action.

    Args:
        juju: The juju instance to use.
        unit: The unit on which to execute the action on
        cluster_set: Whether to get the cluster-set instead

    Returns:
        A dictionary representing the cluster status
    """
    task = juju.run(
        unit=unit,
        action="get-cluster-status",
        params={"cluster-set": bool(cluster_set)},
        wait=5 * MINUTE_SECS,
    )
    task.raise_on_failure()

    return task.results.get("status", {})


def get_mysql_instance_label(unit_name: str) -> str:
    """Builds a MySQL instance label out of a Juju unit name."""
    return "-".join(unit_name.rsplit("/", 1))


def get_mysql_unit_name(instance_label: str) -> str:
    """Builds a Juju unit name out of a MySQL instance label."""
    return "/".join(instance_label.rsplit("-", 1))


def get_mysql_primary_unit(juju: Juju, app_name: str) -> str:
    """Get the current primary node of the cluster."""
    mysql_primary = get_app_leader(juju, app_name)
    mysql_cluster_status = get_mysql_cluster_status(juju, mysql_primary)
    mysql_cluster_topology = mysql_cluster_status["defaultreplicaset"]["topology"]

    for label, value in mysql_cluster_topology.items():
        if value["memberrole"] == "primary":
            return get_mysql_unit_name(label)

    raise Exception("No MySQL primary node found")


def get_mysql_max_written_value(juju: Juju, app_name: str, unit_name: str) -> int:
    """Retrieve the max written value in the MySQL database.

    Args:
        juju: The Juju model.
        app_name: The application name.
        unit_name: The unit name.
    """
    credentials_task = juju.run(
        unit=unit_name,
        action="get-password",
        params={"username": SERVER_CONFIG_USERNAME},
    )
    credentials_task.raise_on_failure()

    output = execute_queries_on_unit(
        get_unit_address(juju, app_name, unit_name),
        credentials_task.results["username"],
        credentials_task.results["password"],
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
    credentials_task = juju.run(
        unit=unit_name,
        action="get-password",
        params={"username": SERVER_CONFIG_USERNAME},
    )
    credentials_task.raise_on_failure()

    output = execute_queries_on_unit(
        get_unit_address(juju, app_name, unit_name),
        credentials_task.results["username"],
        credentials_task.results["password"],
        [f"SELECT @@{variable_name};"],
    )
    return output[0]


def wait_for_apps_status(jubilant_status_func: JujuAppsStatusFn, *apps: str) -> JujuModelStatusFn:
    """Waits for Juju agents to be idle, and for applications to reach a certain status.

    Args:
        jubilant_status_func: The Juju apps status function to wait for.
        apps: The applications to wait for.

    Returns:
        Juju model status function.
    """
    return lambda status: all((
        jubilant.all_agents_idle(status, *apps),
        jubilant_status_func(status, *apps),
    ))
