# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers_ha import (
    CHARM_METADATA,
    check_mysql_units_writes_increment,
    execute_queries_on_unit,
    get_mysql_primary_unit,
    get_mysql_server_credentials,
    get_unit_address,
    start_mysqld_service,
    stop_mysqld_service,
    wait_for_apps_status,
    wait_for_unit_status,
)

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_PROCESS_NAME = "mysqld"
MYSQL_TEST_APP_NAME = "mysql-test-app"

MINUTE_SECS = 60


@pytest.mark.abort_on_fail
def test_deploy_highly_available_cluster(juju: Juju, charm: str) -> None:
    """Simple test to ensure that the MySQL and application charms get deployed."""
    logging.info("Deploying MySQL cluster")
    juju.deploy(
        charm=charm,
        app=MYSQL_APP_NAME,
        base="ubuntu@22.04",
        config={"profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        num_units=3,
    )
    juju.deploy(
        charm=MYSQL_TEST_APP_NAME,
        app=MYSQL_TEST_APP_NAME,
        base="ubuntu@22.04",
        channel="latest/edge",
        config={"sleep_interval": 300},
        num_units=1,
    )

    juju.integrate(
        f"{MYSQL_APP_NAME}:database",
        f"{MYSQL_TEST_APP_NAME}:database",
    )

    logging.info("Wait for applications to become active")
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, MYSQL_APP_NAME, MYSQL_TEST_APP_NAME
        ),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_cluster_manual_rejoin(juju: Juju, continuous_writes) -> None:
    """The cluster manual re-join test.

    A graceful restart is performed in one of the instances (choosing Primary to make it painful).
    In order to verify that the instance can come back ONLINE, after disabling automatic re-join
    """
    # Ensure continuous writes still incrementing for all units
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)

    mysql_primary_unit = get_mysql_primary_unit(juju, MYSQL_APP_NAME)

    credentials = get_mysql_server_credentials(juju, mysql_primary_unit)

    config = {
        "username": credentials["username"],
        "password": credentials["password"],
        "host": get_unit_address(juju, MYSQL_APP_NAME, mysql_primary_unit),
    }

    execute_queries_on_unit(
        unit_address=config["host"],
        username=config["username"],
        password=config["password"],
        queries=["SET PERSIST group_replication_autorejoin_tries=0"],
        commit=True,
    )

    logging.info(f"Stopping server on unit {mysql_primary_unit}")
    stop_mysqld_service(juju, mysql_primary_unit)

    logging.info(f"Starting server on unit {mysql_primary_unit}")
    start_mysqld_service(juju, mysql_primary_unit)

    logging.info("Waiting unit to be back online")
    juju.wait(
        ready=wait_for_unit_status(MYSQL_APP_NAME, mysql_primary_unit, "active"),
        timeout=20 * MINUTE_SECS,
    )

    # Ensure continuous writes still incrementing for all units
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)
