#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest

from .high_availability_helpers import (
    APPLICATION_DEFAULT_APP_NAME,
    deploy_chaos_mesh,
    destroy_chaos_mesh,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
async def continuous_writes(ops_test: OpsTest) -> None:
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    application_unit = ops_test.model.applications[APPLICATION_DEFAULT_APP_NAME].units[0]

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()

    start_writes_action = await application_unit.run_action("start-continuous-writes")
    await start_writes_action.wait()

    yield

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()


@pytest.fixture(scope="function")
def chaos_mesh(ops_test: OpsTest) -> None:
    """Deploys chaos mesh to the namespace and uninstalls it at the end."""
    deploy_chaos_mesh(ops_test.model.info.name)

    yield

    logger.info("Destroying chaos mesh")
    destroy_chaos_mesh(ops_test.model.info.name)
