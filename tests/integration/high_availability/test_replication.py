#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import lightkube
import pytest
from helpers import (
    execute_queries_on_unit,
    generate_random_string,
    get_cluster_status,
    get_primary_unit,
    get_server_config_credentials,
    get_unit_address,
)
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.high_availability.high_availability_helpers import (
    get_max_written_value_in_database,
    high_availability_test_setup,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


@pytest.mark.order(1)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_kill_primary_check_reelection(ops_test: OpsTest) -> None:
    """Test to kill the primary under load and ensure re-election of primary."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_name = primary.name

    last_written_value = await get_max_written_value_in_database(ops_test, primary)

    # kill the primary pod
    client = lightkube.Client()
    client.delete(Pod, primary.name.replace("/", "-"), namespace=ops_test.model.info.name)

    async with ops_test.fast_forward():
        # wait for model to stabilize, k8s will re-create the killed pod
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        # ensure a new primary was elected
        mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
        new_primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
        new_primary_name = new_primary.name

        assert primary_name != new_primary_name

        # wait (and retry) until the killed pod is back online in the mysql cluster
        try:
            for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
                with attempt:
                    cluster_status = await get_cluster_status(ops_test, mysql_unit)
                    online_members = [
                        label
                        for label, member in cluster_status["defaultreplicaset"][
                            "topology"
                        ].items()
                        if member["status"] == "online"
                    ]
                    assert len(online_members) == 3
                    break
        except RetryError:
            assert False, "Old primary has not come back online after being killed"

    # For 2 minutes, ensure that data is being written in the database by the
    # continuous writes application charm
    for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(3)):
        with attempt:
            for unit in ops_test.model.applications[mysql_application_name].units:
                written_value = await get_max_written_value_in_database(ops_test, unit)
                assert written_value > last_written_value, "Continuous writes not incrementing"

                last_written_value = written_value


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_check_consistency(ops_test: OpsTest) -> None:
    """Test to write to primary, and read the same data back from replicas."""
    mysql_application_name, application_name = await high_availability_test_setup(ops_test)
    application_unit = ops_test.model.applications[application_name].units[0]

    # assert that there are 3 units in the mysql cluster
    assert len(ops_test.model.applications[mysql_application_name].units) == 3

    # stop the continuous writes for this test
    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_address = await get_unit_address(ops_test, primary.name)

    # insert some data into the mysql cluster
    database_name, table_name = "test-check-consistency", "data"
    inserted_value = generate_random_string(255)
    server_config_credentials = await get_server_config_credentials(primary)
    insert_data_sql = [
        f"CREATE DATABASE IF NOT EXISTS `{database_name}`",
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{table_name}` (id varchar(255), primary key(id))",
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{inserted_value}')",
    ]

    await execute_queries_on_unit(
        primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        insert_data_sql,
        commit=True,
    )

    # ensure that the inserted data gets replicated onto every instance in the mysql cluster
    select_inserted_data_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{inserted_value}'",
    ]

    for unit in ops_test.model.applications[mysql_application_name].units:
        unit_address = await get_unit_address(ops_test, unit.name)

        try:
            for attempt in Retrying(stop=stop_after_delay(10), wait=wait_fixed(2)):
                with attempt:
                    output = await execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        select_inserted_data_sql,
                    )
                    assert output[0] == inserted_value
        except RetryError:
            assert False, f"Unable to query inserted data from unit {unit.name}"
