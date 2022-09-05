#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import is_relation_broken, is_relation_joined
from pytest_operator.plugin import OpsTest

from constants import CLUSTER_ADMIN_USERNAME, PASSWORD_LENGTH
from tests.integration.helpers import (
    fetch_credentials,
    get_primary_unit,
    rotate_credentials,
)
from utils import generate_random_password

logger = logging.getLogger(__name__)

DB_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
DATABASE_APP_NAME = DB_METADATA["name"]
CLUSTER_NAME = "test_cluster"

APP_METADATA = yaml.safe_load(
    Path("./tests/integration/application-charm/metadata.yaml").read_text()
)
APPLICATION_APP_NAME = APP_METADATA["name"]

APPS = [DATABASE_APP_NAME, APPLICATION_APP_NAME]

ENDPOINT = "database"


@pytest.mark.order(1)
@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
@pytest.mark.database_tests
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    # Build and deploy charm from local source folder
    db_charm = await ops_test.build_charm(".")
    app_charm = await ops_test.build_charm("./tests/integration/application-charm/")

    config = {"cluster-name": CLUSTER_NAME}
    resources = {"mysql-image": DB_METADATA["resources"]["mysql-image"]["upstream-source"]}

    await asyncio.gather(
        ops_test.model.deploy(
            db_charm,
            application_name=DATABASE_APP_NAME,
            config=config,
            num_units=3,
            resources=resources,
        ),
        ops_test.model.deploy(app_charm, application_name=APPLICATION_APP_NAME, num_units=2),
    )

    # Reduce the update_status frequency until the cluster is deployed
    async with ops_test.fast_forward():

        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[DATABASE_APP_NAME].units) == 3
        )

        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APPLICATION_APP_NAME].units) == 2
        )

        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[DATABASE_APP_NAME],
                status="active",
                raise_on_blocked=True,
                timeout=1000,
            ),
            ops_test.model.wait_for_idle(
                apps=[APPLICATION_APP_NAME],
                status="waiting",
                raise_on_blocked=True,
                timeout=1000,
            ),
        )

    assert len(ops_test.model.applications[DATABASE_APP_NAME].units) == 3

    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        assert unit.workload_status == "active"

    assert len(ops_test.model.applications[APPLICATION_APP_NAME].units) == 2


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.database_tests
async def test_password_rotation(ops_test: OpsTest):
    """Rotate password and confirm changes."""
    num_units = len(ops_test.model.applications[DATABASE_APP_NAME].units)
    random_unit = ops_test.model.applications[DATABASE_APP_NAME].units[num_units - 1]

    old_credentials = await fetch_credentials(random_unit, CLUSTER_ADMIN_USERNAME)

    primary_unit = await get_primary_unit(ops_test, random_unit, DATABASE_APP_NAME)
    primary_unit_address = await primary_unit.get_public_address()
    logger.debug(
        "Test succeeded Primary unit detected before password rotation is %s", primary_unit_address
    )

    new_password = generate_random_password(PASSWORD_LENGTH)

    await rotate_credentials(
        unit=primary_unit, username=CLUSTER_ADMIN_USERNAME, password=new_password
    )

    updated_credentials = await fetch_credentials(random_unit, CLUSTER_ADMIN_USERNAME)
    assert updated_credentials["password"] != old_credentials["password"]
    assert updated_credentials["password"] == new_password

    primary_unit = await get_primary_unit(ops_test, random_unit, DATABASE_APP_NAME)
    primary_unit_address = await primary_unit.get_public_address()
    logger.debug(
        "Test succeeded Primary unit detected after password rotation is %s", primary_unit_address
    )


@pytest.mark.order(3)
@pytest.mark.abort_on_fail
@pytest.mark.database_tests
async def test_password_rotation_silent(ops_test: OpsTest):
    """Rotate password and confirm changes."""
    num_units = len(ops_test.model.applications[DATABASE_APP_NAME].units)
    random_unit = ops_test.model.applications[DATABASE_APP_NAME].units[num_units - 1]

    old_credentials = await fetch_credentials(random_unit, CLUSTER_ADMIN_USERNAME)

    primary_unit = await get_primary_unit(ops_test, random_unit, DATABASE_APP_NAME)
    primary_unit_address = await primary_unit.get_public_address()
    logger.debug(
        "Test succeeded Primary unit detected before password rotation is %s", primary_unit_address
    )

    await rotate_credentials(unit=primary_unit, username=CLUSTER_ADMIN_USERNAME)

    updated_credentials = await fetch_credentials(random_unit, CLUSTER_ADMIN_USERNAME)
    assert updated_credentials["password"] != old_credentials["password"]

    primary_unit = await get_primary_unit(ops_test, random_unit, DATABASE_APP_NAME)
    primary_unit_address = await primary_unit.get_public_address()
    logger.debug(
        "Test succeeded Primary unit detected after password rotation is %s", primary_unit_address
    )


@pytest.mark.order(4)
@pytest.mark.abort_on_fail
@pytest.mark.database_tests
async def test_relation_creation(ops_test: OpsTest):
    """Relate charms and wait for the expected changes in status."""
    await ops_test.model.relate(APPLICATION_APP_NAME, f"{DATABASE_APP_NAME}:{ENDPOINT}")

    async with ops_test.fast_forward():
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, ENDPOINT, ENDPOINT) == True  # noqa: E712
        )

        await ops_test.model.wait_for_idle(apps=APPS, status="active")


@pytest.mark.order(5)
@pytest.mark.abort_on_fail
@pytest.mark.database_tests
async def test_relation_broken(ops_test: OpsTest):
    """Remove relation and wait for the expected changes in status."""
    await ops_test.model.applications[DATABASE_APP_NAME].remove_relation(
        f"{APPLICATION_APP_NAME}:{ENDPOINT}", f"{DATABASE_APP_NAME}:{ENDPOINT}"
    )

    await ops_test.model.block_until(
        lambda: is_relation_broken(ops_test, ENDPOINT, ENDPOINT) == True  # noqa: E712
    )

    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[DATABASE_APP_NAME], status="active", raise_on_blocked=True
            ),
            ops_test.model.wait_for_idle(
                apps=[APPLICATION_APP_NAME], status="waiting", raise_on_blocked=True
            ),
        )
