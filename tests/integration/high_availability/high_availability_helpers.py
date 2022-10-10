# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from helpers import execute_queries_on_unit, get_server_config_credentials, get_unit_address

# Copied these values from high_availability.application_charm.src.charm
DATABASE_NAME = "continuous_writes_database"
TABLE_NAME = "data"


logger = logging.getLogger(__name__)


async def get_max_written_value_in_database(ops_test: OpsTest, unit: Unit) -> int:
    """Retrieve the max written value in the MySQL database.
    
    Args:
        ops_test: The ops test framework
        unit: The MySQL unit on which to execute queries on
    """
    server_config_credentials = await get_server_config_credentials(unit)
    unit_address = await get_unit_address(ops_test, unit.name)
    
    select_max_written_value_sql = [
        f"SELECT MAX(number) FROM `{DATABASE_NAME}`.`{TABLE_NAME}`;"
    ]

    output = await execute_queries_on_unit(
        unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        select_max_written_value_sql
    )

    return output[0]
