# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

from pytest_operator.plugin import OpsTest

from ..helpers import (
    get_primary_unit,
    get_process_pid,
)
from .high_availability_helpers import (
    clean_up_database_and_table,
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    get_application_name,
    insert_data_into_mysql_and_validate_replication,
    send_signal_to_pod_container_process,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


async def test_kill_db_process(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test to send a SIGKILL to the primary db process and ensure that the cluster self heals."""
    mysql_application_name = get_application_name(ops_test, "mysql")

    logger.info("Waiting until 3 mysql instances are online")
    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(ops_test, 3), (
        "The deployed mysql application is not fully online"
    )

    logger.info("Ensuring all units have continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )

    logger.info(f"Sending SIGKILL to unit {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test.model.info.name,
        primary.name,
        MYSQL_CONTAINER_NAME,
        MYSQLD_PROCESS_NAME,
        "SIGKILL",
    )

    # Wait for the SIGKILL above to take effect before continuing with test checks
    time.sleep(10)

    logger.info("Waiting until 3 mysql instances are online")
    assert await ensure_n_online_mysql_members(ops_test, 3), (
        "The mysql application is not fully online after sending SIGKILL to primary"
    )

    # ensure that the mysqld process got restarted and has a new process id
    new_mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert mysql_pid != new_mysql_pid, (
        "The mysql process id is the same after sending it a SIGKILL"
    )

    new_primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    assert primary.name != new_primary.name, (
        "The mysql primary has not been reelected after sending a SIGKILL"
    )

    logger.info("Ensuring all units have continuous writes incrementing")
    # ensure continuous writes still incrementing for all units
    async with ops_test.fast_forward():
        await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    # ensure that we are able to insert data into the primary and have it replicated to all units
    database_name, table_name = "test-kill-db-process", "data"
    await insert_data_into_mysql_and_validate_replication(
        ops_test, database_name, table_name, credentials
    )
    await clean_up_database_and_table(ops_test, database_name, table_name, credentials)
