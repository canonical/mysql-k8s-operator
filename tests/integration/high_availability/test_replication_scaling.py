# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from ..helpers import (
    execute_queries_on_unit,
    get_primary_unit,
    get_unit_address,
    scale_application,
)
from .high_availability_helpers import (
    clean_up_database_and_table,
    ensure_n_online_mysql_members,
    get_application_name,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


async def test_scaling_without_data_loss(
    ops_test: OpsTest, highly_available_cluster, credentials
) -> None:
    """Test to ensure that data is preserved when a unit is scaled up and then down.

    Ensures that there are no running continuous writes as the extra data in the
    database makes scaling up slower.
    """
    mysql_application_name = get_application_name(ops_test, "mysql")
    assert mysql_application_name, "mysql application not found"

    # assert that there are 3 units in the mysql cluster
    assert len(ops_test.model.applications[mysql_application_name].units) == 3

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    assert primary, "Primary unit not found"

    # insert a value before scale up, and ensure that the value exists in all units
    database_name, table_name = "test-preserves-data-on-delete", "data"
    value_before_scale_up = await insert_data_into_mysql_and_validate_replication(
        ops_test, database_name, table_name, credentials
    )

    select_value_before_scale_up_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{value_before_scale_up}'",
    ]

    # scale up the mysql application
    await scale_application(ops_test, mysql_application_name, 4)
    assert await ensure_n_online_mysql_members(
        ops_test, 4
    ), "The cluster is not fully online after scaling up"

    # ensure value inserted before scale exists in all units
    for attempt in Retrying(stop=stop_after_delay(10), wait=wait_fixed(2)):
        with attempt:
            for unit in ops_test.model.applications[mysql_application_name].units:
                unit_address = await get_unit_address(ops_test, unit.name)

                output = execute_queries_on_unit(
                    unit_address,
                    credentials["username"],
                    credentials["password"],
                    select_value_before_scale_up_sql,
                )
                assert output[0] == value_before_scale_up

    # insert data after scale up
    value_after_scale_up = await insert_data_into_mysql_and_validate_replication(
        ops_test, database_name, table_name, credentials
    )

    # verify inserted data is present on all units
    select_value_after_scale_up_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{value_after_scale_up}'",
    ]

    # scale down the mysql application
    await scale_application(ops_test, mysql_application_name, 3)
    assert await ensure_n_online_mysql_members(
        ops_test, 3
    ), "The cluster is not fully online after scaling down"

    # ensure data written before scale down is persisted
    for unit in ops_test.model.applications[mysql_application_name].units:
        unit_address = await get_unit_address(ops_test, unit.name)

        output = execute_queries_on_unit(
            unit_address,
            credentials["username"],
            credentials["password"],
            select_value_after_scale_up_sql,
        )
        assert output[0] == value_after_scale_up

    # clean up inserted data, and created tables + databases
    await clean_up_database_and_table(ops_test, database_name, table_name, credentials)
