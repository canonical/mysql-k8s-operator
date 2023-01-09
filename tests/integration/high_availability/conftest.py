#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest

from constants import CONTAINER_NAME, MYSQLD_SERVICE
from tests.integration.high_availability.high_availability_helpers import (
    deploy_chaos_mesh,
    destroy_chaos_mesh,
    get_application_name,
    modify_pebble_restart_delay,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
async def continuous_writes(ops_test: OpsTest) -> None:
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    application_name = await get_application_name(ops_test, "application")

    application_unit = ops_test.model.applications[application_name].units[0]

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()

    start_writes_action = await application_unit.run_action("start-continuous-writes")
    await start_writes_action.wait()

    yield

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()


@pytest.fixture()
async def chaos_mesh(ops_test: OpsTest) -> None:
    """Deploys choas mesh to the namespace and uninstalls it at the end."""
    deploy_chaos_mesh(ops_test.model.info.name)

    yield

    destroy_chaos_mesh(ops_test.model.info.name)


@pytest.fixture()
async def restart_policy(ops_test: OpsTest) -> None:
    """Sets and resets service pebble restart policy on all units."""
    mysql_application_name = await get_application_name(ops_test, "mysql")

    for unit in ops_test.model.applications[mysql_application_name].units:
        modify_pebble_restart_delay(
            ops_test,
            unit.name,
            CONTAINER_NAME,
            MYSQLD_SERVICE,
            "tests/integration/high_availability/manifests/extend_pebble_restart_delay.yml",
        )

        async with ops_test.fast_forward():
            await ops_test.model.wait_for_idle(
                apps=[mysql_application_name],
                status="active",
                raise_on_blocked=True,
                timeout=5 * 60,
                idle_period=30,
            )

    yield

    for unit in ops_test.model.applications[mysql_application_name].units:
        modify_pebble_restart_delay(
            ops_test,
            unit.name,
            CONTAINER_NAME,
            MYSQLD_SERVICE,
            "tests/integration/high_availability/manifests/reduce_pebble_restart_delay.yml",
        )

        async with ops_test.fast_forward():
            await ops_test.model.wait_for_idle(
                apps=[mysql_application_name],
                status="active",
                raise_on_blocked=True,
                timeout=5 * 60,
                idle_period=30,
            )
