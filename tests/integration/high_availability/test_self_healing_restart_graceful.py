# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from pytest_operator.plugin import OpsTest

from ..helpers import (
    execute_queries_on_unit,
    get_primary_unit,
    start_mysqld_service,
    stop_mysqld_service,
)
from .high_availability_helpers import (
    ensure_all_units_continuous_writes_incrementing,
    ensure_process_not_running,
    get_application_name,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


async def test_cluster_manual_rejoin(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """The cluster manual re-join test.

    A graceful restart is performed in one of the instances (choosing Primary to make it painful).
    In order to verify that the instance can come back ONLINE, after disabling automatic re-join
    """
    # Ensure continuous writes still incrementing for all units
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_app_name = get_application_name(ops_test, "mysql")
    mysql_units = ops_test.model.applications[mysql_app_name].units

    primary_unit = await get_primary_unit(ops_test, mysql_units[0], mysql_app_name)
    primary_address = await primary_unit.get_public_address()

    queries = [
        "SET PERSIST group_replication_autorejoin_tries=0",
    ]

    # Disable automatic re-join procedure
    execute_queries_on_unit(
        unit_address=primary_address,
        username=credentials["username"],
        password=credentials["password"],
        queries=queries,
        commit=True,
    )

    logger.info(f"Stopping mysqld on {primary_unit.name}")
    await stop_mysqld_service(ops_test, primary_unit.name)

    logger.info(f"Wait until mysqld stopped on {primary_unit.name}")
    await ensure_process_not_running(
        ops_test=ops_test,
        unit_name=primary_unit.name,
        container_name=MYSQL_CONTAINER_NAME,
        process=MYSQLD_PROCESS_NAME,
    )

    logger.info(f"Starting mysqld on {primary_unit.name}")
    await start_mysqld_service(ops_test, primary_unit.name)

    # Verify unit comes back active
    async with ops_test.fast_forward():
        logger.info("Waiting unit to be back online as secondary")
        await ops_test.model.block_until(
            lambda: primary_unit.workload_status == "active"
            and primary_unit.workload_status_message == "",
            timeout=TIMEOUT,
        )
        logger.info("Waiting unit to be back online.")
        await ops_test.model.block_until(
            lambda: primary_unit.workload_status == "active",
            timeout=TIMEOUT,
        )

    # Ensure continuous writes still incrementing for all units
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)
