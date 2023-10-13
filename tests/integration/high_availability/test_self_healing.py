#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import lightkube
import pytest
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from ..helpers import (
    get_cluster_status,
    get_primary_unit,
    get_process_pid,
    scale_application,
    start_mysqld_service,
    stop_mysqld_service,
)
from .high_availability_helpers import (
    clean_up_database_and_table,
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    ensure_process_not_running,
    get_process_stat,
    high_availability_test_setup,
    insert_data_into_mysql_and_validate_replication,
    isolate_instance_from_cluster,
    remove_instance_isolation,
    send_signal_to_pod_container_process,
    wait_until_units_in_status,
)

logger = logging.getLogger(__name__)

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"
TIMEOUT = 40 * 60


@pytest.mark.group(1)
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    await high_availability_test_setup(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_kill_db_process(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send a SIGKILL to the primary db process and ensure that the cluster self heals."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    logger.info("Waiting until 3 mysql instances are online")
    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application is not fully online"

    logger.info("Ensuring all units have continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )

    logger.info(f"Sending SIGKILL to unit {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test,
        primary.name,
        MYSQL_CONTAINER_NAME,
        MYSQLD_PROCESS_NAME,
        "SIGKILL",
    )

    # Wait for the SIGKILL above to take effect before continuining with test checks
    time.sleep(10)

    logger.info("Waiting until 3 mysql instances are online")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The mysql application is not fully online after sending SIGKILL to primary"

    # ensure that the mysqld process got restarted and has a new process id
    new_mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert (
        mysql_pid != new_mysql_pid
    ), "The mysql process id is the same after sending it a SIGKILL"

    new_primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    assert (
        primary.name != new_primary.name
    ), "The mysql primary has not been reelected after sending a SIGKILL"

    logger.info("Ensuring all units have continuous writes incrementing")
    # ensure continuous writes still incrementing for all units
    async with ops_test.fast_forward():
        await ensure_all_units_continuous_writes_incrementing(ops_test)

    # ensure that we are able to insert data into the primary and have it replicated to all units
    database_name, table_name = "test-kill-db-process", "data"
    await insert_data_into_mysql_and_validate_replication(ops_test, database_name, table_name)
    await clean_up_database_and_table(ops_test, database_name, table_name)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@pytest.mark.unstable
async def test_freeze_db_process(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send a SIGSTOP to the primary db process and ensure that the cluster self heals."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application is not fully online"

    logger.info("Ensuring that all units continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert mysql_pid > 0, "mysql process id is not positive"

    logger.info(f"Sending SIGSTOP to unit {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test,
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
            assert await ensure_n_online_mysql_members(
                ops_test, 2, remaining_online_units
            ), "The deployed mysql application does not have two online nodes"

            new_primary = await get_primary_unit(
                ops_test, remaining_online_units[0], mysql_application_name
            )
            assert primary.name != new_primary.name, "new mysql primary was not elected"

    logger.info("Ensuring all remaining units continuous writes incrementing")

    async with ops_test.fast_forward():
        for attempt in Retrying(stop=stop_after_delay(15 * 60), wait=wait_fixed(10)):
            with attempt:
                await ensure_all_units_continuous_writes_incrementing(
                    ops_test, remaining_online_units
                )

    logger.info(f"Sending SIGCONT to {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test,
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
    assert (
        "T" not in mysql_process_stat_after_sigcont
    ), "mysql process is not started after sigcont"
    assert (
        "R" in mysql_process_stat_after_sigcont
        or "S" in mysql_process_stat_after_sigcont
        or "I" in mysql_process_stat_after_sigcont
    ), "mysql process not running or sleeping after sigcont"

    new_mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert (
        new_mysql_pid == mysql_pid
    ), "mysql process id is not the same as it was before process was stopped"

    # wait for possible recovery of the old primary
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=False,
            timeout=TIMEOUT,
        )

    logger.info("Ensuring that there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(
        ops_test, 3, remaining_online_units
    ), "The deployed mysql application does not have three online nodes"

    logger.info("Ensure all units continuous writes incrementing")
    await ensure_all_units_continuous_writes_incrementing(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_graceful_crash_of_primary(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send SIGTERM to primary instance and then verify recovery."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    logger.info("Ensuring that there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    logger.info("Ensuring that all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )

    logger.info(f"Sending SIGTERM to unit {primary.name}")
    await send_signal_to_pod_container_process(
        ops_test,
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
                await ensure_all_units_continuous_writes_incrementing(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_network_cut_affecting_an_instance(
    ops_test: OpsTest, continuous_writes, chaos_mesh
) -> None:
    """Test for a network cut affecting an instance."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    logger.info("Ensuring that there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    logger.info("Ensuring that all instances have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_units = ops_test.model.applications[mysql_application_name].units
    primary = await get_primary_unit(ops_test, mysql_units[0], mysql_application_name)

    assert primary is not None, "No primary unit found"

    logger.info(
        f"Creating networkchaos policy to isolate instance {primary.name} from the cluster"
    )
    isolate_instance_from_cluster(ops_test, primary.name)

    remaining_units = [unit for unit in mysql_units if unit.name != primary.name]

    logger.info("Wait until MySQL GR actually detects isolated instance")
    await wait_until_units_in_status(ops_test, [primary], remaining_units[0], "(missing)")
    await wait_until_units_in_status(ops_test, remaining_units, remaining_units[0], "online")

    cluster_status = await get_cluster_status(ops_test, remaining_units[0])

    isolated_primary_status, isolated_primary_memberrole = [
        (member["status"], member["memberrole"])
        for label, member in cluster_status["defaultreplicaset"]["topology"].items()
        if label == primary.name.replace("/", "-")
    ][0]
    assert isolated_primary_status == "(missing)"
    assert isolated_primary_memberrole == "secondary"

    new_primary = await get_primary_unit(ops_test, remaining_units[0], mysql_application_name)
    assert primary.name != new_primary.name

    logger.info("Ensure all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test, remaining_units)

    logger.info("Remove networkchaos policy isolating instance from cluster")
    remove_instance_isolation(ops_test)

    async with ops_test.fast_forward():
        logger.info("Wait until returning instance enters recovery")
        await ops_test.model.block_until(
            lambda: primary.workload_status != "active", timeout=TIMEOUT
        )
        logger.info("Wait until returning instance become active")
        await ops_test.model.block_until(
            lambda: primary.workload_status == "active", timeout=TIMEOUT
        )

    logger.info("Wait until all units are online")
    await wait_until_units_in_status(ops_test, mysql_units, mysql_units[0], "online")

    new_cluster_status = await get_cluster_status(ops_test, mysql_units[0])

    logger.info("Ensure isolated instance is now secondary")
    isolated_primary_status, isolated_primary_memberrole = [
        (member["status"], member["memberrole"])
        for label, member in new_cluster_status["defaultreplicaset"]["topology"].items()
        if label == primary.name.replace("/", "-")
    ][0]
    assert isolated_primary_status == "online"
    assert isolated_primary_memberrole == "secondary"

    logger.info("Ensure there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    logger.info("Ensure all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@pytest.mark.unstable
async def test_graceful_full_cluster_crash_test(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send SIGTERM to all units and then ensure that the cluster recovers."""
    mysql_application_name, application_name = await high_availability_test_setup(ops_test)

    logger.info("Ensure there are 3 online mysql members")
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    logger.info("Ensure that all units have incrementing continuous writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_units = ops_test.model.applications[mysql_application_name].units

    unit_mysqld_pids = {}
    logger.info("Get mysqld pids on all instances")
    for unit in mysql_units:
        pid = await get_process_pid(ops_test, unit.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME)
        assert pid > 1

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

    cluster_status = await get_cluster_status(ops_test, mysql_units[0])
    for member in cluster_status["defaultreplicaset"]["topology"].values():
        assert member["status"] == "online"

    async with ops_test.fast_forward():
        logger.info("Ensure all units have incrementing continuous writes")
        await ensure_all_units_continuous_writes_incrementing(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_single_unit_pod_delete(ops_test: OpsTest) -> None:
    """Delete the pod in a single unit deployment and write data to new pod."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    logger.info("Scale mysql application to 1 unit that is active")
    async with ops_test.fast_forward("60s"):
        await scale_application(ops_test, mysql_application_name, 1)
    unit = ops_test.model.applications[mysql_application_name].units[0]
    assert unit.workload_status == "active"

    logger.info("Delete pod for the the mysql unit")
    client = lightkube.Client()
    client.delete(Pod, unit.name.replace("/", "-"), namespace=ops_test.model.info.name)

    logger.info("Wait for a new pod to be created by k8s")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
            idle_period=30,
        )

    logger.info("Write data to unit and verify that data was written")
    database_name, table_name = "test-single-pod-delete", "data"
    await insert_data_into_mysql_and_validate_replication(
        ops_test, database_name, table_name, mysql_application_substring="mysql-k8s"
    )
    await clean_up_database_and_table(ops_test, database_name, table_name)
