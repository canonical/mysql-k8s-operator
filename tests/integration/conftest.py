# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest

from constants import SERVER_CONFIG_USERNAME

from . import architecture, juju_
from .high_availability.high_availability_helpers import get_application_name

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def charm():
    # Return str instead of pathlib.Path since python-libjuju's model.deploy(), juju deploy, and
    # juju bundle files expect local charms to begin with `./` or `/` to distinguish them from
    # Charmhub charms.
    return f"./mysql-k8s_ubuntu@22.04-{architecture.architecture}.charm"


@pytest.fixture(scope="function")
async def credentials(ops_test: OpsTest):
    """Return the credentials for the MySQL cluster."""
    logger.info("Getting credentials for the MySQL cluster")
    mysql_app_name = get_application_name(ops_test, "mysql-k8s")
    unit = ops_test.model.applications[mysql_app_name].units[0]
    credentials = await juju_.run_action(unit, "get-password", username=SERVER_CONFIG_USERNAME)

    yield credentials
