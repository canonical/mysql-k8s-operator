#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest

from ..helpers import get_primary_unit
from .high_availability_helpers import (
    delete_pvcs,
    delete_pvs,
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    evict_pod,
    get_application_name,
    get_pod,
    get_pod_pvcs,
    get_pod_pvs,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 30 * 60


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_pod_eviction_and_pvc_deletion(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test behavior when node drains - pod is evicted and pvs are rotated."""
    mysql_application_name = get_application_name(ops_test, "mysql")

    logger.info("Waiting until 3 mysql instances are online")
    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application is not fully online"

    logger.info("Ensuring all units have continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    logger.info(f"Evicting primary node {primary.name} and deleting its PVCs")
    primary_pod = get_pod(ops_test, primary.name)
    primary_pod_pvcs = get_pod_pvcs(primary_pod)
    primary_pod_pvs = get_pod_pvs(primary_pod)
    evict_pod(primary_pod)
    delete_pvcs(primary_pod_pvcs)
    delete_pvs(primary_pod_pvs)

    async with ops_test.fast_forward():
        logger.info("Waiting for evicted primary pod to be rescheduled")
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
            wait_for_exact_units=3,
        )

    logger.info("Waiting until 3 mysql instances are online")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application is not fully online after primary pod eviction"

    logger.info("Ensuring all units have continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)
