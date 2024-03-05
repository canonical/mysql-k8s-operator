#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import socket
import uuid
from pathlib import Path

import boto3
import pytest
import pytest_microceph
from pytest_operator.plugin import OpsTest

from . import juju_
from .helpers import (
    execute_queries_on_unit,
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

host_ip = socket.gethostbyname(socket.gethostname())

S3_INTEGRATOR = "s3-integrator"
TIMEOUT = 10 * 60
CLUSTER_ADMIN_PASSWORD = "clusteradminpassword"
SERVER_CONFIG_PASSWORD = "serverconfigpassword"
ROOT_PASSWORD = "rootpassword"
DATABASE_NAME = "backup-database"
TABLE_NAME = "backup-table"

backups_by_cloud = {}
value_before_backup, value_after_backup = None, None


@pytest.fixture(scope="session")
def cloud_credentials(
    github_secrets, microceph: pytest_microceph.ConnectionInformation
) -> dict[str, dict[str, str]]:
    """Read cloud credentials."""
    return {
        "aws": {
            "access-key": github_secrets["AWS_ACCESS_KEY"],
            "secret-key": github_secrets["AWS_SECRET_KEY"],
        },
        "gcp": {
            "access-key": github_secrets["GCP_ACCESS_KEY"],
            "secret-key": github_secrets["GCP_SECRET_KEY"],
        },
        "ceph": {
            "access-key": microceph.access_key_id,
            "secret-key": microceph.secret_access_key,
        },
    }


@pytest.fixture(scope="session")
def cloud_configs(microceph: pytest_microceph.ConnectionInformation):
    # Add UUID to path to avoid conflict with tests running in parallel (e.g. multiple Juju
    # versions on a PR, multiple PRs)
    path = f"mysql-k8s/{uuid.uuid4()}"

    return {
        "aws": {
            "endpoint": "https://s3.amazonaws.com",
            "bucket": "data-charms-testing",
            "path": path,
            "region": "us-east-1",
        },
        "gcp": {
            "endpoint": "https://storage.googleapis.com",
            "bucket": "data-charms-testing",
            "path": path,
            "region": "",
        },
        "ceph": {
            "endpoint": f"http://{host_ip}",
            "bucket": microceph.bucket,
            "path": "mysql-k8s",
            "region": "",
        },
    }


@pytest.fixture(scope="session", autouse=True)
def clean_backups_from_buckets(cloud_credentials, cloud_configs):
    """Teardown to clean up created backups from clouds."""
    yield

    logger.info("Cleaning backups from cloud buckets")
    for cloud_name, config in cloud_configs.items():
        backup = backups_by_cloud.get(cloud_name)

        if not backup:
            continue

        session = boto3.session.Session(
            aws_access_key_id=cloud_credentials[cloud_name]["access-key"],
            aws_secret_access_key=cloud_credentials[cloud_name]["secret-key"],
            region_name=config["region"],
        )
        s3 = session.resource("s3", endpoint_url=config["endpoint"])
        bucket = s3.Bucket(config["bucket"])

        # GCS doesn't support batch delete operation, so delete the objects one by one
        backup_path = str(Path(config["path"]) / backups_by_cloud[cloud_name])
        for bucket_object in bucket.objects.filter(Prefix=backup_path):
            bucket_object.delete()


@pytest.mark.group(1)
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql charm gets deployed."""
    # TODO: deploy 3 units when bug https://bugs.launchpad.net/juju/+bug/1995466 is resolved
    mysql_application_name = await deploy_and_scale_mysql(ops_test, num_units=1)

    mysql_unit = ops_test.model.units[f"{mysql_application_name}/0"]

    logger.info("Rotating all mysql credentials")
    await rotate_credentials(mysql_unit, username="clusteradmin", password=CLUSTER_ADMIN_PASSWORD)
    await rotate_credentials(mysql_unit, username="serverconfig", password=SERVER_CONFIG_PASSWORD)
    await rotate_credentials(mysql_unit, username="root", password=ROOT_PASSWORD)

    # deploy and relate to s3-integrator
    logger.info("Deploying s3 integrator and tls operator")

    await ops_test.model.deploy(S3_INTEGRATOR, channel="stable")
    await ops_test.model.relate(mysql_application_name, S3_INTEGRATOR)

    await ops_test.model.wait_for_idle(
        apps=[S3_INTEGRATOR],
        status="blocked",
        raise_on_blocked=False,
        timeout=TIMEOUT,
    )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_backup(ops_test: OpsTest, cloud_credentials, cloud_configs) -> None:
    """Test to create a backup and list backups."""
    # TODO: deploy 3 units when bug https://bugs.launchpad.net/juju/+bug/1995466 is resolved
    mysql_application_name = await deploy_and_scale_mysql(ops_test, num_units=1)

    global backups_by_cloud, value_before_backup, value_after_backup

    zeroth_unit = ops_test.model.units[f"{mysql_application_name}/0"]

    # insert data into cluster before
    logger.info("Inserting value before backup")
    value_before_backup = await insert_data_into_mysql_and_validate_replication(
        ops_test,
        DATABASE_NAME,
        TABLE_NAME,
    )

    for cloud_name, config in cloud_configs.items():
        # set the s3 config and credentials

        logger.info(f"Setting s3 config for {cloud_name}")
        await ops_test.model.applications[S3_INTEGRATOR].set_config(config)
        logger.info(f"Syncing credentials for {cloud_name}")
        await juju_.run_action(
            ops_test.model.units[f"{S3_INTEGRATOR}/0"],
            "sync-s3-credentials",
            **cloud_credentials[cloud_name],
        )

        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name, S3_INTEGRATOR],
            status="active",
            timeout=TIMEOUT,
        )

        # list backups
        logger.info("Listing existing backup ids")

        results = await juju_.run_action(zeroth_unit, "list-backups")
        output = results["backups"]
        backup_ids = [line.split("|")[0].strip() for line in output.split("\n")[2:]]

        # create backup
        logger.info("Creating backup")

        results = await juju_.run_action(zeroth_unit, "create-backup")
        backup_id = results["backup-id"]

        # list backups again and ensure new backup id exists
        logger.info("Listing backup ids post backup")

        results = await juju_.run_action(zeroth_unit, "list-backups")
        output = results["backups"]
        new_backup_ids = [line.split("|")[0].strip() for line in output.split("\n")[2:]]

        assert sorted(new_backup_ids) == sorted(backup_ids + [backup_id])

        backups_by_cloud[cloud_name] = backup_id

    # insert data into cluster after backup
    logger.info("Inserting value after backup")
    value_after_backup = await insert_data_into_mysql_and_validate_replication(
        ops_test,
        DATABASE_NAME,
        TABLE_NAME,
    )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_restore_on_same_cluster(
    ops_test: OpsTest, cloud_credentials, cloud_configs
) -> None:
    """Test to restore a backup to the same mysql cluster."""
    # TODO: deploy 3 units when bug https://bugs.launchpad.net/juju/+bug/1995466 is resolved
    mysql_application_name = await deploy_and_scale_mysql(ops_test, num_units=1)

    mysql_unit = ops_test.model.units[f"{mysql_application_name}/0"]
    mysql_unit_address = await get_unit_address(ops_test, mysql_unit.name)
    server_config_credentials = await get_server_config_credentials(mysql_unit)

    for cloud_name, config in cloud_configs.items():
        assert backups_by_cloud[cloud_name]

        # set the s3 config and credentials
        logger.info(f"Syncing credentials for {cloud_name}")

        await ops_test.model.applications[S3_INTEGRATOR].set_config(config)
        await juju_.run_action(
            ops_test.model.units[f"{S3_INTEGRATOR}/0"],
            "sync-s3-credentials",
            **cloud_credentials[cloud_name],
        )

        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name, S3_INTEGRATOR],
            status="active",
            timeout=TIMEOUT,
        )

        # restore the backup
        logger.info(f"Restoring backup with id {backups_by_cloud[cloud_name]}")

        await juju_.run_action(
            mysql_unit, "restore", **{"backup-id": backups_by_cloud[cloud_name]}
        )

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

        # insert data into cluster after restore
        logger.info(f"Inserting value after restore from {cloud_name}")
        value_after_restore = await insert_data_into_mysql_and_validate_replication(
            ops_test,
            DATABASE_NAME,
            TABLE_NAME,
        )

        logger.info("Ensuring that pre-backup and post-restore values exist in the database")

        values = await execute_queries_on_unit(
            mysql_unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_values_sql,
        )
        assert sorted(values) == sorted([value_before_backup, value_after_restore])

    logger.info("Scaling mysql application to 3 units")
    await scale_application(ops_test, mysql_application_name, 3)

    logger.info("Ensuring inserted values before backup and after restore exist on all units")
    for unit in ops_test.model.applications[mysql_application_name].units:
        unit_address = await get_unit_address(ops_test, unit.name)

        values = await execute_queries_on_unit(
            unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_values_sql,
        )

        assert sorted(values) == sorted([value_before_backup, value_after_restore])


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_restore_on_new_cluster(ops_test: OpsTest, cloud_credentials, cloud_configs) -> None:
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

    for cloud_name, config in cloud_configs.items():
        assert backups_by_cloud[cloud_name]

        # set the s3 config and credentials
        logger.info(f"Syncing credentials for {cloud_name}")

        await ops_test.model.applications[S3_INTEGRATOR].set_config(config)
        await juju_.run_action(
            ops_test.model.units[f"{S3_INTEGRATOR}/0"],
            "sync-s3-credentials",
            **cloud_credentials[cloud_name],
        )

        await ops_test.model.wait_for_idle(
            apps=[new_mysql_application_name, S3_INTEGRATOR],
            status="active",
            timeout=TIMEOUT,
        )

        # restore the backup
        logger.info(f"Restoring backup with id {backups_by_cloud[cloud_name]}")

        await juju_.run_action(
            primary_mysql, "restore", **{"backup-id": backups_by_cloud[cloud_name]}
        )

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

        # insert data into cluster after restore
        logger.info(f"Inserting value after restore from {cloud_name}")
        value_after_restore = await insert_data_into_mysql_and_validate_replication(
            ops_test,
            DATABASE_NAME,
            TABLE_NAME,
            mysql_application_substring="another-mysql",
        )

        logger.info("Ensuring that pre-backup and post-restore values exist in the database")

        values = await execute_queries_on_unit(
            primary_unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_values_sql,
        )
        assert sorted(values) == sorted([value_before_backup, value_after_restore])

    logger.info("Scaling mysql application to 3 units")
    await scale_application(ops_test, new_mysql_application_name, 3)

    logger.info("Ensuring inserted values before backup and after restore exist on all units")
    for unit in ops_test.model.applications[new_mysql_application_name].units:
        unit_address = await get_unit_address(ops_test, unit.name)

        values = await execute_queries_on_unit(
            unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_values_sql,
        )

        assert sorted(values) == sorted([value_before_backup, value_after_restore])
