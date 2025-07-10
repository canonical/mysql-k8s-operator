# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from pytest_operator.plugin import OpsTest

from ..helpers import (
    execute_queries_on_unit,
    get_primary_unit,
    get_server_config_credentials,
    scale_application,
)
from .high_availability_helpers import (
    clean_up_database_and_table,
    deploy_and_scale_mysql,
    get_application_name,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


async def test_no_replication_across_clusters(
    ops_test: OpsTest, charm, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test to ensure that writes to one cluster do not replicate to another cluster."""
    mysql_application_name = get_application_name(ops_test, "mysql")

    # assert that there are 3 units in the mysql cluster
    assert len(ops_test.model.applications[mysql_application_name].units) == 3

    # deploy another mysql application cluster with the same 'cluster-name'
    another_mysql_application_name = "another-mysql"
    await deploy_and_scale_mysql(
        ops_test,
        charm,
        check_for_existing_application=False,
        mysql_application_name=another_mysql_application_name,
        num_units=1,
    )

    # insert some data into the first/original mysql cluster
    database_name, table_name = "test-no-replication-across-clusters", "data"
    await insert_data_into_mysql_and_validate_replication(
        ops_test, database_name, table_name, credentials
    )

    # ensure that the inserted data DOES NOT get replicated into the another mysql cluster
    another_mysql_unit = ops_test.model.applications[another_mysql_application_name].units[0]
    another_mysql_primary = await get_primary_unit(
        ops_test, another_mysql_unit, another_mysql_application_name
    )
    assert another_mysql_primary
    another_server_config_credentials = await get_server_config_credentials(another_mysql_primary)

    select_databases_sql = [
        "SELECT schema_name FROM information_schema.schemata",
    ]

    for unit in ops_test.model.applications[another_mysql_application_name].units:
        unit_address = await unit.get_public_address()

        output = execute_queries_on_unit(
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
    await clean_up_database_and_table(ops_test, database_name, table_name, credentials)
