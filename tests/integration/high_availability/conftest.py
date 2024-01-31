#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import pathlib

import pytest
from pytest_operator.plugin import OpsTest

from .. import juju_
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
    await juju_.run_action(application_unit, "clear-continuous-writes")
    await juju_.run_action(application_unit, "start-continuous-writes")

    yield

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
