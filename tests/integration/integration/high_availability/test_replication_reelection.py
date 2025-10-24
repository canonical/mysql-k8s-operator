# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers import generate_random_string
from .high_availability_helpers_new import (
    CHARM_METADATA,
    check_mysql_instances_online,
    check_mysql_units_writes_increment,
    delete_k8s_pod,
    get_mysql_primary_unit,
    insert_mysql_test_data,
    remove_mysql_test_data,
    wait_for_apps_status,
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
def test_kill_primary_check_reelection(juju: Juju) -> None:
    """Confirm that a new primary is elected when the current primary is tear down."""
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)

    mysql_old_primary = get_mysql_primary_unit(juju, MYSQL_APP_NAME)

    logging.info("Killing the primary pod")
    delete_k8s_pod(juju, mysql_old_primary)

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )

    # Confirm that the new primary unit is different
    mysql_new_primary = get_mysql_primary_unit(juju, MYSQL_APP_NAME)
    assert mysql_new_primary != mysql_old_primary, "Primary has not changed"

    # Retry until the killed pod is back online in the mysql cluster
    assert check_mysql_instances_online(juju, MYSQL_APP_NAME)

    table_name = "data"
    table_value = generate_random_string(255)

    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)
    insert_mysql_test_data(juju, MYSQL_APP_NAME, table_name, table_value)
    remove_mysql_test_data(juju, MYSQL_APP_NAME, table_name)
