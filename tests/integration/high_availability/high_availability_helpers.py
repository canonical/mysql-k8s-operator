# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import Tuple

import yaml
from helpers import (
    execute_queries_on_unit,
    get_server_config_credentials,
    get_unit_address,
    is_relation_joined,
    scale_application,
)
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

# Copied these values from high_availability.application_charm.src.charm
DATABASE_NAME = "continuous_writes_database"
TABLE_NAME = "data"

CLUSTER_NAME = "test_cluster"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MYSQL_DEFAULT_APP_NAME = METADATA["name"]
APPLICATION_DEFAULT_APP_NAME = "application"
TIMEOUT = 15 * 60

mysql_charm, application_charm = None, None

logger = logging.getLogger(__name__)


async def get_max_written_value_in_database(ops_test: OpsTest, unit: Unit) -> int:
    """Retrieve the max written value in the MySQL database.

    Args:
        ops_test: The ops test framework
        unit: The MySQL unit on which to execute queries on
    """
    server_config_credentials = await get_server_config_credentials(unit)
    unit_address = await get_unit_address(ops_test, unit.name)

    select_max_written_value_sql = [f"SELECT MAX(number) FROM `{DATABASE_NAME}`.`{TABLE_NAME}`;"]

    output = await execute_queries_on_unit(
        unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        select_max_written_value_sql,
    )

    return output[0]


async def get_application_name(ops_test: OpsTest, application_name: str) -> str:
    """Returns the name of the application witt the provided application name.

    This enables us to retrieve the name of the deployed application in an existing model.

    Note: if multiple applications with the application name exist,
    the first one found will be returned.
    """
    status = await ops_test.model.get_status()

    for application in ops_test.model.applications:
        # note that format of the charm field is not exactly "mysql" but instead takes the form
        # of `local:focal/mysql-6`
        if application_name in status["applications"][application]["charm"]:
            return application

    return None


async def deploy_and_scale_mysql(ops_test: OpsTest) -> str:
    """Deploys and scales the mysql application charm."""
    application_name = await get_application_name(ops_test, "mysql")

    if application_name:
        if len(ops_test.model.applications[application_name].units) != 3:
            async with ops_test.fast_forward():
                await scale_application(ops_test, application_name, 3)

        return application_name

    global mysql_charm
    if not mysql_charm:
        charm = await ops_test.build_charm(".")
        # Cache the built charm to avoid rebuilding it between tests
        mysql_charm = charm

    config = {"cluster-name": CLUSTER_NAME}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    async with ops_test.fast_forward():
        await ops_test.model.deploy(
            mysql_charm,
            application_name=MYSQL_DEFAULT_APP_NAME,
            config=config,
            resources=resources,
            num_units=3,
        )

        await ops_test.model.wait_for_idle(
            apps=[MYSQL_DEFAULT_APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        assert len(ops_test.model.applications[MYSQL_DEFAULT_APP_NAME].units) == 3

    return MYSQL_DEFAULT_APP_NAME


async def deploy_and_scale_application(ops_test: OpsTest) -> str:
    """Deploys and scales the test application charm."""
    application_name = await get_application_name(ops_test, "application")

    if application_name:
        if len(ops_test.model.application[application_name].units) != 1:
            async with ops_test.fast_forward():
                await scale_application(ops_test, application_name, 1)

        return application_name

    global application_charm
    if not application_charm:
        charm = await ops_test.build_charm(
            "./tests/integration/high_availability/application_charm/"
        )
        # Cache the built charm to avoid rebuilding it between tests
        application_charm = charm

    async with ops_test.fast_forward():
        await ops_test.model.deploy(
            application_charm,
            application_name=APPLICATION_DEFAULT_APP_NAME,
            num_units=1,
        )

        await ops_test.model.wait_for_idle(
            apps=[APPLICATION_DEFAULT_APP_NAME],
            status="waiting",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        assert len(ops_test.model.applications[APPLICATION_DEFAULT_APP_NAME].units) == 1

    return APPLICATION_DEFAULT_APP_NAME


async def relate_mysql_and_application(
    ops_test: OpsTest, mysql_application_name: str, application_name: str
) -> None:
    """Relates the mysql and application charms."""
    if is_relation_joined(ops_test, "database", "database"):
        return

    await ops_test.model.relate(
        f"{application_name}:database", f"{mysql_application_name}:database"
    )
    await ops_test.model.block_until(
        lambda: is_relation_joined(ops_test, "database", "database")
    )


async def high_availability_test_setup(ops_test: OpsTest) -> Tuple[str, str]:
    """Run the set up for high availability tests.

    Args:
        ops_test: The ops test framework
    """
    mysql_application_name = await deploy_and_scale_mysql(ops_test)
    application_name = await deploy_and_scale_application(ops_test)

    await relate_mysql_and_application(ops_test, mysql_application_name, application_name)

    application_unit = ops_test.model.applications[application_name].units[0]

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()

    start_writes_action = await application_unit.run_action("start-continuous-writes")
    await start_writes_action.wait()

    return mysql_application_name, application_name
