# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers import generate_random_string
from ...helpers_ha import (
    CHARM_METADATA,
    delete_k8s_pod,
    get_app_units,
    insert_mysql_test_data,
    remove_mysql_test_data,
    scale_app_units,
    verify_mysql_test_data,
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
def test_single_unit_pod_delete(juju: Juju) -> None:
    """Delete the pod in a single unit deployment and write data to new pod."""
    logging.info("Scale mysql application to 1 unit that is active")
    scale_app_units(juju, MYSQL_APP_NAME, 1)

    mysql_units = get_app_units(juju, MYSQL_APP_NAME)

    logging.info("Delete pod for the the mysql unit")
    delete_k8s_pod(juju, mysql_units[0])

    logging.info("Wait for a new pod to be created by k8s")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )

    logging.info("Write data to unit and verify that data was written")
    table_name = "data"
    table_value = generate_random_string(255)

    insert_mysql_test_data(juju, MYSQL_APP_NAME, table_name, table_value)
    verify_mysql_test_data(juju, MYSQL_APP_NAME, table_name, table_value)
    remove_mysql_test_data(juju, MYSQL_APP_NAME, table_name)
