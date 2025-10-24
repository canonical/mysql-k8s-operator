#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from ...helpers import is_relation_joined

logger = logging.getLogger(__name__)

DB_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

DATABASE_APP_NAME = DB_METADATA["name"]
DATABASE_ENDPOINT = "mysql-root"
APPLICATION_APP_NAME = "mysql-test-app"
APPLICATION_ENDPOINT = "mysql"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, charm):
    """Build the charm and deploy 3 units to ensure a cluster is formed."""
    config = {
        "profile": "testing",
        "mysql-root-interface-user": "test-user",
        "mysql-root-interface-database": "continuous_writes",
    }
    resources = {
        "mysql-image": DB_METADATA["resources"]["mysql-image"]["upstream-source"],
    }

    await asyncio.gather(
        ops_test.model.deploy(
            charm,
            application_name=DATABASE_APP_NAME,
            config=config,
            num_units=3,
            resources=resources,
            base="ubuntu@22.04",
            trust=True,
        ),
        ops_test.model.deploy(
            APPLICATION_APP_NAME,
            application_name=APPLICATION_APP_NAME,
            num_units=2,
            channel="latest/edge",
            base="ubuntu@22.04",
        ),
    )


@pytest.mark.abort_on_fail
async def test_relation_creation_eager(ops_test: OpsTest):
    """Relate charms before they have time to properly start.

    It simulates a Terraform-like deployment strategy
    """
    await ops_test.model.relate(
        f"{APPLICATION_APP_NAME}:{APPLICATION_ENDPOINT}",
        f"{DATABASE_APP_NAME}:{DATABASE_ENDPOINT}",
    )
    await ops_test.model.block_until(
        lambda: is_relation_joined(ops_test, APPLICATION_ENDPOINT, DATABASE_ENDPOINT) == True  # noqa: E712
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
                raise_on_error=False,
            ),
            ops_test.model.wait_for_idle(
                apps=[APPLICATION_APP_NAME],
                status="waiting",
                raise_on_blocked=True,
                timeout=1000,
            ),
        )
