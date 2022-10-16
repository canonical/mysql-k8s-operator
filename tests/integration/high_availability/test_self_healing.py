#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from helpers import get_primary_unit, get_process_pid
from pytest_operator.plugin import OpsTest

from tests.integration.high_availability.high_availability_helpers import (
    clean_up_database_and_table,
    ensure_all_units_continuous_writes_incrementing,
    ensure_n_online_mysql_members,
    high_availability_test_setup,
    insert_data_into_mysql_and_validate_replication,
    send_signal_to_pod_container_process,
)

logger = logging.getLogger(__name__)


@pytest.mark.order(1)
@pytest.mark.self_healing_tests
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    await high_availability_test_setup(ops_test)


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.self_healing_tests
async def test_kill_db_process(ops_test: OpsTest, continuous_writes) -> None:
    """Test to send a SIGKILL to the db process and ensure that the cluster self heals."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    # ensure all units in the cluster are online
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The deployed mysql application is not fully online"

    mysql_pid = await get_process_pid(ops_test, primary.name, "mysql", "mysqld")

    await send_signal_to_pod_container_process(
        ops_test,
        primary.name,
        "mysql",
        "mysqld",
        "SIGKILL",
    )

    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The mysql application is not fully online after sending SIGKILL to primary"

    new_mysql_pid = await get_process_pid(ops_test, primary.name, "mysql", "mysqld")

    assert (
        mysql_pid != new_mysql_pid
    ), "The mysql process id is the same after sending it a SIGKILL"

    new_primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    assert (
        primary.name != new_primary.name
    ), "The mysql primary has not been reelected after sending a SIGKILL"

    async with ops_test.fast_forward():
        await ensure_all_units_continuous_writes_incrementing(ops_test)

    await insert_data_into_mysql_and_validate_replication(ops_test, "test-kill-db-process", "data")
    await clean_up_database_and_table(ops_test, "test-kill-db-process", "data")
