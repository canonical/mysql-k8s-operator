# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from .high_availability_helpers_new import (
    CHARM_METADATA,
    check_mysql_instances_online,
    check_mysql_units_writes_increment,
    get_app_units,
    start_mysqld_service,
    stop_mysqld_service,
    update_interval,
    wait_for_apps_status,
    wait_for_unit_status,
)

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_TEST_APP_NAME = "mysql-test-app"

MINUTE_SECS = 60

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


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
async def test_graceful_full_cluster_crash(juju: Juju, continuous_writes_new) -> None:
    """Pause test.

    A graceful simultaneous restart of all instances,
    check primary election after the start, write and read data
    """
    # Ensure continuous writes still incrementing for all units
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)

    mysql_units = get_app_units(juju, MYSQL_APP_NAME)

    logging.info("Stopping all instances")
    for unit_name in mysql_units:
        stop_mysqld_service(juju, unit_name)

    logging.info("Starting all instances")
    for unit_name in mysql_units:
        start_mysqld_service(juju, unit_name)

    with update_interval(juju, "10s"):
        logging.info("Waiting units to enter maintenance")
        juju.wait(
            ready=lambda status: all((
                wait_for_unit_status(MYSQL_APP_NAME, f"{MYSQL_APP_NAME}/0", "maintenance")(status),
                wait_for_unit_status(MYSQL_APP_NAME, f"{MYSQL_APP_NAME}/1", "maintenance")(status),
                wait_for_unit_status(MYSQL_APP_NAME, f"{MYSQL_APP_NAME}/2", "maintenance")(status),
            )),
            timeout=20 * MINUTE_SECS,
        )
        logging.info("Waiting units to be back online")
        juju.wait(
            ready=lambda status: all((
                wait_for_unit_status(MYSQL_APP_NAME, f"{MYSQL_APP_NAME}/0", "active")(status),
                wait_for_unit_status(MYSQL_APP_NAME, f"{MYSQL_APP_NAME}/1", "active")(status),
                wait_for_unit_status(MYSQL_APP_NAME, f"{MYSQL_APP_NAME}/2", "active")(status),
            )),
            timeout=20 * MINUTE_SECS,
        )

    logging.info("Check that all units are online")
    assert check_mysql_instances_online(juju, MYSQL_APP_NAME, mysql_units)

    # Ensure continuous writes still incrementing for all units
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)
