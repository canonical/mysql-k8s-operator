#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest

from ..helpers import get_unit_address
from .high_availability_helpers import (
    deploy_and_scale_application,
    deploy_and_scale_mysql,
    get_endpoint_addresses,
    relate_mysql_and_application,
)

logger = logging.getLogger(__name__)

MYSQL_CLUSTER_ONE = "mysql1"
MYSQL_CLUSTER_TWO = "mysql2"
MYSQL_CLUSTER_NAME = "test_cluster"
TEST_APP_ONE = "mysql-test-app1"
TEST_APP_TWO = "mysql-test-app2"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_labeling_of_k8s_endpoints(ops_test: OpsTest):
    """Test the labeling of k8s endpoints when apps with same cluster-name deployed."""
    logger.info("Deploying first mysql cluster")
    mysql_cluster_one = await deploy_and_scale_mysql(
        ops_test,
        check_for_existing_application=False,
        mysql_application_name=MYSQL_CLUSTER_ONE,
        cluster_name=MYSQL_CLUSTER_NAME,
    )

    logger.info("Deploying and relating test app with cluster")
    await deploy_and_scale_application(
        ops_test,
        check_for_existing_application=False,
        test_application_name=TEST_APP_ONE,
    )

    await relate_mysql_and_application(
        ops_test,
        mysql_application_name=MYSQL_CLUSTER_ONE,
        application_name=TEST_APP_ONE,
    )

    logger.info("Deploying second mysql application with same cluster name")
    mysql_cluster_two = await deploy_and_scale_mysql(
        ops_test,
        check_for_existing_application=False,
        mysql_application_name=MYSQL_CLUSTER_TWO,
        cluster_name=MYSQL_CLUSTER_NAME,
    )

    logger.info("Deploying and relating another test app with second cluster")
    await deploy_and_scale_application(
        ops_test,
        check_for_existing_application=False,
        test_application_name=TEST_APP_TWO,
    )

    await relate_mysql_and_application(
        ops_test,
        mysql_application_name=MYSQL_CLUSTER_TWO,
        application_name=TEST_APP_TWO,
    )

    logger.info("Ensuring that the created k8s endpoints have correct addresses")
    cluster_one_ips = [
        await get_unit_address(ops_test, unit.name)
        for unit in ops_test.model.applications[mysql_cluster_one].units
    ]

    cluster_one_primary_addresses = get_endpoint_addresses(
        ops_test, f"{mysql_cluster_one}-primary"
    )
    cluster_one_replica_addresses = get_endpoint_addresses(
        ops_test, f"{mysql_cluster_one}-replicas"
    )

    for primary in cluster_one_primary_addresses:
        assert (
            primary in cluster_one_ips
        ), f"{primary} (not belonging to cluster 1) should not be in cluster one addresses"

    assert set(cluster_one_primary_addresses + cluster_one_replica_addresses) == set(
        cluster_one_ips
    ), "IPs not belonging to cluster one in cluster one addresses"

    cluster_two_ips = [
        await get_unit_address(ops_test, unit.name)
        for unit in ops_test.model.applications[mysql_cluster_two].units
    ]

    cluster_two_primary_addresses = get_endpoint_addresses(
        ops_test, f"{mysql_cluster_two}-primary"
    )
    cluster_two_replica_addresses = get_endpoint_addresses(
        ops_test, f"{mysql_cluster_two}-replicas"
    )

    for primary in cluster_two_primary_addresses:
        assert (
            primary in cluster_two_ips
        ), f"{primary} (not belonging to cluster w) should not be in cluster two addresses"

    assert set(cluster_two_primary_addresses + cluster_two_replica_addresses) == set(
        cluster_two_ips
    ), "IPs not belonging to cluster two in cluster two addresses"
