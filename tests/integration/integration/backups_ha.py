# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import boto3
import jubilant_backports
import pytest
from jubilant_backports import Juju, TaskError

from constants import SERVER_CONFIG_USERNAME

from ..helpers import execute_queries_on_unit, generate_random_string
from ..helpers_ha import (
    CHARM_METADATA,
    MINUTE_SECS,
    get_app_units,
    get_mysql_primary_unit,
    get_unit_address,
    insert_mysql_data_and_validate_replication,
    rotate_mysql_server_credentials,
    scale_app_units,
    wait_for_apps_status,
    wait_for_unit_status,
)

logger = logging.getLogger(__name__)

S3_INTEGRATOR = "s3-integrator"
S3_INTEGRATOR_CHANNEL = "1/stable"
MYSQL_APPLICATION_NAME = "mysql-k8s"
TIMEOUT = 10 * MINUTE_SECS
CLUSTER_NAME = "test_cluster"
SERVER_CONFIG_USER = "serverconfig"
SERVER_CONFIG_PASSWORD = "serverconfigpassword"
DATABASE_NAME = "backup-database"
TABLE_NAME = "backup-table"
MOVE_RESTORED_CLUSTER_TO_ANOTHER_S3_REPOSITORY_ERROR = (
    "Move restored cluster to another S3 repository"
)


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


def build_and_deploy_operations(
    juju: Juju,
    charm: str,
    cloud_configs: dict[str, str],
    cloud_credentials: dict[str, str],
) -> None:
    """Simple test to ensure that the mysql charm gets deployed."""
    logger.info("Deploying s3 integrator")
    juju.deploy(
        S3_INTEGRATOR,
        S3_INTEGRATOR,
        channel=S3_INTEGRATOR_CHANNEL,
        base="ubuntu@22.04",
    )

    logger.info("Deploying mysql")
    juju.deploy(
        charm,
        MYSQL_APPLICATION_NAME,
        base="ubuntu@22.04",
        config={"cluster-name": CLUSTER_NAME, "profile": "testing"},
        num_units=3,
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        trust=True,
    )

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APPLICATION_NAME),
        timeout=15 * MINUTE_SECS,
    )

    logger.info("Rotating mysql credentials")
    primary_unit_name = get_mysql_primary_unit(juju, MYSQL_APPLICATION_NAME)
    rotate_mysql_server_credentials(
        juju, primary_unit_name, SERVER_CONFIG_USERNAME, SERVER_CONFIG_PASSWORD
    )

    logger.info("Configuring s3 integrator and integrating it with mysql")
    juju.wait(
        ready=lambda status: all((
            *(
                wait_for_unit_status(S3_INTEGRATOR, unit_name, "blocked")(status)
                for unit_name in status.get_units(S3_INTEGRATOR)
            ),
        )),
        timeout=TIMEOUT,
    )
    juju.config(S3_INTEGRATOR, cloud_configs)
    s3_unit_name = get_app_units(juju, S3_INTEGRATOR)[0]
    juju.run(
        unit=s3_unit_name,
        action="sync-s3-credentials",
        params=cloud_credentials,
    )
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, MYSQL_APPLICATION_NAME, S3_INTEGRATOR
        ),
        timeout=TIMEOUT,
    )
    juju.integrate(MYSQL_APPLICATION_NAME, S3_INTEGRATOR)
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, MYSQL_APPLICATION_NAME, S3_INTEGRATOR
        ),
        timeout=TIMEOUT,
    )


