#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import pathlib

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from .. import juju_
from .high_availability_helpers import (
    APPLICATION_DEFAULT_APP_NAME,
    deploy_and_scale_application,
    deploy_and_scale_mysql,
    deploy_chaos_mesh,
    destroy_chaos_mesh,
    relate_mysql_and_application,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
async def continuous_writes(ops_test: OpsTest) -> None:
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    application_unit = ops_test.model.applications[APPLICATION_DEFAULT_APP_NAME].units[0]
    logger.info("Clearing continuous writes")
    await juju_.run_action(application_unit, "clear-continuous-writes")
    logger.info("Starting continuous writes")
    await juju_.run_action(application_unit, "start-continuous-writes")

    yield

    for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(30)):
        with attempt:
            logger.info("Clearing continuous writes")
            await juju_.run_action(application_unit, "clear-continuous-writes")


@pytest.fixture()
def chaos_mesh(ops_test: OpsTest) -> None:
    """Deploys chaos mesh to the namespace and uninstalls it at the end."""
    deploy_chaos_mesh(ops_test.model.info.name)

    yield

    logger.info("Destroying chaos mesh")
    destroy_chaos_mesh(ops_test.model.info.name)


@pytest.fixture()
def built_charm(ops_test: OpsTest) -> pathlib.Path:
    """Return the path of a previously built charm."""
    if os.environ.get("CI") == "true":
        return
    charms_dst_dir = ops_test.tmp_path / "charms"
    packed_charm = list(charms_dst_dir.glob("*.charm"))
    return packed_charm[0].resolve(strict=True)


@pytest.fixture(scope="module")
async def highly_available_cluster(ops_test: OpsTest):
    """Run the set up for high availability tests.

    Args:
        ops_test: The ops test framework
    """
    logger.info("Deploying mysql-k8s and scaling to 3 units")
    mysql_application_name = await deploy_and_scale_mysql(ops_test)

    logger.info("Deploying mysql-test-app")
    application_name = await deploy_and_scale_application(ops_test)

    logger.info("Relating mysql-k8s with mysql-test-app")
    await relate_mysql_and_application(ops_test, mysql_application_name, application_name)

    yield
