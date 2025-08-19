# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
from typing import Optional

import pytest
from jubilant import Juju, all_active

from ..markers import juju3

CHARM_NAME = "mysql-k8s"

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


@juju3
@pytest.mark.abort_on_fail
def test_cluster_switchover(juju: Juju, highly_available_cluster) -> None:
    """Test that the primary node can be switched over."""
    logging.info("Testing cluster switchover...")
    app_name = get_app_name(juju, CHARM_NAME)
    assert app_name, "MySQL application not found in the cluster"

    app_units = get_app_units(juju, app_name)
    assert len(app_units) > 1, "Not enough units to perform a switchover"

    primary_unit = get_primary_unit_name(juju, next(iter(app_units)))
    assert primary_unit, "No primary unit found in the cluster"
    logging.info(f"Current primary unit: {primary_unit}")

    logging.info("Selecting a new primary unit for switchover...")
    app_units.discard(primary_unit)
    new_primary_unit = app_units.pop()
    logging.info(f"New primary unit selected: {new_primary_unit}")

    switchover_task = juju.run(new_primary_unit, "promote-to-primary", {"scope": "unit"})
    assert switchover_task.status == "completed", "Switchover failed"

    assert get_primary_unit_name(juju, primary_unit) == new_primary_unit, "Switchover failed"


@juju3
@pytest.mark.abort_on_fail
def test_cluster_failover_after_majority_loss(juju: Juju, highly_available_cluster) -> None:
    """Test the promote-to-primary command after losing the majority of nodes, with force flag."""
    app_name = get_app_name(juju, CHARM_NAME)
    assert app_name, "MySQL application not found in the cluster"

    app_units = get_app_units(juju, app_name)
    assert len(app_units) > 1, "Not enough units to perform a switchover"

    primary_unit = get_primary_unit_name(juju, next(iter(app_units)))
    assert primary_unit, "No primary unit found in the cluster"
    logging.info(f"Current primary unit: {primary_unit}")

    non_primary_units = app_units - {primary_unit}

    unit_to_promote = non_primary_units.pop()

    logging.info(f"Unit selected for promotion: {unit_to_promote}")

    logging.info("Simulate quorum loss")
    units_to_kill = [non_primary_units.pop(), primary_unit]
    kill_pods(juju, units_to_kill)

    juju.model_config({"update-status-hook-interval": "45s"})
    logging.info("Waiting to settle in error state")
    juju.wait(
        lambda status: status.apps[app_name].units[unit_to_promote].workload_status.current
        == "active"
        and status.apps[app_name].units[units_to_kill[0]].workload_status.message == "offline"
        and status.apps[app_name].units[units_to_kill[1]].workload_status.message == "offline",
        timeout=60 * 15,
        delay=15,
    )

    logging.info("Attempting to promote a unit to primary after quorum loss...")
    failover_task = juju.run(
        unit_to_promote,
        "promote-to-primary",
        {"scope": "unit", "force": True},
        wait=600,
    )

    juju.model_config({"update-status-hook-interval": "15s"})

    assert failover_task.status == "completed", "Switchover failed"
    logging.info("Waiting for all units to become active after switchover...")
    juju.wait(all_active, timeout=60 * 10, delay=5)

    assert get_primary_unit_name(juju, primary_unit) == unit_to_promote, "Failover failed"


def get_primary_unit_name(juju: Juju, mysql_unit) -> Optional[str]:
    """Get the current primary node of the cluster."""
    cluster_status_task = juju.run(mysql_unit, "get-cluster-status")
    assert cluster_status_task.status == "completed", "Failed to retrieve cluster status"
    for label, value in cluster_status_task.results["status"]["defaultreplicaset"][
        "topology"
    ].items():
        if value["memberrole"] == "primary":
            return label2name(label)


def get_app_name(juju: Juju, charm_name: str) -> Optional[str]:
    """Get the application name for the given charm."""
    status = juju.status()
    for app, value in status.apps.items():
        if value.charm_name == charm_name:
            return app


def get_app_units(juju: Juju, app_name: str) -> set[str]:
    """Get the units for the given application."""
    status = juju.status()
    assert app_name in status.apps, f"Application {app_name} not found in status"
    return set(status.apps[app_name].units.keys())


def kill_pods(juju: Juju, unit_names: list[str]) -> None:
    """Kill the unit pods simultaneously using kubectl."""
    pod_names = [name2label(unit) for unit in unit_names]
    cmd = [
        "kubectl",
        "delete",
        "pod",
        *pod_names,
        "-n",
        juju.model,
        "--grace-period=0",
        "--force",
    ]
    subprocess.run(cmd, check=True)


def label2name(label: str) -> str:
    """Convert a label to a unit name."""
    return label.rsplit("-", 1)[0] + "/" + label.rsplit("-", 1)[1]


def name2label(name: str) -> str:
    """Convert a unit name to a label."""
    return name.rsplit("/", 1)[0] + "-" + name.rsplit("/", 1)[1]
