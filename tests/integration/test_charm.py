#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import AsyncRetrying, RetryError, stop_after_delay, wait_fixed

from tests.integration.helpers import (
    execute_queries_on_unit,
    generate_random_string,
    get_cluster_status,
    get_primary_unit,
    get_server_config_credentials,
    get_unit_address,
    scale_application,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CLUSTER_NAME = "test_cluster"

UNIT_IDS = [0, 1, 2]


@pytest.mark.order(1)
@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build the mysql charm and deploy it."""
    async with ops_test.fast_forward():
        charm = await ops_test.build_charm(".")
        resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
        config = {"cluster-name": CLUSTER_NAME}
        await ops_test.model.deploy(
            charm, resources=resources, application_name=APP_NAME, config=config, num_units=3
        )

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=1000,
            wait_for_exact_units=3,
        )
        assert len(ops_test.model.applications[APP_NAME].units) == 3

        random_unit = ops_test.model.applications[APP_NAME].units[0]
        server_config_credentials = await get_server_config_credentials(random_unit)

        count_group_replication_members_sql = [
            "SELECT count(*) FROM performance_schema.replication_group_members where MEMBER_STATE='ONLINE';",
        ]

        for unit in ops_test.model.applications[APP_NAME].units:
            assert unit.workload_status == "active"

            unit_address = await get_unit_address(ops_test, unit.name)
            output = await execute_queries_on_unit(
                unit_address,
                server_config_credentials["username"],
                server_config_credentials["password"],
                count_group_replication_members_sql,
            )
            assert output[0] == 3


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
async def test_consistent_data_replication_across_cluster(ops_test: OpsTest) -> None:
    """Confirm that data is replicated from the primary node to all the replicas."""
    # Insert values into a table on the primary unit
    random_unit = ops_test.model.applications[APP_NAME].units[0]
    server_config_credentials = await get_server_config_credentials(random_unit)

    primary_unit = await get_primary_unit(
        ops_test,
        random_unit,
        APP_NAME,
    )
    primary_unit_address = await get_unit_address(ops_test, primary_unit.name)

    random_chars = generate_random_string(40)
    create_records_sql = [
        "CREATE DATABASE IF NOT EXISTS test",
        "CREATE TABLE IF NOT EXISTS test.data_replication_table (id varchar(40), primary key(id))",
        f"INSERT INTO test.data_replication_table VALUES ('{random_chars}')",
    ]

    await execute_queries_on_unit(
        primary_unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        create_records_sql,
        commit=True,
    )

    select_data_sql = [
        f"SELECT * FROM test.data_replication_table WHERE id = '{random_chars}'",
    ]

    # Retry
    try:
        for attempt in AsyncRetrying(stop=stop_after_delay(5), wait=wait_fixed(3)):
            with attempt:
                # Confirm that the values are available on all units
                for unit in ops_test.model.applications[APP_NAME].units:
                    unit_address = await get_unit_address(ops_test, unit.name)

                    output = await execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        select_data_sql,
                    )
                    assert random_chars in output
    except RetryError:
        assert False


@pytest.mark.order(3)
@pytest.mark.abort_on_fail
async def test_scale_up_and_down(ops_test: OpsTest) -> None:
    """Confirm that a new primary is elected when the current primary is torn down."""
    async with ops_test.fast_forward():
        random_unit = ops_test.model.applications[APP_NAME].units[0]

        await scale_application(ops_test, APP_NAME, 5)

        cluster_status = await get_cluster_status(ops_test, random_unit)
        online_member_addresses = [
            member["address"]
            for _, member in cluster_status["defaultreplicaset"]["topology"].items()
            if member["status"] == "online"
        ]
        assert len(online_member_addresses) == 5

        await scale_application(ops_test, APP_NAME, 1, wait=False)

        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 1
            and ops_test.model.applications[APP_NAME].units[0].workload_status == "maintenance"
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=1500,
        )

        random_unit = ops_test.model.applications[APP_NAME].units[0]
        cluster_status = await get_cluster_status(ops_test, random_unit)
        online_member_addresses = [
            member["address"]
            for _, member in cluster_status["defaultreplicaset"]["topology"].items()
            if member["status"] == "online"
        ]
        assert len(online_member_addresses) == 1

        not_online_member_addresses = [
            member["address"]
            for _, member in cluster_status["defaultreplicaset"]["topology"].items()
            if member["status"] != "online"
        ]
        assert len(not_online_member_addresses) == 0

        await scale_application(ops_test, APP_NAME, 0)
        await ops_test.model.remove_application(APP_NAME)
