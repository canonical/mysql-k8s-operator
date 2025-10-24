#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from collections.abc import Generator

import pytest
from jubilant_backports import Juju
from pytest_operator.plugin import OpsTest

from .high_availability_helpers import (
    deploy_and_scale_application,
    deploy_and_scale_mysql,
    deploy_chaos_mesh,
    destroy_chaos_mesh,
    relate_mysql_and_application,
)
from .high_availability_helpers_new import (
    get_app_leader,
)

MYSQL_TEST_APP_NAME = "mysql-test-app"

logger = logging.getLogger(__name__)


@pytest.fixture()
def continuous_writes(juju: Juju) -> Generator:
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    test_app_leader = get_app_leader(juju, MYSQL_TEST_APP_NAME)

    logging.info("Clearing continuous writes")
    juju.run(test_app_leader, "clear-continuous-writes")
    logging.info("Starting continuous writes")
    juju.run(test_app_leader, "start-continuous-writes")

    yield

    logging.info("Clearing continuous writes")
    juju.run(test_app_leader, "clear-continuous-writes")


@pytest.fixture()
def chaos_mesh(juju: Juju) -> Generator:
    """Deploys chaos mesh to the namespace and uninstalls it at the end."""
    logger.info("Deploying chaos mesh")
    deploy_chaos_mesh(juju.model)

    yield

    logger.info("Destroying chaos mesh")
    destroy_chaos_mesh(juju.model)


@pytest.fixture(scope="module")
async def highly_available_cluster(ops_test: OpsTest, charm):
    """Run the set up for high availability tests.

    Args:
        ops_test: The ops test framework
        charm: `charm` fixture
    """
    logger.info("Deploying mysql-k8s and scaling to 3 units")
    mysql_application_name = await deploy_and_scale_mysql(ops_test, charm)

    logger.info("Deploying mysql-test-app")
    application_name = await deploy_and_scale_application(ops_test)

    logger.info("Relating mysql-k8s with mysql-test-app")
    await relate_mysql_and_application(ops_test, mysql_application_name, application_name)

    yield
