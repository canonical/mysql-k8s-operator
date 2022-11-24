#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import pytest
from helpers import get_cluster_status, get_primary_unit, get_process_pid
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from tests.integration.high_availability.high_availability_helpers import (
    clean_up_database_and_table,
    deploy_chaos_mesh,
    destroy_chaos_mesh,
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
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


@pytest.mark.order(1)
@pytest.mark.self_healing_tests
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    await high_availability_test_setup(ops_test)


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.self_healing_tests
async def test_kill_db_process(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send a SIGKILL to the primary db process and ensure that the cluster self heals."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application is not fully online"

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )

    await send_signal_to_pod_container_process(
        ops_test,
        primary.name,
        MYSQL_CONTAINER_NAME,
        MYSQLD_PROCESS_NAME,
        "SIGKILL",
    )

    # Wait for the SIGKILL above to take effect before continuining with test checks
    time.sleep(10)

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

    # ensure continuous writes still incrementing for all units
    async with ops_test.fast_forward():
        await ensure_all_units_continuous_writes_incrementing(ops_test)

    # ensure that we are able to insert data into the primary and have it replicated to all units
    database_name, table_name = "test-kill-db-process", "data"
    await insert_data_into_mysql_and_validate_replication(ops_test, database_name, table_name)
    await clean_up_database_and_table(ops_test, database_name, table_name)


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.self_healing_tests
async def test_freeze_db_process(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send a SIGSTOP to the primary db process and ensure that the cluster self heals."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application is not fully online"

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )
    assert mysql_pid > 0, "mysql process id is not positive"

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

    # retring as it may take time for the cluster to recognize that the primary process is stopped
    for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(10)):
        with attempt:
            assert await ensure_n_online_mysql_members(
                ops_test, 2, remaining_online_units
            ), "The deployed mysql application does not have two online nodes"

            new_primary = await get_primary_unit(
                ops_test, remaining_online_units[0], mysql_application_name
            )
            assert primary.name != new_primary.name, "new mysql primary was not elected"

    async with ops_test.fast_forward():
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(10)):
            with attempt:
                assert ensure_all_units_continuous_writes_incrementing(
                    ops_test, remaining_online_units
                )

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

    assert await ensure_n_online_mysql_members(
        ops_test, 3, remaining_online_units
    ), "The deployed mysql application does not have three online nodes"

    await ensure_all_units_continuous_writes_incrementing(ops_test)


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.self_healing_tests
async def test_graceful_crash_of_primary(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send SIGTERM to primary instance and then verify recovery."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    await ensure_all_units_continuous_writes_incrementing(ops_test)

    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    mysql_pid = await get_process_pid(
        ops_test, primary.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME
    )

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

    # retring as it may take time for the cluster to recognize that the primary process is stopped
    for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(10)):
        with attempt:
            assert await ensure_n_online_mysql_members(
                ops_test, 3
            ), "The deployed mysql application does not have three online nodes"

            new_primary = await get_primary_unit(
                ops_test, remaining_online_units[0], mysql_application_name
            )
            assert primary.name != new_primary.name, "new mysql primary was not elected"

    async with ops_test.fast_forward():
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(10)):
            with attempt:
                assert ensure_all_units_continuous_writes_incrementing(ops_test)


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.self_healing_tests
async def test_network_cut_affecting_an_instance(ops_test: OpsTest, continuous_writes) -> None:
    """Test for a network cut affecting an instance."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    await ensure_all_units_continuous_writes_incrementing(ops_test)

    deploy_chaos_mesh(ops_test, ops_test.model.info.name)

    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application does not have three online nodes"

    mysql_units = ops_test.model.applications[mysql_application_name].units
    primary = await get_primary_unit(ops_test, mysql_units[0], mysql_application_name)

    # Create networkchaos policy to isolate instance from cluster
    isolate_instance_from_cluster(ops_test, primary.name)

    remaining_units = [unit for unit in mysql_units if unit.name != primary.name]

    # Wait until MySQL GR actually detects isolated instance
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

    await ensure_all_units_continuous_writes_incrementing(ops_test, remaining_units)

    # Remove networkchaos policy isolating instance from cluster
    remove_instance_isolation(ops_test)

    await wait_until_units_in_status(ops_test, mysql_units, mysql_units[0], "online")

    new_cluster_status = await get_cluster_status(ops_test, mysql_units[0])

    isolated_primary_status, isolated_primary_memberrole = [
        (member["status"], member["memberrole"])
        for label, member in new_cluster_status["defaultreplicaset"]["topology"].items()
        if label == primary.name.replace("/", "-")
    ][0]
    assert isolated_primary_status == "online"
    assert isolated_primary_memberrole == "secondary"

    await ensure_all_units_continuous_writes_incrementing(ops_test)

    destroy_chaos_mesh(ops_test, ops_test.model.info.name)
