# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from ..helpers import (
    get_primary_unit,
    get_process_pid,
)
from .high_availability_helpers import (
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    get_application_name,
    send_signal_to_pod_container_process,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


async def test_graceful_crash_of_primary(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test to send SIGTERM to primary instance and then verify recovery."""
    mysql_application_name = get_application_name(ops_test, "mysql")

    assert mysql_application_name, "mysql application name is not set"

    logger.info("Ensuring that there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    logger.info("Ensuring that all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )

    logger.info(f"Sending SIGTERM to unit {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test.model.info.name,
        primary.name,
        MYSQL_CONTAINER_NAME,
        MYSQLD_PROCESS_NAME,
        "SIGTERM",
    )

    new_mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert (
        new_mysql_pid == mysql_pid
    ), "mysql process id is not the same as it was before process was stopped"

    remaining_online_units = [
        unit
        for unit in ops_test.model.applications[mysql_application_name].units
        if unit.name != primary.name
    ]

    logger.info("Waiting until there are 3 online mysql instances again")
    # retrying as it may take time for the cluster to recognize that the primary process is stopped
    for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(10)):
        with attempt:
            assert await ensure_n_online_mysql_members(
                ops_test, 3
            ), "The deployed mysql application does not have three online nodes"

            new_primary = await get_primary_unit(
                ops_test, remaining_online_units[0], mysql_application_name
            )
            assert primary.name != new_primary.name, "new mysql primary was not elected"

    logger.info("Ensuring all instances have incrementing continuous writes")
    async with ops_test.fast_forward():
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(10)):
            with attempt:
                await ensure_all_units_continuous_writes_incrementing(
                    ops_test, credentials=credentials
                )
