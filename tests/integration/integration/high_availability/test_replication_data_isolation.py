# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers_ha import (
    CHARM_METADATA,
    insert_mysql_test_data,
    remove_mysql_test_data,
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


def test_cluster_data_isolation(juju: Juju, charm: str) -> None:
    """Test for cluster data isolation.

    This test creates a new cluster, create a new table on both cluster, write a single record with
    the application name for each cluster, retrieve and compare these records, asserting they are
    not the same.
    """
    mysql_main_app_name = f"{MYSQL_APP_NAME}"
    mysql_other_app_name = f"{MYSQL_APP_NAME}-other"

    juju.deploy(
        charm=charm,
        app=mysql_other_app_name,
        base="ubuntu@22.04",
        config={"profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        num_units=1,
    )

    logging.info("Wait for application to become active")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, mysql_other_app_name),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )

    table_name = "cluster_isolation_table"

    for app_name in (mysql_main_app_name, mysql_other_app_name):
        insert_mysql_test_data(juju, app_name, table_name, f"{app_name}-value")
    for app_name in (mysql_main_app_name, mysql_other_app_name):
        verify_mysql_test_data(juju, app_name, table_name, f"{app_name}-value")
    for app_name in (mysql_main_app_name, mysql_other_app_name):
        remove_mysql_test_data(juju, app_name, table_name)

    juju.remove_application(mysql_other_app_name, destroy_storage=True, force=True)
