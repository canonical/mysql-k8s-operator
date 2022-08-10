# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import itertools
import secrets
import string
from typing import Dict, List

import mysql.connector
from juju.unit import Unit
from pytest_operator.plugin import OpsTest


def generate_random_string(length: int) -> str:
    """Generate a random string of the provided length.

    Args:
        length: the length of the random string to generate

    Returns:
        A random string comprised of letters and digits
    """
    choices = string.ascii_letters + string.digits
    return "".join([secrets.choice(choices) for i in range(length)])


async def get_unit_address(ops_test: OpsTest, unit_name: str) -> str:
    """Get unit IP address.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        IP address of the unit
    """
    status = await ops_test.model.get_status()
    return status["applications"][unit_name.split("/")[0]].units[unit_name]["address"]


async def get_cluster_status(ops_test: OpsTest, unit: Unit) -> Dict:
    """Get the cluster status by running the get-cluster-status action.

    Args:
        ops_test: The ops test framework
        unit: The unit on which to execute the action on

    Returns:
        A dictionary representing the cluster status
    """
    get_cluster_status_action = await unit.run_action("get-cluster-status")
    cluster_status_results = await get_cluster_status_action.wait()
    return cluster_status_results.results


async def get_primary_unit(
    ops_test: OpsTest,
    unit: Unit,
    app_name: str,
) -> str:
    """Helper to retrieve the primary unit.

    Args:
        ops_test: The ops test object passed into every test case
        unit: A unit on which to execute commands/queries/actions on
        app_name: The name of the test application

    Returns:
        A juju unit that is a MySQL primary
    """
    cluster_status = await get_cluster_status(ops_test, unit)

    primary_label = [
        label
        for label, member in cluster_status["defaultreplicaset"]["topology"].items()
        if member["mode"] == "r/w"
    ][0]
    primary_name = "/".join(primary_label.rsplit("-", 1))

    for unit in ops_test.model.applications[app_name].units:
        if unit.name == primary_name:
            return unit

    return None


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


async def scale_application(
    ops_test: OpsTest, application_name: str, desired_count: int, wait: bool = True
) -> None:
    """Scale a given application to the desired unit count.

    Args:
        ops_test: The ops test framework
        application_name: The name of the application
        desired_count: The number of units to scale to
        wait: Boolean indicating whether to wait until units
            reach desired count
    """
    await ops_test.model.applications[application_name].scale(desired_count)

    if desired_count > 0 and wait:
        await ops_test.model.wait_for_idle(
            apps=[application_name],
            status="active",
            timeout=2000,
            wait_for_exact_units=desired_count,
        )

def is_relation_joined(ops_test: OpsTest, endpoint_one: str, endpoint_two: str) -> bool:
    """Check if a relation is joined.

    Args:
        ops_test: The ops test framework
        endpoint_one: The first endpoint of the relation
        endpoint_two: The second endpoint of the relation
    """
    for relation in ops_test.model.relations:
        endpoints = [endpoint.name for endpoint in relation.endpoints]
        if endpoint_one in endpoints and endpoint_two in endpoints:
            return True

    return False
