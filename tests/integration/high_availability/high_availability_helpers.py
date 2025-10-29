# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional

import yaml
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from ..helpers import (
    execute_queries_on_unit,
    generate_random_string,
    get_primary_unit,
    get_unit_address,
    is_relation_joined,
    scale_application,
)

CLUSTER_NAME = "test_cluster"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MYSQL_DEFAULT_APP_NAME = METADATA["name"]
APPLICATION_DEFAULT_APP_NAME = "mysql-test-app"
TIMEOUT = 15 * 60

logger = logging.getLogger(__name__)


def get_application_name(ops_test: OpsTest, application_name_substring: str) -> Optional[str]:
    """Returns the name of the application with the provided application name.

    This enables us to retrieve the name of the deployed application in an existing model.

    Note: if multiple applications with the application name exist,
    the first one found will be returned.
    """
    for application in ops_test.model.applications:
        if application_name_substring in application:
            return application

    return None


async def deploy_and_scale_mysql(
    ops_test: OpsTest,
    charm,
    check_for_existing_application: bool = True,
    mysql_application_name: str = MYSQL_DEFAULT_APP_NAME,
    num_units: int = 3,
    model: Optional[Model] = None,
    cluster_name: str = CLUSTER_NAME,
) -> str:
    """Deploys and scales the mysql application charm.

    Args:
        ops_test: The ops test framework
        charm: `charm` fixture
        check_for_existing_application: Whether to check for existing mysql applications
            in the model
        mysql_application_name: The name of the mysql application if it is to be deployed
        num_units: The number of units to deploy
        model: The model to deploy the mysql application to
        cluster_name: The name of the mysql cluster
    """
    application_name = get_application_name(ops_test, "mysql")
    if not model:
        model = ops_test.model

    if check_for_existing_application and application_name:
        if len(model.applications[application_name].units) != num_units:
            async with ops_test.fast_forward("60s"):
                await scale_application(ops_test, application_name, num_units)

        return application_name

    config = {"cluster-name": cluster_name, "profile": "testing"}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    async with ops_test.fast_forward("60s"):
        await ops_test.model.deploy(
            charm,
            application_name=mysql_application_name,
            config=config,
            resources=resources,
            num_units=num_units,
            base="ubuntu@22.04",
            trust=True,
        )

        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
            raise_on_error=False,
        )

        assert len(ops_test.model.applications[mysql_application_name].units) == num_units

    return mysql_application_name


async def deploy_and_scale_application(
    ops_test: OpsTest,
    check_for_existing_application: bool = True,
    test_application_name: str = APPLICATION_DEFAULT_APP_NAME,
) -> str:
    """Deploys and scales the test application charm.

    Args:
        ops_test: The ops test framework
        check_for_existing_application: Whether to check for existing test applications
        test_application_name: Name of test application to be deployed
    """
    application_name = get_application_name(ops_test, test_application_name)

    if check_for_existing_application and application_name:
        if len(ops_test.model.applications[application_name].units) != 1:
            async with ops_test.fast_forward("60s"):
                await scale_application(ops_test, application_name, 1)

        return application_name

    async with ops_test.fast_forward("60s"):
        await ops_test.model.deploy(
            APPLICATION_DEFAULT_APP_NAME,
            application_name=test_application_name,
            num_units=1,
            channel="latest/edge",
            base="ubuntu@22.04",
            config={"sleep_interval": 300},
        )

        await ops_test.model.wait_for_idle(
            apps=[test_application_name],
            status="waiting",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        assert len(ops_test.model.applications[test_application_name].units) == 1

    return test_application_name


async def relate_mysql_and_application(
    ops_test: OpsTest, mysql_application_name: str, application_name: str
) -> None:
    """Relates the mysql and application charms.

    Args:
        ops_test: The ops test framework
        mysql_application_name: The mysql charm application name
        application_name: The continuous writes test charm application name
    """
    if is_relation_joined(
        ops_test,
        "database",
        "database",
        application_one=mysql_application_name,
        application_two=application_name,
    ):
        return

    await ops_test.model.relate(
        f"{application_name}:database", f"{mysql_application_name}:database"
    )
    await ops_test.model.block_until(
        lambda: is_relation_joined(
            ops_test,
            "database",
            "database",
            application_one=mysql_application_name,
            application_two=application_name,
        )
    )

    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, application_name],
        status="active",
        raise_on_blocked=True,
        timeout=TIMEOUT,
    )


