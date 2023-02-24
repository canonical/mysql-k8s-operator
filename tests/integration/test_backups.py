#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import os
from pathlib import Path

import boto3
import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    execute_queries_on_unit,
    get_primary_unit,
    get_server_config_credentials,
    get_unit_address,
    rotate_credentials,
    scale_application,
)
from .high_availability.high_availability_helpers import (
    deploy_and_scale_mysql,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

CLOUD_CONFIGS = {
    "aws": {
        "endpoint": "https://s3.amazonaws.com",
        "bucket": "canonical-mysql",
        "path": "test",
        "region": "us-east-1",
    },
    "gcp": {
        "endpoint": "https://storage.googleapis.com",
        "bucket": "data-charms-testing",
        "path": "mysql-k8s",
        "region": "",
    },
}
CLOUD_CREDENTIALS = {
    "aws": {
        "access-key": os.environ["AWS_ACCESS_KEY"],
        "secret-key": os.environ["AWS_SECRET_KEY"],
    },
    "gcp": {
        "access-key": os.environ["GCP_ACCESS_KEY"],
        "secret-key": os.environ["GCP_SECRET_KEY"],
    },
}
S3_INTEGRATOR = "s3-integrator"
TIMEOUT = 10 * 60
CLUSTER_ADMIN_PASSWORD = "clusteradminpassword"
SERVER_CONFIG_PASSWORD = "serverconfigpassword"
ROOT_PASSWORD = "rootpassword"
DATABASE_NAME = "backup-database"
TABLE_NAME = "backup-table"

backups_by_cloud = {}
value_before_backup, value_after_backup = None, None


@pytest.fixture(scope="session", autouse=True)
def clean_backups_from_buckets() -> None:
    """Teardown to clean up created backups from clouds."""
    yield

    logger.info("Cleaning backups from cloud buckets")
    for cloud_name, config in CLOUD_CONFIGS.items():
        backup = backups_by_cloud.get(cloud_name)

        if not backup:
            continue

        session = boto3.session.Session(
            aws_access_key_id=CLOUD_CREDENTIALS[cloud_name]["access-key"],
            aws_secret_access_key=CLOUD_CREDENTIALS[cloud_name]["secret-key"],
            region_name=config["region"],
        )
        s3 = session.resource("s3", endpoint_url=config["endpoint"])
        bucket = s3.Bucket(config["bucket"])

        # GCS doesn't support batch delete operation, so delete the objects one by one
        backup_path = str(Path(config["path"]) / backups_by_cloud[cloud_name])
        for bucket_object in bucket.objects.filter(Prefix=backup_path):
            bucket_object.delete()


async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql charm gets deployed."""
    mysql_application_name = await deploy_and_scale_mysql(ops_test)

    mysql_unit = ops_test.model.units[f"{mysql_application_name}/0"]
    primary_mysql = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)

    logger.info("Rotating all mysql credentials")

    await rotate_credentials(
        primary_mysql, username="clusteradmin", password=CLUSTER_ADMIN_PASSWORD
    )
    await rotate_credentials(
        primary_mysql, username="serverconfig", password=SERVER_CONFIG_PASSWORD
    )
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
async def test_backup(ops_test: OpsTest) -> None:
    """Test to create a backup and list backups."""
    mysql_application_name = await deploy_and_scale_mysql(ops_test)

    global backups_by_cloud, value_before_backup, value_after_backup

    zeroth_unit = ops_test.model.units[f"{mysql_application_name}/0"]

    primary_unit = await get_primary_unit(ops_test, zeroth_unit, mysql_application_name)
    non_primary_units = [
        unit
        for unit in ops_test.model.applications[mysql_application_name].units
        if unit.name != primary_unit.name
    ]

    # insert data into cluster before
    logger.info("Inserting value before backup")
    value_before_backup = await insert_data_into_mysql_and_validate_replication(
        ops_test,
        DATABASE_NAME,
        TABLE_NAME,
    )

    for cloud_name, config in CLOUD_CONFIGS.items():
        # set the s3 config and credentials
        logger.info(f"Syncing credentials for {cloud_name}")

        await ops_test.model.applications[S3_INTEGRATOR].set_config(config)
        action = await ops_test.model.units[f"{S3_INTEGRATOR}/0"].run_action(
            "sync-s3-credentials", **CLOUD_CREDENTIALS[cloud_name]
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

        # create backup
        logger.info("Creating backup")

        action = await non_primary_units[0].run_action(action_name="create-backup")
        result = await action.wait()
        backup_id = result.results["backup-id"]

        # list backups again and ensure new backup id exists
        logger.info("Listing backup ids post backup")

        action = await zeroth_unit.run_action(action_name="list-backups")
        result = await action.wait()
        new_backup_ids = json.loads(result.results["backup-ids"])

        assert sorted(new_backup_ids) == sorted(backup_ids + [backup_id])

        backups_by_cloud[cloud_name] = backup_id

    # insert data into cluster after backup
    logger.info("Inserting value after backup")
    value_after_backup = await insert_data_into_mysql_and_validate_replication(
        ops_test,
        DATABASE_NAME,
        TABLE_NAME,
    )


@pytest.mark.abort_on_fail
async def test_restore_on_same_cluster(ops_test: OpsTest) -> None:
    """Test to restore a backup to the same mysql cluster."""
    mysql_application_name = await deploy_and_scale_mysql(ops_test)

    logger.info("Scaling mysql application to 1 unit")
    async with ops_test.fast_forward():
        await scale_application(ops_test, mysql_application_name, 1)

    mysql_unit = ops_test.model.units[f"{mysql_application_name}/0"]
    mysql_unit_address = await get_unit_address(ops_test, mysql_unit.name)
    server_config_credentials = await get_server_config_credentials(mysql_unit)

    for cloud_name, config in CLOUD_CONFIGS.items():
        assert backups_by_cloud[cloud_name]

        # set the s3 config and credentials
        logger.info(f"Syncing credentials for {cloud_name}")

        await ops_test.model.applications[S3_INTEGRATOR].set_config(config)
        action = await ops_test.model.units[f"{S3_INTEGRATOR}/0"].run_action(
            "sync-s3-credentials",
            **CLOUD_CREDENTIALS[cloud_name],
        )
        await action.wait()

        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name, S3_INTEGRATOR],
            status="active",
            timeout=TIMEOUT,
        )

        # restore the backup
        logger.info(f"Restoring backup with id {backups_by_cloud[cloud_name]}")

        action = await mysql_unit.run_action(
            action_name="restore", **{"backup-id": backups_by_cloud[cloud_name]}
        )
        result = await action.wait()
        assert result.results.get("Code") == "0"

        # ensure the correct inserted values exist
        logger.info(
            "Ensuring that the pre-backup inserted value exists in database, while post-backup inserted value does not"
        )
        select_values_sql = [f"SELECT id FROM `{DATABASE_NAME}`.`{TABLE_NAME}`"]

        values = await execute_queries_on_unit(
            mysql_unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_values_sql,
        )
        assert values == [value_before_backup]


@pytest.mark.abort_on_fail
async def test_restore_on_new_cluster(ops_test: OpsTest) -> None:
    """Test to restore a backup on a new mysql cluster."""
    logger.info("Deploying a new mysql cluster")

    new_mysql_application_name = await deploy_and_scale_mysql(
        ops_test,
        check_for_existing_application=False,
        mysql_application_name="another-mysql-k8s",
        num_units=1,
    )

    # relate to S3 integrator
    await ops_test.model.relate(new_mysql_application_name, S3_INTEGRATOR)

    await ops_test.model.wait_for_idle(
        apps=[new_mysql_application_name, S3_INTEGRATOR],
        status="active",
        timeout=TIMEOUT,
    )

    # rotate all credentials
    logger.info("Rotating all mysql credentials")

    primary_mysql = ops_test.model.units[f"{new_mysql_application_name}/0"]
    primary_unit_address = await get_unit_address(ops_test, primary_mysql.name)

    await rotate_credentials(
        primary_mysql, username="clusteradmin", password=CLUSTER_ADMIN_PASSWORD
    )
    await rotate_credentials(
        primary_mysql, username="serverconfig", password=SERVER_CONFIG_PASSWORD
    )
    await rotate_credentials(primary_mysql, username="root", password=ROOT_PASSWORD)

    server_config_credentials = await get_server_config_credentials(primary_mysql)

    for cloud_name, config in CLOUD_CONFIGS.items():
        assert backups_by_cloud[cloud_name]

        # set the s3 config and credentials
        logger.info(f"Syncing credentials for {cloud_name}")

        await ops_test.model.applications[S3_INTEGRATOR].set_config(config)
        action = await ops_test.model.units[f"{S3_INTEGRATOR}/0"].run_action(
            "sync-s3-credentials",
            **CLOUD_CREDENTIALS[cloud_name],
        )
        await action.wait()

        await ops_test.model.wait_for_idle(
            apps=[new_mysql_application_name, S3_INTEGRATOR],
            status="active",
            timeout=TIMEOUT,
        )

        # restore the backup
        logger.info(f"Restoring backup with id {backups_by_cloud[cloud_name]}")

        action = await primary_mysql.run_action(
            action_name="restore", **{"backup-id": backups_by_cloud[cloud_name]}
        )
        result = await action.wait()
        assert result.results.get("Code") == "0"

        # ensure the correct inserted values exist
        logger.info(
            "Ensuring that the pre-backup inserted value exists in database, while post-backup inserted value does not"
        )
        select_values_sql = [f"SELECT id FROM `{DATABASE_NAME}`.`{TABLE_NAME}`"]

        values = await execute_queries_on_unit(
            primary_unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_values_sql,
        )
        assert values == [value_before_backup]
