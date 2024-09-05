#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml

from ..helpers import delete_file_or_directory_in_unit, write_content_to_file_in_unit
from .high_availability_helpers import CLUSTER_NAME, delete_pod

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
TIMEOUT = 15 * 60


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_crash_during_cluster_setup(ops_test) -> None:
    mysql_charm = await ops_test.build_charm(".")

    config = {"cluster-name": CLUSTER_NAME, "profile": "testing"}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    logger.info("Deploying 3 units of mysql-k8s")
    mysql_application = await ops_test.model.deploy(
        mysql_charm,
        application_name=APP_NAME,
        config=config,
        resources=resources,
        num_units=3,
        base="ubuntu@22.04",
        trust=True,
    )

    logger.info("Waiting until application enters maintenance status")
    await ops_test.model.block_until(
        lambda: mysql_application.status == "maintenance", timeout=TIMEOUT
    )

    leader_unit = None
    non_leader_units = []

    for unit in mysql_application.units:
        if not await unit.is_leader_from_status():
            non_leader_units.append(unit)
        else:
            leader_unit = unit

    logger.info("Waiting until leader unit is creating cluster")
    await ops_test.model.block_until(
        lambda: leader_unit.workload_status == "maintenance"
        and leader_unit.agent_status == "executing"
        and "Creating cluster" in leader_unit.workload_status_message,
        timeout=TIMEOUT,
    )

    logger.info("Disabling non-leader units to avoid joining the cluster")
    for unit in non_leader_units:
        unit_label = unit.name.replace("/", "-")
        await write_content_to_file_in_unit(
            ops_test,
            unit,
            f"/var/lib/juju/agents/unit-{unit_label}/charm/disable",
            "",
            container_name="charm",
        )

    logger.info("Deleting pod")
    delete_pod(ops_test, leader_unit)

    logger.info("Waiting until pod rescheduled and cluster is set up again")
    await ops_test.model.block_until(
        lambda: leader_unit.workload_status == "active"
        and leader_unit.workload_status_message == "Primary",
        timeout=TIMEOUT,
    )

    logger.info("Removing disabled flag from non-leader units")
    for unit in non_leader_units:
        unit_label = unit.name.replace("/", "-")
        await delete_file_or_directory_in_unit(
            ops_test,
            unit.name,
            f"/var/lib/juju/agents/unit-{unit_label}/charm/disable",
            container_name="charm",
        )

    logger.info("Waiting until cluster is fully active")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=False,
        timeout=TIMEOUT,
        wait_for_exact_units=3,
    )
