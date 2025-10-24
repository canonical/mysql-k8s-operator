# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju

from .high_availability_helpers_new import (
    CHARM_METADATA,
    get_app_units,
    get_k8s_endpoint_addresses,
    get_unit_address,
    update_interval,
    wait_for_apps_status,
)

MYSQL_APP_NAME_1 = "mysql-k8s1"
MYSQL_APP_NAME_2 = "mysql-k8s2"
MYSQL_APP_CLUSTER = "test-cluster"

MYSQL_TEST_APP_NAME_1 = "mysql-test-app1"
MYSQL_TEST_APP_NAME_2 = "mysql-test-app2"

MINUTE_SECS = 60

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


@pytest.mark.abort_on_fail
def test_deploy_highly_available_cluster_1(juju: Juju, charm: str) -> None:
    """Simple test to ensure that the MySQL and application charms get deployed."""
    logging.info("Deploying MySQL cluster")
    juju.deploy(
        charm=charm,
        app=MYSQL_APP_NAME_1,
        base="ubuntu@22.04",
        config={"cluster-name": MYSQL_APP_CLUSTER, "profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        num_units=3,
    )
    juju.deploy(
        charm="mysql-test-app",
        app=MYSQL_TEST_APP_NAME_1,
        base="ubuntu@22.04",
        channel="latest/edge",
        config={"sleep_interval": 300},
        num_units=1,
    )

    juju.integrate(
        f"{MYSQL_APP_NAME_1}:database",
        f"{MYSQL_TEST_APP_NAME_1}:database",
    )

    with update_interval(juju, "10s"):
        logging.info("Wait for applications to become active")
        juju.wait(
            ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_NAME_1),
            error=jubilant_backports.any_blocked,
            timeout=20 * MINUTE_SECS,
        )
        juju.wait(
            ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_TEST_APP_NAME_1),
            error=jubilant_backports.any_blocked,
            timeout=20 * MINUTE_SECS,
        )


@pytest.mark.abort_on_fail
def test_deploy_highly_available_cluster_2(juju: Juju, charm: str) -> None:
    """Simple test to ensure that the MySQL and application charms get deployed."""
    logging.info("Deploying MySQL cluster")
    juju.deploy(
        charm=charm,
        app=MYSQL_APP_NAME_2,
        base="ubuntu@22.04",
        config={"cluster-name": MYSQL_APP_CLUSTER, "profile": "testing"},
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        num_units=3,
    )
    juju.deploy(
        charm="mysql-test-app",
        app=MYSQL_TEST_APP_NAME_2,
        base="ubuntu@22.04",
        channel="latest/edge",
        config={"sleep_interval": 300},
        num_units=1,
    )

    juju.integrate(
        f"{MYSQL_APP_NAME_2}:database",
        f"{MYSQL_TEST_APP_NAME_2}:database",
    )

    with update_interval(juju, "10s"):
        logging.info("Wait for applications to become active")
        juju.wait(
            ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_NAME_2),
            error=jubilant_backports.any_blocked,
            timeout=20 * MINUTE_SECS,
        )
        juju.wait(
            ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_TEST_APP_NAME_2),
            error=jubilant_backports.any_blocked,
            timeout=20 * MINUTE_SECS,
        )


@pytest.mark.abort_on_fail
def test_labeling_of_k8s_endpoints(juju: Juju) -> None:
    """Test the labeling of k8s endpoints when apps with same cluster-name deployed."""
    logging.info("Ensuring that the created k8s endpoints have correct addresses")
    check_endpoint_addresses(juju, MYSQL_APP_NAME_1)
    check_endpoint_addresses(juju, MYSQL_APP_NAME_2)


def check_endpoint_addresses(juju: Juju, mysql_app_name: str) -> None:
    """Check that the endpoints have correct addresses."""
    cluster_ips = [
        get_unit_address(juju, mysql_app_name, unit_name)
        for unit_name in get_app_units(juju, mysql_app_name)
    ]

    cluster_primary_addresses = get_k8s_endpoint_addresses(juju, f"{mysql_app_name}-primary")
    cluster_replica_addresses = get_k8s_endpoint_addresses(juju, f"{mysql_app_name}-replicas")

    for address in cluster_primary_addresses:
        assert address in cluster_ips, f"{address} is not in cluster {mysql_app_name} addresses"

    assert set(cluster_primary_addresses + cluster_replica_addresses) == set(cluster_ips)
