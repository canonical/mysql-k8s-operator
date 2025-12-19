# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju
from mysql.connector.errors import OperationalError

from ..connector import create_db_connections
from ..helpers_ha import CHARM_METADATA, MINUTE_SECS, get_app_units, get_unit_address

logger = logging.getLogger(__name__)

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)

MYSQL_APP_NAME = "mysql"
TEST_APP_NAME = "app"
CONNECTIONS = 10


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Build the charm and deploy 1 units to ensure a cluster is formed."""
    juju.deploy(
        charm,
        MYSQL_APP_NAME,
        config={"profile-limit-memory": "2000", "experimental-max-connections": CONNECTIONS},
        num_units=1,
        base="ubuntu@22.04",
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        trust=True,
    )


@pytest.mark.abort_on_fail
def test_deploy_and_relate_test_app(juju: Juju) -> None:
    config = {"auto_start_writes": False, "sleep_interval": "500"}
    logger.info("Deploying test app")
    juju.deploy(
        "mysql-test-app",
        TEST_APP_NAME,
        num_units=1,
        base="ubuntu@22.04",
        config=config,
        channel="latest/edge",
    )

    logger.info("Relating test app to mysql")
    juju.integrate(MYSQL_APP_NAME, f"{TEST_APP_NAME}:database")

    logger.info("Waiting all to be active")
    juju.wait(
        jubilant_backports.all_active,
        timeout=10 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_saturate_max_connections(juju: Juju) -> None:
    app_unit_name = get_app_units(juju, TEST_APP_NAME)[0]
    mysql_unit_name = get_app_units(juju, MYSQL_APP_NAME)[0]

    host_ip = get_unit_address(juju, MYSQL_APP_NAME, mysql_unit_name)

    logger.info("Running action to get app connection data")
    credentials = juju.run(app_unit_name, "get-client-connection-data").results
    if "return-code" in credentials:
        # juju 2.9 dont have the return-code key
        del credentials["return-code"]
    if "Code" in credentials:
        del credentials["Code"]
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
    juju.run(mysql_unit_name, "get-cluster-status")
