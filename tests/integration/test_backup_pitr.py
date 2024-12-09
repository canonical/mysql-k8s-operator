#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import uuid

import boto3
import pytest
from pytest_operator.plugin import OpsTest

from . import juju_
from .helpers import (
    execute_queries_on_unit,
    get_primary_unit,
    get_unit_address,
    rotate_credentials,
)
from .high_availability.high_availability_helpers import (
    deploy_and_scale_mysql,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

S3_INTEGRATOR = "s3-integrator"
S3_INTEGRATOR_CHANNEL = "latest/stable"
TIMEOUT = 10 * 60
SERVER_CONFIG_USER = "serverconfig"
SERVER_CONFIG_PASSWORD = "serverconfigpassword"
DATABASE_NAME = "backup-database"
TABLE_NAME = "backup-table"
APPLICATION_NAME_AWS = "mysql-k8s-aws"
APPLICATION_NAME_GCP = "mysql-k8s-gcp"
MOVE_RESTORED_CLUSTER_TO_ANOTHER_S3_REPOSITORY_ERROR = (
    "Move restored cluster to another S3 repository"
)


@pytest.fixture(scope="session")
def cloud_configs_aws(github_secrets) -> tuple[dict[str, str], dict[str, str]]:
    configs = {
        "endpoint": "https://s3.amazonaws.com",
        "bucket": "data-charms-testing",
        "path": f"mysql-k8s/{uuid.uuid4()}",
        "region": "us-east-1",
    }
    credentials = {
        "access-key": github_secrets["AWS_ACCESS_KEY"],
        "secret-key": github_secrets["AWS_SECRET_KEY"],
    }
    yield configs, credentials
    clean_backups_from_buckets(configs, credentials)


@pytest.fixture(scope="session")
def cloud_configs_gcp(github_secrets) -> tuple[dict[str, str], dict[str, str]]:
    configs = {
        "endpoint": "https://storage.googleapis.com",
        "bucket": "data-charms-testing",
        "path": f"mysql/{uuid.uuid4()}",
        "region": "",
    }
    credentials = {
        "access-key": github_secrets["GCP_ACCESS_KEY"],
        "secret-key": github_secrets["GCP_SECRET_KEY"],
    }
    yield configs, credentials
    clean_backups_from_buckets(configs, credentials)


def clean_backups_from_buckets(cloud_configs, cloud_credentials) -> None:
    """Teardown to clean up created backups from clouds."""
    logger.info("Cleaning backups from cloud buckets")
    session = boto3.session.Session(  # pyright: ignore
        aws_access_key_id=cloud_credentials["access-key"],
        aws_secret_access_key=cloud_credentials["secret-key"],
        region_name=cloud_configs["region"],
    )
    s3 = session.resource("s3", endpoint_url=cloud_configs["endpoint"])
    bucket = s3.Bucket(cloud_configs["bucket"])

    # GCS doesn't support batch delete operation, so delete the objects one by one
    backup_path = cloud_configs["path"]
    for bucket_object in bucket.objects.filter(Prefix=backup_path):
        bucket_object.delete()


@pytest.mark.group("AWS")
@pytest.mark.abort_on_fail
async def test_build_and_deploy_aws(
    ops_test: OpsTest, cloud_configs_aws: tuple[dict[str, str], dict[str, str]]
) -> None:
    await build_and_deploy_operations(
        ops_test, APPLICATION_NAME_AWS, cloud_configs_aws[0], cloud_configs_aws[1]
    )


@pytest.mark.group("GCP")
@pytest.mark.abort_on_fail
async def test_build_and_deploy_gcp(
    ops_test: OpsTest, cloud_configs_gcp: tuple[dict[str, str], dict[str, str]]
) -> None:
    await build_and_deploy_operations(
        ops_test, APPLICATION_NAME_GCP, cloud_configs_gcp[0], cloud_configs_gcp[1]
    )


async def build_and_deploy_operations(
    ops_test: OpsTest,
    mysql_application_name: str,
    cloud_configs: dict[str, str],
    cloud_credentials: dict[str, str],
) -> None:
    """Simple test to ensure that the mysql charm gets deployed."""
    logger.info("Deploying s3 integrator")
    await ops_test.model.deploy(S3_INTEGRATOR, channel=S3_INTEGRATOR_CHANNEL, base="ubuntu@22.04")

    logger.info("Deploying mysql")
    await deploy_and_scale_mysql(ops_test, mysql_application_name=mysql_application_name)

    logger.info("Rotating mysql credentials")
    first_mysql_unit = ops_test.model.units[f"{mysql_application_name}/0"]
    assert first_mysql_unit
    primary_mysql = await get_primary_unit(ops_test, first_mysql_unit, mysql_application_name)
    await rotate_credentials(
        primary_mysql, username=SERVER_CONFIG_USER, password=SERVER_CONFIG_PASSWORD
    )

    logger.info("Configuring s3 integrator and integrating it with mysql")
    await ops_test.model.wait_for_idle(
        apps=[S3_INTEGRATOR],
        status="blocked",
        raise_on_blocked=False,
        timeout=TIMEOUT,
    )
    await ops_test.model.applications[S3_INTEGRATOR].set_config(cloud_configs)
    await juju_.run_action(
        ops_test.model.units[f"{S3_INTEGRATOR}/0"],  # pyright: ignore
        "sync-s3-credentials",
        **cloud_credentials,
    )
    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, S3_INTEGRATOR],
        status="active",
        timeout=TIMEOUT,
    )
    await ops_test.model.relate(mysql_application_name, S3_INTEGRATOR)
    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, S3_INTEGRATOR],
        status="active",
        timeout=TIMEOUT,
    )


