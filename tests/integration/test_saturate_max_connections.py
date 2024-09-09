# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from mysql.connector.errors import OperationalError
from pytest_operator.plugin import OpsTest

from .connector import create_db_connections
from .helpers import get_unit_address
from .juju_ import run_action

logger = logging.getLogger(__name__)

MYSQL_APP_NAME = "mysql"
TEST_APP_NAME = "app"
CONNECTIONS = 10
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build the charm and deploy 1 units to ensure a cluster is formed."""
    charm = await ops_test.build_charm(".")
    config = {"profile-limit-memory": "2000", "experimental-max-connections": CONNECTIONS}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    await ops_test.model.deploy(
        charm,
        application_name=MYSQL_APP_NAME,
        config=config,
        num_units=1,
        base="ubuntu@22.04",
        resources=resources,
        trust=True,
    )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy_and_relate_test_app(ops_test: OpsTest) -> None:
    config = {"auto_start_writes": False, "sleep_interval": "500"}
    logger.info("Deploying test app")
    await ops_test.model.deploy(
        "mysql-test-app",
        application_name=TEST_APP_NAME,
        num_units=1,
        base="ubuntu@22.04",
        config=config,
        channel="latest/edge",
    )

    logger.info("Relating test app to mysql")
    await ops_test.model.relate(MYSQL_APP_NAME, f"{TEST_APP_NAME}:database")

    logger.info("Waiting all to be active")
    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in ops_test.model.units.values()),
        timeout=60 * 10,
        wait_period=5,
    )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_saturate_max_connections(ops_test: OpsTest) -> None:
    app_unit = ops_test.model.applications[TEST_APP_NAME].units[0]
    mysql_unit = ops_test.model.applications[MYSQL_APP_NAME].units[0]

    host_ip = await get_unit_address(ops_test, mysql_unit.name)
    logger.info("Running action to get app connection data")
    credentials = await run_action(app_unit, "get-client-connection-data")
    if "return-code" in credentials:
        # juju 2.9 dont have the return-code key
        del credentials["return-code"]
    credentials["host"] = host_ip

    logger.info(f"Creating {CONNECTIONS} connections")
    connections = create_db_connections(CONNECTIONS, **credentials)
    assert isinstance(connections, list), "Connections not created"

    logger.info("Ensure all connections are established")
    for conn in connections:
        assert conn.is_connected(), "Connection failed to establish"

    assert len(connections) == CONNECTIONS, "Not all connections were established"

    logger.info("Ensure no more client connections are possible")

    with pytest.raises(OperationalError):
        # exception raised when too many connections are attempted
        create_db_connections(1, **credentials)

    logger.info("Get cluster status while connections are saturated")
    _ = await run_action(mysql_unit, "get-cluster-status")
