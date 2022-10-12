#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import lightkube
import pytest
from helpers import (
    execute_queries_on_unit,
    generate_random_string,
    get_primary_unit,
    get_server_config_credentials,
    get_unit_address,
    scale_application,
)
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.high_availability.high_availability_helpers import (
    deploy_and_scale_mysql,
    ensure_n_online_mysql_members,
    get_application_name,
    get_max_written_value_in_database,
    high_availability_test_setup,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


@pytest.fixture(scope="module")
async def continuous_writes(ops_test: OpsTest):
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    application_name = await get_application_name(ops_test, "application")

    application_unit = ops_test.model.applications[application_name].units[0]

    start_writes_action = await application_unit.run_action("start-continuous-writes")
    await start_writes_action.wait()

    yield

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()


@pytest.mark.order(1)
@pytest.mark.replication_tests
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    await high_availability_test_setup(ops_test)


# TODO: change test order to '2' after the following issue is resolved
# https://github.com/canonical/mysql-k8s-operator/issues/102
@pytest.mark.order(3)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_kill_primary_check_reelection(ops_test: OpsTest, continuous_writes) -> None:
    """Test to kill the primary under load and ensure re-election of primary."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_name = primary.name

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
        assert ensure_n_online_mysql_members(ops_test, 3), "Old primary has not come back online after being killed"

    last_written_value = await get_max_written_value_in_database(ops_test, primary)

    for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(3)):
        with attempt:
            # ensure that all units are up to date (including the previous primary)
            for unit in ops_test.model.applications[mysql_application_name].units:
                written_value = await get_max_written_value_in_database(ops_test, unit)
                assert written_value > last_written_value, "Continuous writes not incrementing"

                last_written_value = written_value


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_check_consistency(ops_test: OpsTest, continuous_writes) -> None:
    """Test to write to primary, and read the same data back from replicas."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    # assert that there are 3 units in the mysql cluster
    assert len(ops_test.model.applications[mysql_application_name].units) == 3

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

    # clean up inserted data, and created tables + databases
    clean_up_database_and_table_sql = [
        f"DROP TABLE IF EXISTS `{database_name}`.`{table_name}`",
        f"DROP DATABASE IF EXISTS `{database_name}`",
    ]
    execute_queries_on_unit(
        primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        clean_up_database_and_table_sql,
        commit=True,
    )


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_no_replication_across_clusters(ops_test: OpsTest, continuous_writes) -> None:
    """Test to ensure that writes to one cluster do not replicate to another cluster."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    # assert that there are 3 units in the mysql cluster
    assert len(ops_test.model.applications[mysql_application_name].units) == 3

    # deploy another mysql application cluster with the same 'cluster-name'
    another_mysql_application_name = "another-mysql"
    await deploy_and_scale_mysql(
        ops_test,
        check_for_existing_application=False,
        mysql_application_name=another_mysql_application_name,
    )

    # insert some data into the first/original mysql cluster
    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    mysql_primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    mysql_primary_address = await get_unit_address(ops_test, mysql_primary.name)

    database_name, table_name = "test-no-replication-across-clusters", "data"
    inserted_value = generate_random_string(255)
    server_config_credentials = await get_server_config_credentials(mysql_primary)
    insert_data_sql = [
        f"CREATE DATABASE IF NOT EXISTS `{database_name}`",
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{table_name}` (id varchar(255), primary key(id))",
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{inserted_value}')",
    ]

    await execute_queries_on_unit(
        mysql_primary_address,
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

    # ensure that the inserted data DOES NOT get replicated into the another mysql cluster
    another_mysql_unit = ops_test.model.applications[another_mysql_application_name].units[0]
    another_mysql_primary = await get_primary_unit(
        ops_test, another_mysql_unit, another_mysql_application_name
    )
    another_server_config_credentials = await get_server_config_credentials(another_mysql_primary)

    select_databases_sql = [
        "SELECT schema_name FROM information_schema.schemata",
    ]

    for unit in ops_test.model.applications[another_mysql_application_name].units:
        unit_address = await get_unit_address(ops_test, unit.name)

        output = await execute_queries_on_unit(
            unit_address,
            another_server_config_credentials["username"],
            another_server_config_credentials["password"],
            select_databases_sql,
        )

        assert len(output) > 0
        assert "information_schema" in output
        assert database_name not in output

    # remove another mysql application cluster
    await scale_application(ops_test, another_mysql_application_name, 0, wait=False)
    await ops_test.model.remove_application(
        another_mysql_application_name,
        block_until_done=False,
    )

    # clean up inserted data, and created tables + databases
    clean_up_database_and_table_sql = [
        f"DROP TABLE IF EXISTS `{database_name}`.`{table_name}`",
        f"DROP DATABASE IF EXISTS `{database_name}`",
    ]
    execute_queries_on_unit(
        mysql_primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        clean_up_database_and_table_sql,
        commit=True,
    )


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_preserves_data_on_delete(ops_test: OpsTest) -> None:
    """Test to ensure that data is preserved when a unit is scaled up and then down.

    Ensures that there are no running continuous writes as the extra data in the
    database makes scaling up slower.
    """
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    # assert that there are 3 units in the mysql cluster
    assert len(ops_test.model.applications[mysql_application_name].units) == 3

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_address = await get_unit_address(ops_test, primary.name)

    # insert a value before scale up, and ensure that the value exists in all units
    database_name, table_name = "test-preserves-data-on-delete", "data"
    value_before_scale_up = generate_random_string(255)
    server_config_credentials = await get_server_config_credentials(primary)
    insert_before_scale_up_sql = [
        f"CREATE DATABASE IF NOT EXISTS `{database_name}`",
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{table_name}` (id varchar(255), primary key(id))",
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{value_before_scale_up}')",
    ]

    await execute_queries_on_unit(
        primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        insert_before_scale_up_sql,
        commit=True,
    )

    select_value_before_scale_up_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{value_before_scale_up}'",
    ]

    for attempt in Retrying(stop=stop_after_delay(10), wait=wait_fixed(2)):
        with attempt:
            for unit in ops_test.model.applications[mysql_application_name].units:
                unit_address = await get_unit_address(ops_test, unit.name)

                output = await execute_queries_on_unit(
                    unit_address,
                    server_config_credentials["username"],
                    server_config_credentials["password"],
                    select_value_before_scale_up_sql,
                )
                assert output[0] == value_before_scale_up

    # scale up the mysql application
    await scale_application(ops_test, mysql_application_name, 4)
    await ensure_n_online_mysql_members(ops_test, 4)

    for attempt in Retrying(stop=stop_after_delay(10), wait=wait_fixed(2)):
        with attempt:
            for unit in ops_test.model.applications[mysql_application_name].units:
                unit_address = await get_unit_address(ops_test, unit.name)

                output = await execute_queries_on_unit(
                    unit_address,
                    server_config_credentials["username"],
                    server_config_credentials["password"],
                    select_value_before_scale_up_sql,
                )
                assert output[0] == value_before_scale_up

    # insert data after scale up
    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_address = await get_unit_address(ops_test, primary.name)

    value_after_scale_up = generate_random_string(255)
    insert_after_scale_up_sql = [
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{value_after_scale_up}')",
    ]

    await execute_queries_on_unit(
        primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        insert_after_scale_up_sql,
        commit=True,
    )

    # verify inserted data is present on all units
    select_value_after_scale_up_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{value_after_scale_up}'",
    ]

    for attempt in Retrying(stop=stop_after_delay(10), wait=wait_fixed(2)):
        with attempt:
            for unit in ops_test.model.applications[mysql_application_name].units:
                unit_address = await get_unit_address(ops_test, unit.name)

                output = await execute_queries_on_unit(
                    unit_address,
                    server_config_credentials["username"],
                    server_config_credentials["password"],
                    select_value_after_scale_up_sql,
                )
                assert output[0] == value_after_scale_up

    # scale down the mysql application
    await scale_application(ops_test, mysql_application_name, 3)
    await ensure_n_online_mysql_members(ops_test, 3)

    # ensure data written before scale down is persisted
    for unit in ops_test.model.applications[mysql_application_name].units:
        unit_address = await get_unit_address(ops_test, unit.name)

        output = await execute_queries_on_unit(
            unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_value_after_scale_up_sql,
        )
        assert output[0] == value_after_scale_up

    # clean up inserted data, and created tables + databases
    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_address = await get_unit_address(ops_test, primary.name)

    clean_up_database_and_table_sql = [
        f"DROP TABLE IF EXISTS `{database_name}`.`{table_name}`",
        f"DROP DATABASE IF EXISTS `{database_name}`",
    ]
    execute_queries_on_unit(
        primary_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        clean_up_database_and_table_sql,
        commit=True,
    )
