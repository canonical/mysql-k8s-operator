# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from pytest_operator.plugin import OpsTest

from .high_availability_helpers import (
    clean_up_database_and_table,
    ensure_all_units_continuous_writes_incrementing,
    get_application_name,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


async def test_check_consistency(
    ops_test: OpsTest, highly_available_cluster, continuous_writes, credentials
) -> None:
    """Test to write to primary, and read the same data back from replicas."""
    mysql_application_name = get_application_name(ops_test, "mysql")

    # assert that there are 3 units in the mysql cluster
    assert len(ops_test.model.applications[mysql_application_name].units) == 3

    database_name, table_name = "test-check-consistency", "data"
    await insert_data_into_mysql_and_validate_replication(
        ops_test, database_name, table_name, credentials
    )
    await clean_up_database_and_table(ops_test, database_name, table_name, credentials)

    await ensure_all_units_continuous_writes_incrementing(ops_test, credentials=credentials)
