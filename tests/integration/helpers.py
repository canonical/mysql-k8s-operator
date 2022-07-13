# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import itertools
from typing import Dict, List

import mysql.connector
from juju.unit import Unit
from pytest_operator.plugin import OpsTest


async def execute_queries_on_unit(
    unit_address: str,
    username: str,
    password: str,
    queries: List[str],
    commit: bool = False,
) -> List:
    """Execute given MySQL queries on a unit.

    Args:
        unit_address: The public IP address of the unit to execute the queries on
        username: The MySQL username
        password: The MySQL password
        queries: A list of queries to execute
        commit: A keyword arg indicating whether there are any writes queries

    Returns:
        A list of rows that were potentially queried
    """
    connection = mysql.connector.connect(
        host=unit_address,
        user=username,
        password=password,
    )
    cursor = connection.cursor()

    for query in queries:
        cursor.execute(query)

    if commit:
        connection.commit()

    output = list(itertools.chain(*cursor.fetchall()))

    cursor.close()
    connection.close()

    return output


async def get_server_config_credentials(unit: Unit) -> Dict:
    """Helper to run an action to retrieve server config credentials.

    Args:
        unit: The juju unit on which to run the get-server-config-credentials action

    Returns:
        A dictionary with the server config username and password
    """
    action = await unit.run_action("get-server-config-credentials")
    result = await action.wait()

    return {
        "username": result.results["server-config-username"],
        "password": result.results["server-config-password"],
    }


async def get_unit_address(ops_test: OpsTest, unit_name: str) -> str:
    """Get unit's IP address.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        IP address of the unit
    """
    status = await ops_test.model.get_status()
    return status["applications"][unit_name.split("/")[0]].units[unit_name]["address"]


async def scale_application(ops_test: OpsTest, application_name: str, desired_count: int) -> None:
    """Scale a given application to the desired unit count.

    Args:
        ops_test: The ops test framework
        application_name: The name of the application
        desired_count: The number of units to scale to
    """
    await ops_test.model.applications[application_name].scale(desired_count)

    if desired_count > 0:
        await ops_test.model.wait_for_idle(apps=[application_name], status="active", timeout=1000)