@pytest.mark.group("AWS")
@pytest.mark.abort_on_fail
async def test_pitr_aws(ops_test: OpsTest, credentials: dict[str, str]) -> None:
    await pitr_operations(ops_test, APPLICATION_NAME_AWS, credentials)


@pytest.mark.group("GCP")
@pytest.mark.abort_on_fail
async def test_pitr_gcp(ops_test: OpsTest, credentials: dict[str, str]) -> None:
    await pitr_operations(ops_test, APPLICATION_NAME_GCP, credentials)


async def pitr_operations(
    ops_test: OpsTest, mysql_application_name: str, credentials: dict[str, str]
) -> None:
    first_mysql_unit = ops_test.model.units[f"{mysql_application_name}/0"]
    assert first_mysql_unit
    first_mysql_ip = await get_unit_address(ops_test, first_mysql_unit.name)
    primary_unit = await get_primary_unit(ops_test, first_mysql_unit, mysql_application_name)
    non_primary_units = [
        unit
        for unit in ops_test.model.applications[mysql_application_name].units
        if unit.name != primary_unit.name
    ]
    primary_ip = await get_unit_address(ops_test, primary_unit.name)

    logger.info("Creating backup")
    results = await juju_.run_action(non_primary_units[0], "create-backup", **{"--wait": "5m"})
    backup_id = results["backup-id"]

    logger.info("Creating test data 1")
    td1 = await insert_data_into_mysql_and_validate_replication(
        ops_test, DATABASE_NAME, TABLE_NAME, credentials
    )
    ts = execute_queries_on_unit(
        primary_ip,
        SERVER_CONFIG_USER,
        SERVER_CONFIG_PASSWORD,
        ["SELECT CURRENT_TIMESTAMP"],
        raw=True,
    )
    # This is a raw bytes, so we need to decode it to the utf-8 string
    ts = ts[0].decode("utf-8")
    ts_year_before = ts.replace(ts[:4], str(int(ts[:4]) - 1), 1)
    ts_year_after = ts.replace(ts[:4], str(int(ts[:4]) + 1), 1)

    logger.info("Creating test data 2")
    td2 = await insert_data_into_mysql_and_validate_replication(
        ops_test, DATABASE_NAME, TABLE_NAME, credentials
    )

    execute_queries_on_unit(
        primary_ip,
        SERVER_CONFIG_USER,
        SERVER_CONFIG_PASSWORD,
        ["FLUSH BINARY LOGS"],
    )

    logger.info("Scaling down to 1 unit")
    await ops_test.model.applications[mysql_application_name].scale(1)
    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name],
        status="active",
        timeout=TIMEOUT,
        wait_for_exact_units=1,
    )

    del primary_ip
    del primary_unit

    logger.info(f"Restoring backup {backup_id} with bad restore-to-time parameter")
    action = await first_mysql_unit.run_action(
        "restore", **{"backup-id": backup_id, "restore-to-time": "bad"}
    )
    await action.wait()
    assert (
        action.status == "failed"
    ), "restore should fail with bad restore-to-time parameter, but it succeeded"

    logger.info(f"Restoring backup {backup_id} with year_before restore-to-time parameter")
    await juju_.run_action(
        first_mysql_unit, "restore", **{"backup-id": backup_id, "restore-to-time": ts_year_before}
    )
    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, S3_INTEGRATOR],
        timeout=TIMEOUT,
    )
    assert await check_test_data_existence(
        first_mysql_ip, should_not_exist=[td1, td2]
    ), "test data should not exist"

    logger.info(f"Restoring backup {backup_id} with year_after restore-to-time parameter")
    await juju_.run_action(
        first_mysql_unit, "restore", **{"backup-id": backup_id, "restore-to-time": ts_year_after}
    )
    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, S3_INTEGRATOR],
        timeout=TIMEOUT,
    )
    assert await check_test_data_existence(
        first_mysql_ip, should_exist=[td1, td2]
    ), "both test data should exist"

    logger.info(f"Restoring backup {backup_id} with actual restore-to-time parameter")
    await juju_.run_action(
        first_mysql_unit, "restore", **{"backup-id": backup_id, "restore-to-time": ts}
    )
    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, S3_INTEGRATOR],
        timeout=TIMEOUT,
    )
    assert await check_test_data_existence(
        first_mysql_ip, should_exist=[td1], should_not_exist=[td2]
    ), "only first test data should exist"

    logger.info(f"Restoring backup {backup_id} with restore-to-time=latest parameter")
    await juju_.run_action(
        first_mysql_unit, "restore", **{"backup-id": backup_id, "restore-to-time": "latest"}
    )
    await ops_test.model.wait_for_idle(
        apps=[mysql_application_name, S3_INTEGRATOR],
        timeout=TIMEOUT,
    )
    assert await check_test_data_existence(
        first_mysql_ip, should_exist=[td1, td2]
    ), "both test data should exist"


async def check_test_data_existence(
    unit_address: str,
    should_exist: list[str] | None = None,
    should_not_exist: list[str] | None = None,
) -> bool:
    if should_exist is None:
        should_exist = []
    if should_not_exist is None:
        should_not_exist = []
    res = execute_queries_on_unit(
        unit_address,
        SERVER_CONFIG_USER,
        SERVER_CONFIG_PASSWORD,
        [
            f"CREATE DATABASE IF NOT EXISTS `{DATABASE_NAME}`",
            f"CREATE TABLE IF NOT EXISTS `{DATABASE_NAME}`.`{TABLE_NAME}` (id varchar(255), primary key (id))",
            f"SELECT id FROM `{DATABASE_NAME}`.`{TABLE_NAME}`",
        ],
        commit=True,
    )
    return all(res_elem in should_exist and res_elem not in should_not_exist for res_elem in res)