def pitr_operations(
    juju: Juju,
    cloud_configs: dict[str, str],
    cloud_credentials: dict[str, str],
) -> None:
    app_units = get_app_units(juju, MYSQL_APPLICATION_NAME)
    first_mysql_unit_name = app_units[0]
    first_mysql_ip = get_unit_address(juju, MYSQL_APPLICATION_NAME, first_mysql_unit_name)

    primary_unit_name = get_mysql_primary_unit(juju, MYSQL_APPLICATION_NAME)
    non_primary_unit_names = [unit for unit in app_units if unit != primary_unit_name]
    primary_ip = get_unit_address(juju, MYSQL_APPLICATION_NAME, primary_unit_name)

    credentials = {"username": SERVER_CONFIG_USER, "password": SERVER_CONFIG_PASSWORD}

    logger.info("Creating backup")
    results = juju.run(
        non_primary_unit_names[0],
        "create-backup",
        wait=5 * MINUTE_SECS,
    ).results
    backup_id = results["backup-id"]

    logger.info("Creating test data 1")
    td1 = generate_random_string(255)
    insert_mysql_data_and_validate_replication(
        juju, MYSQL_APPLICATION_NAME, DATABASE_NAME, TABLE_NAME, td1, credentials
    )

    ts = execute_queries_on_unit(
        primary_ip,
        SERVER_CONFIG_USERNAME,
        SERVER_CONFIG_PASSWORD,
        ["SELECT CURRENT_TIMESTAMP"],
        raw=True,
    )
    # This is a raw bytes, so we need to decode it to the utf-8 string
    ts = ts[0].decode("utf-8")
    ts_year_before = ts.replace(ts[:4], str(int(ts[:4]) - 1), 1)
    ts_year_after = ts.replace(ts[:4], str(int(ts[:4]) + 1), 1)

    logger.info("Creating test data 2")
    td2 = generate_random_string(255)
    insert_mysql_data_and_validate_replication(
        juju, MYSQL_APPLICATION_NAME, DATABASE_NAME, TABLE_NAME, td2, credentials
    )

    execute_queries_on_unit(
        primary_ip,
        SERVER_CONFIG_USERNAME,
        SERVER_CONFIG_PASSWORD,
        ["FLUSH BINARY LOGS"],
    )

    logger.info("Scaling down to 1 unit")
    scale_app_units(juju, MYSQL_APPLICATION_NAME, 1)

    del primary_ip
    del primary_unit_name

    logger.info(f"Restoring backup {backup_id} with bad restore-to-time parameter")
    with pytest.raises(TaskError, match="Bad restore-to-time format"):
        juju.run(
            first_mysql_unit_name,
            "restore",
            params={"backup-id": backup_id, "restore-to-time": "bad"},
        )

    logger.info(f"Restoring backup {backup_id} with year_before restore-to-time parameter")
    juju.run(
        first_mysql_unit_name,
        "restore",
        params={"backup-id": backup_id, "restore-to-time": ts_year_before},
    )
    juju.wait(
        ready=lambda status: all((
            jubilant_backports.all_agents_idle(status, MYSQL_APPLICATION_NAME, S3_INTEGRATOR),
        )),
        timeout=TIMEOUT,
    )
    assert check_test_data_existence(first_mysql_ip, should_not_exist=[td1, td2]), (
        "test data should not exist"
    )

    logger.info(f"Restoring backup {backup_id} with year_after restore-to-time parameter")
    juju.run(
        first_mysql_unit_name,
        "restore",
        params={"backup-id": backup_id, "restore-to-time": ts_year_after},
    )
    juju.wait(
        ready=lambda status: all((
            jubilant_backports.all_agents_idle(status, MYSQL_APPLICATION_NAME, S3_INTEGRATOR),
        )),
        timeout=TIMEOUT,
    )
    assert check_test_data_existence(first_mysql_ip, should_exist=[td1, td2]), (
        "both test data should exist"
    )

    logger.info(f"Restoring backup {backup_id} with actual restore-to-time parameter")
    juju.run(
        first_mysql_unit_name,
        "restore",
        params={"backup-id": backup_id, "restore-to-time": ts},
    )
    juju.wait(
        ready=lambda status: all((
            jubilant_backports.all_agents_idle(status, MYSQL_APPLICATION_NAME, S3_INTEGRATOR),
        )),
        timeout=TIMEOUT,
    )
    assert check_test_data_existence(first_mysql_ip, should_exist=[td1], should_not_exist=[td2]), (
        "only first test data should exist"
    )

    logger.info(f"Restoring backup {backup_id} with restore-to-time=latest parameter")
    juju.run(
        first_mysql_unit_name,
        "restore",
        params={"backup-id": backup_id, "restore-to-time": "latest"},
    )
    juju.wait(
        ready=lambda status: all((
            jubilant_backports.all_agents_idle(status, MYSQL_APPLICATION_NAME, S3_INTEGRATOR),
        )),
        timeout=TIMEOUT,
    )
    assert check_test_data_existence(first_mysql_ip, should_exist=[td1, td2]), (
        "both test data should exist"
    )
    clean_backups_from_buckets(cloud_configs, cloud_credentials)


def check_test_data_existence(
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
        SERVER_CONFIG_USERNAME,
        SERVER_CONFIG_PASSWORD,
        [
            f"CREATE DATABASE IF NOT EXISTS `{DATABASE_NAME}`",
            f"CREATE TABLE IF NOT EXISTS `{DATABASE_NAME}`.`{TABLE_NAME}` (id varchar(255), primary key (id))",
            f"SELECT id FROM `{DATABASE_NAME}`.`{TABLE_NAME}`",
        ],
        commit=True,
    )
    return all(res_elem in should_exist and res_elem not in should_not_exist for res_elem in res)
