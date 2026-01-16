#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from collections.abc import Generator

import pytest
from jubilant_backports import Juju

from ...helpers_ha import get_app_leader
from .high_availability_helpers import (
    deploy_chaos_mesh,
    destroy_chaos_mesh,
)

MYSQL_TEST_APP_NAME = "mysql-test-app"


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
    logging.info("Deploying chaos mesh")
    deploy_chaos_mesh(juju.model)

    yield

    logging.info("Destroying chaos mesh")
    destroy_chaos_mesh(juju.model)