def deploy_chaos_mesh(namespace: str) -> None:
    """Deploy chaos mesh to the provided namespace."""
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    subprocess.check_output(
        f"tests/integration/high_availability/scripts/deploy_chaos_mesh.sh {namespace}",
        shell=True,
        env=env,
    )

    logger.info("Ensure chaos mesh is ready")
    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
            with attempt:
                output = subprocess.check_output(
                    f"microk8s.kubectl get pods --namespace {namespace} -l app.kubernetes.io/instance=chaos-mesh".split(),
                    env=env,
                )
                assert output.decode().count("Running") == 4, "Chaos Mesh not ready"

    except RetryError:
        raise Exception("Chaos Mesh pods not found") from None


def destroy_chaos_mesh(namespace: str) -> None:
    """Remove chaos mesh from the provided namespace."""
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    subprocess.check_output(
        f"tests/integration/high_availability/scripts/destroy_chaos_mesh.sh {namespace}",
        shell=True,
        env=env,
    )


async def insert_data_into_mysql_and_validate_replication(
    ops_test: OpsTest,
    database_name: str,
    table_name: str,
    credentials: dict,
    mysql_units: Optional[List[Unit]] = None,
    mysql_application_substring: Optional[str] = "mysql",
) -> str:
    """Inserts data into the mysql cluster and validates its replication.

    database_name: The name of the database to create
    table_name: The name of the table to create and insert data into
    """
    mysql_application_name = get_application_name(ops_test, mysql_application_substring)

    if not mysql_units:
        mysql_units = ops_test.model.applications[mysql_application_name].units

    primary = await get_primary_unit(ops_test, mysql_units[0], mysql_application_name)

    # insert some data into the new primary and ensure that the writes get replicated
    primary_address = await get_unit_address(ops_test, primary.name)

    value = generate_random_string(255)
    insert_value_sql = [
        f"CREATE DATABASE IF NOT EXISTS `{database_name}`",
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{table_name}` (id varchar(255), primary key (id))",
        f"INSERT INTO `{database_name}`.`{table_name}` (id) VALUES ('{value}')",
    ]

    execute_queries_on_unit(
        primary_address,
        credentials["username"],
        credentials["password"],
        insert_value_sql,
        commit=True,
    )

    select_value_sql = [
        f"SELECT id FROM `{database_name}`.`{table_name}` WHERE id = '{value}'",
    ]

    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
            with attempt:
                for unit in mysql_units:
                    unit_address = await get_unit_address(ops_test, unit.name)

                    output = execute_queries_on_unit(
                        unit_address,
                        credentials["username"],
                        credentials["password"],
                        select_value_sql,
                    )
                    assert output[0] == value
    except RetryError:
        assert False, "Cannot query inserted data from all units"

    return value


async def clean_up_database_and_table(
    ops_test: OpsTest, database_name: str, table_name: str, credentials: dict
) -> None:
    """Cleans the database and table created by insert_data_into_mysql_and_validate_replication.

    Args:
        ops_test: The ops test framework
        database_name: The name of the database to drop
        table_name: The name of the table to drop
        credentials: The credentials to use to connect to the MySQL database
    """
    mysql_application_name = get_application_name(ops_test, "mysql")

    assert mysql_application_name, "MySQL application not found"

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]

    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_address = await get_unit_address(ops_test, primary.name)

    clean_up_database_and_table_sql = [
        f"DROP TABLE IF EXISTS `{database_name}`.`{table_name}`",
        f"DROP DATABASE IF EXISTS `{database_name}`",
    ]

    execute_queries_on_unit(
        primary_address,
        credentials["username"],
        credentials["password"],
        clean_up_database_and_table_sql,
        commit=True,
    )
