#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from .. import markers
from ..helpers import get_relation_data, is_relation_broken, is_relation_joined

logger = logging.getLogger(__name__)

DB_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
DATABASE_APP_NAME = DB_METADATA["name"]
CLUSTER_NAME = "test_cluster"

APPLICATION_APP_NAME = "mysql-test-app"

APPS = [DATABASE_APP_NAME, APPLICATION_APP_NAME]

ENDPOINT = "database"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    # Build and deploy charm from local source folder
    db_charm = await ops_test.build_charm(".")

    config = {"cluster-name": CLUSTER_NAME, "profile": "testing"}
    resources = {"mysql-image": DB_METADATA["resources"]["mysql-image"]["upstream-source"]}

    await asyncio.gather(
        ops_test.model.deploy(
            db_charm,
            application_name=DATABASE_APP_NAME,
            config=config,
            num_units=3,
            resources=resources,
            series="jammy",
            trust=True,
        ),
        ops_test.model.deploy(
            APPLICATION_APP_NAME,
            application_name=APPLICATION_APP_NAME,
            num_units=2,
            channel="latest/edge",
        ),
    )

    # Reduce the update_status frequency until the cluster is deployed
    async with ops_test.fast_forward("60s"):
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


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@markers.only_without_juju_secrets
async def test_relation_creation_databag(ops_test: OpsTest):
    """Relate charms and wait for the expected changes in status."""
    await ops_test.model.relate(APPLICATION_APP_NAME, f"{DATABASE_APP_NAME}:{ENDPOINT}")

    async with ops_test.fast_forward("60s"):
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, ENDPOINT, ENDPOINT) == True  # noqa: E712
        )

        await ops_test.model.wait_for_idle(apps=APPS, status="active")
    relation_data = await get_relation_data(ops_test, APPLICATION_APP_NAME, "database")
    assert set(["password", "username"]) <= set(relation_data[0]["application-data"])


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@markers.only_with_juju_secrets
async def test_relation_creation(ops_test: OpsTest):
    """Relate charms and wait for the expected changes in status."""
    await ops_test.model.relate(APPLICATION_APP_NAME, f"{DATABASE_APP_NAME}:{ENDPOINT}")

    async with ops_test.fast_forward("60s"):
        await ops_test.model.block_until(
            lambda: is_relation_joined(ops_test, ENDPOINT, ENDPOINT) == True  # noqa: E712
        )

        await ops_test.model.wait_for_idle(apps=APPS, status="active")
    relation_data = await get_relation_data(ops_test, APPLICATION_APP_NAME, "database")
    assert not set(["password", "username"]) <= set(relation_data[0]["application-data"])
    assert "secret-user" in relation_data[0]["application-data"]


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_relation_broken(ops_test: OpsTest):
    """Remove relation and wait for the expected changes in status."""
    await ops_test.model.applications[DATABASE_APP_NAME].remove_relation(
        f"{APPLICATION_APP_NAME}:{ENDPOINT}", f"{DATABASE_APP_NAME}:{ENDPOINT}"
    )

    await ops_test.model.block_until(
        lambda: is_relation_broken(ops_test, ENDPOINT, ENDPOINT) == True  # noqa: E712
    )

    async with ops_test.fast_forward("60s"):
        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[DATABASE_APP_NAME], status="active", raise_on_blocked=True
            ),
            ops_test.model.wait_for_idle(
                apps=[APPLICATION_APP_NAME], status="waiting", raise_on_blocked=True
            ),
        )
