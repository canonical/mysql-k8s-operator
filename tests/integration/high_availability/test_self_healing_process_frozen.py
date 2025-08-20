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
    get_process_stat,
    send_signal_to_pod_container_process,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


async def test_freeze_db_process(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test to send a SIGSTOP to the primary db process and ensure that the cluster self heals."""
    mysql_application_name = get_application_name(ops_test, "mysql")
    assert mysql_application_name, "mysql application name is not set"

    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(ops_test, 3), (
        "The deployed mysql application is not fully online"
    )

    logger.info("Ensuring that all units continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert (mysql_pid or -1) > 0, "mysql process id is not positive"

    logger.info(f"Sending SIGSTOP to unit {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test.model.info.name,
        primary.name,
        MYSQL_CONTAINER_NAME,
        MYSQLD_PROCESS_NAME,
        "SIGSTOP",
    )

    # ensure that the mysqld process is stopped after receiving the sigstop
    # T = stopped by job control signal
    # (see https://man7.org/linux/man-pages/man1/ps.1.html under PROCESS STATE CODES)
    mysql_process_stat_after_sigstop = await get_process_stat(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert "T" in mysql_process_stat_after_sigstop, "mysql process is not stopped after sigstop"

    remaining_online_units = [
        unit
        for unit in ops_test.model.applications[mysql_application_name].units
        if unit.name != primary.name
    ]

    logger.info("Waiting for new primary to be elected")

    # retring as it may take time for the cluster to recognize that the primary process is stopped
    for attempt in Retrying(stop=stop_after_delay(15 * 60), wait=wait_fixed(10)):
        with attempt:
            assert await ensure_n_online_mysql_members(ops_test, 2, remaining_online_units), (
                "The deployed mysql application does not have two online nodes"
            )

            new_primary = await get_primary_unit(
                ops_test, remaining_online_units[0], mysql_application_name
            )
            assert primary.name != new_primary.name, "new mysql primary was not elected"

    logger.info("Ensuring all remaining units continuous writes incrementing")

    async with ops_test.fast_forward():
        for attempt in Retrying(stop=stop_after_delay(15 * 60), wait=wait_fixed(10)):
            with attempt:
                await ensure_all_units_continuous_writes_incrementing(
                    ops_test, credentials=credentials, mysql_units=remaining_online_units
                )

    logger.info(f"Sending SIGCONT to {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test.model.info.name,
        primary.name,
        MYSQL_CONTAINER_NAME,
        MYSQLD_PROCESS_NAME,
        "SIGCONT",
    )

    # ensure that the mysqld process has started after receiving the sigstop
    # T = stopped by job control signal
    # R = running or runnable
    # S = interruptible sleep
    # I = idle kernel thread
    # (see https://man7.org/linux/man-pages/man1/ps.1.html under PROCESS STATE CODES)
    mysql_process_stat_after_sigcont = await get_process_stat(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert "T" not in mysql_process_stat_after_sigcont, (
        "mysql process is not started after sigcont"
    )
    assert (
        "R" in mysql_process_stat_after_sigcont
        or "S" in mysql_process_stat_after_sigcont
        or "I" in mysql_process_stat_after_sigcont
    ), "mysql process not running or sleeping after sigcont"

    new_mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert new_mysql_pid == mysql_pid, (
        "mysql process id is not the same as it was before process was stopped"
    )

    # wait for possible recovery of the old primary
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=False,
            timeout=TIMEOUT,
        )

    logger.info("Ensuring that there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(ops_test, 3, remaining_online_units), (
        "The deployed mysql application does not have three online nodes"
    )

    logger.info("Ensure all units continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)
