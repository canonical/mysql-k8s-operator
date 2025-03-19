#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml

from .high_availability_helpers import CLUSTER_NAME, delete_pod

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
TIMEOUT = 15 * 60


@pytest.mark.abort_on_fail
async def test_crash_during_cluster_setup(ops_test, charm) -> None:
    """Test primary crash during startup.

    It must recover/end setup when the primary got offline.
    """
    config = {"cluster-name": CLUSTER_NAME, "profile": "testing"}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    logger.info("Deploying 1 units of mysql-k8s")
    mysql_application = await ops_test.model.deploy(
        charm,
        application_name=APP_NAME,
        config=config,
        resources=resources,
        num_units=1,
        base="ubuntu@22.04",
        trust=True,
    )

    logger.info("Waiting for single unit to be ready")
    await ops_test.model.block_until(lambda: mysql_application.status == "active", timeout=TIMEOUT)

    # leader unit is the 1st unit
    leader_unit = mysql_application.units[0]

    logger.info("Scaling to 3 units and wait until application enters waiting status")
    await asyncio.gather(
        ops_test.model.block_until(
            lambda: len(mysql_application.units) == 3, timeout=TIMEOUT, wait_period=0.1
        ),
        ops_test.model.applications[APP_NAME].scale(3),
    )

    logger.info("Deleting pod")
    delete_pod(ops_test, leader_unit)

    async with ops_test.fast_forward("60s"):
        logger.info("Waiting until cluster is fully active")
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            timeout=TIMEOUT,
            wait_for_exact_units=3,
        )
