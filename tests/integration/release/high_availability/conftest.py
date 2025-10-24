# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from collections.abc import Generator

import pytest
from jubilant_backports import Juju

from .high_availability_helpers import (
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
