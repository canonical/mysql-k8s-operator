# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from ..helpers import (
    get_cluster_status,
    get_process_pid,
    start_mysqld_service,
    stop_mysqld_service,
)
from .high_availability_helpers import (
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    ensure_process_not_running,
    get_application_name,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


async def test_graceful_full_cluster_crash_test(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test to send SIGTERM to all units and then ensure that the cluster recovers."""
    mysql_application_name = get_application_name(ops_test, "mysql")
    assert mysql_application_name, "mysql application name is not set"

    logger.info("Ensure there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    logger.info("Ensure that all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_units = ops_test.model.applications[mysql_application_name].units

    unit_mysqld_pids = {}
    logger.info("Get mysqld pids on all instances")
    for unit in mysql_units:
        pid = await get_process_pid(ops_test, unit.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME)
        assert (pid or -1) > 1, "mysql process id is not known/positive"

        unit_mysqld_pids[unit.name] = pid

    for unit in mysql_units:
        logger.info(f"Stopping mysqld on {unit.name}")
        await stop_mysqld_service(ops_test, unit.name)

    logger.info("Wait until mysqld stopped on all instances")
    for attempt in Retrying(stop=stop_after_delay(300), wait=wait_fixed(30)):
        with attempt:
            for unit in mysql_units:
                await ensure_process_not_running(
                    ops_test, unit.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
                )
    for unit in mysql_units:
        logger.info(f"Starting mysqld on {unit.name}")
        await start_mysqld_service(ops_test, unit.name)

    async with ops_test.fast_forward("60s"):
        logger.info("Block until all in maintenance/offline")
        await ops_test.model.block_until(
            lambda: all(unit.workload_status == "maintenance" for unit in mysql_units),
            timeout=TIMEOUT,
        )

        logger.info("Wait all members to recover")
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=False,
            timeout=TIMEOUT,
            idle_period=30,
        )

    for unit in mysql_units:
        new_pid = await get_process_pid(
            ops_test, unit.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
        )
        assert new_pid > unit_mysqld_pids[unit.name], "The mysqld process did not restart"

    cluster_status = await get_cluster_status(mysql_units[0])
    for member in cluster_status["defaultreplicaset"]["topology"].values():
        assert member["status"] == "online"

    logger.info("Ensure all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)
