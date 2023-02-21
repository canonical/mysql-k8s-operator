#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import os
import pytest

from pytest_operator.plugin import OpsTest

from .high_availability.high_availability_helpers import (
    ensure_all_units_continuous_writes_incrementing,
    high_availability_test_setup,
)
from .helpers import get_primary_unit, rotate_credentials

logger = logging.getLogger(__name__)

CLOUD_CONFIGS = {
    "aws": {
        "endpoint": "https://s3.amazonaws.com",
        "bucket": "mysql-backups-development",
        "path": "test",
        "region": "us-east-1",
    },
}
CLOUD_CREDENTIALS = {
    "aws": {
        "access-key": os.environ.get("AWS_ACCESS_KEY"),
        "secret-key": os.environ.get("AWS_SECRET_KEY"),
    },
}
S3_INTEGRATOR = "s3-integrator"
TIMEOUT = 10 * 60
CLUSTER_ADMIN_PASSWORD = "clusteradminpassword"
SERVER_CONFIG_PASSWORD = "serverconfigpassword"
ROOT_PASSWORD = "rootpassword"

backups_by_cloud = {}


async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    mysql_unit = ops_test.model.units.get(f"{mysql_application_name}/0")
    primary_mysql = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    logger.info("Rotating all mysql credentials")

    await rotate_credentials(primary_mysql, username="clusteradmin", password=CLUSTER_ADMIN_PASSWORD)
    await rotate_credentials(primary_mysql, username="serverconfig", password=SERVER_CONFIG_PASSWORD)
    await rotate_credentials(primary_mysql, username="root", password=ROOT_PASSWORD)

    # deploy and relate to s3-integrator
    logger.info("Deploying s3 integrator")

    await ops_test.model.deploy(S3_INTEGRATOR, channel="edge")
    await ops_test.model.relate(mysql_application_name, S3_INTEGRATOR)

    await ops_test.model.wait_for_idle(
        apps=[S3_INTEGRATOR],
        status="blocked",
        raise_on_blocked=False,
        timeout=TIMEOUT,
    )


@pytest.mark.abort_on_fail
async def test_backup(ops_test: OpsTest, continuous_writes) -> None:
    """Test to create a backup and list backups."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    global backups_by_cloud

    zeroth_unit = ops_test.model.units.get(f"{mysql_application_name}/0")

    primary_unit = await get_primary_unit(ops_test, zeroth_unit, mysql_application_name)
    non_primary_units = [
        unit
        for unit in ops_test.model.applications[mysql_application_name].units
        if unit.name != primary_unit.name
    ]

    for cloud_name, config in CLOUD_CONFIGS.items():
        # set the s3 config and credentials
        logger.info(f"Syncing credentials for {cloud_name}")

        await ops_test.model.applications[S3_INTEGRATOR].set_config(config)
        action = await ops_test.model.units.get(f"{S3_INTEGRATOR}/0").run_action(
            "sync-s3-credentials",
            **CLOUD_CREDENTIALS[cloud_name]
        )
        await action.wait()

        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name, S3_INTEGRATOR],
            status="active",
            timeout=TIMEOUT,
        )

        # list backups
        logger.info("Listing existing backup ids")

        action = await zeroth_unit.run_action(action_name="list-backups")
        result = await action.wait()
        backup_ids = json.loads(result.results["backup-ids"])

        # ensure continuous writes
        logger.info("Ensuring all units continuous writes incrementing pre backup")

        await ensure_all_units_continuous_writes_incrementing(ops_test)

        # create backup
        logger.info("Creating backup")

        action = await non_primary_units[0].run_action(action_name="create-backup")
        result = await action.wait()
        backup_id = result.results["backup-id"]

        # ensure continuous writes
        logger.info("Ensuring all units continuous writes incrementing post backup")

        await ensure_all_units_continuous_writes_incrementing(ops_test)

        # list backups again and ensure new backup id exists
        logger.info("Listing backup ids post backup")

        action = await zeroth_unit.run_action(action_name="list-backups")
        result = await action.wait()
        new_backup_ids = json.loads(result.results["backup-ids"])

        assert sorted(new_backup_ids) == sorted(backup_ids + [backup_id])

        backups_by_cloud[cloud_name] = backup_id
        