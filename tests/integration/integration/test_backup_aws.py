#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import socket
from pathlib import Path

import boto3
import jubilant_backports
import pytest
from jubilant_backports import Juju

from constants import CLUSTER_ADMIN_USERNAME, ROOT_USERNAME, SERVER_CONFIG_USERNAME

from ..helpers import generate_random_string
from ..helpers_ha import (
    CHARM_METADATA,
    MINUTE_SECS,
    execute_queries_on_unit,
    get_app_units,
    get_mysql_primary_unit,
    get_mysql_server_credentials,
    get_unit_address,
    insert_mysql_test_data,
    rotate_mysql_server_credentials,
    scale_app_units,
    verify_mysql_test_data,
    wait_for_apps_status,
    wait_for_unit_status,
)
from ..helpers_ha import (
    TEST_DATABASE_NAME as DATABASE_NAME,
)

logger = logging.getLogger(__name__)

host_ip = socket.gethostbyname(socket.gethostname())

DATABASE_APP_NAME = "mysql-k8s"
S3_INTEGRATOR = "s3-integrator"
TIMEOUT = 10 * MINUTE_SECS
CLUSTER_NAME = "test_cluster"
CLUSTER_ADMIN_PASSWORD = "clusteradminpassword"
SERVER_CONFIG_PASSWORD = "serverconfigpassword"
ROOT_PASSWORD = "rootpassword"
TABLE_NAME = "backup-table"
CLOUD = "aws"
ANOTHER_S3_CLUSTER_REPOSITORY_ERROR_MESSAGE = "S3 repository claimed by another cluster"
MOVE_RESTORED_CLUSTER_TO_ANOTHER_S3_REPOSITORY_ERROR = (
    "Move restored cluster to another S3 repository"
)

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)

backup_id, value_before_backup, value_after_backup = None, None, None


@pytest.fixture(scope="session", autouse=True)
def clean_backups_from_buckets(cloud_configs_aws):
    """Teardown to clean up created backups from clouds."""
    yield

    cloud_configs, cloud_credentials = cloud_configs_aws

    logger.info("Cleaning backups from buckets")
    session = boto3.session.Session(  # pyright: ignore
        aws_access_key_id=cloud_credentials["access-key"],
        aws_secret_access_key=cloud_credentials["secret-key"],
        region_name=cloud_configs["region"],
    )
    s3 = session.resource("s3", endpoint_url=cloud_configs["endpoint"])
    bucket = s3.Bucket(cloud_configs["bucket"])

    # GCS doesn't support batch delete operation, so delete the objects one by one
    backup_path = str(Path(cloud_configs["path"]) / CLOUD)
    for bucket_object in bucket.objects.filter(Prefix=backup_path):
        bucket_object.delete()


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Simple test to ensure that the mysql charm gets deployed."""
    juju.deploy(
        charm,
        DATABASE_APP_NAME,
        base="ubuntu@22.04",
        config={"cluster-name": CLUSTER_NAME, "profile": "testing"},
        num_units=3,
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        trust=True,
    )

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=15 * MINUTE_SECS,
    )

    primary_unit_name = get_mysql_primary_unit(juju, DATABASE_APP_NAME)

    logger.info("Rotating all mysql credentials")
    rotate_mysql_server_credentials(
        juju, primary_unit_name, CLUSTER_ADMIN_USERNAME, CLUSTER_ADMIN_PASSWORD
    )
    rotate_mysql_server_credentials(
        juju, primary_unit_name, SERVER_CONFIG_USERNAME, SERVER_CONFIG_PASSWORD
    )
    rotate_mysql_server_credentials(juju, primary_unit_name, ROOT_USERNAME, ROOT_PASSWORD)

    logger.info("Deploying s3-integrator")

    juju.deploy(S3_INTEGRATOR, channel="1/stable", base="ubuntu@22.04")
    juju.integrate(DATABASE_APP_NAME, S3_INTEGRATOR)

    juju.wait(
        ready=lambda status: all((
            *(
                wait_for_unit_status(S3_INTEGRATOR, unit_name, "blocked")(status)
                for unit_name in status.get_units(S3_INTEGRATOR)
            ),
        )),
        timeout=TIMEOUT,
    )


@pytest.mark.abort_on_fail
def test_backup(juju: Juju, cloud_configs_aws) -> None:
    """Test to create a backup and list backups."""
    global backup_id, value_before_backup, value_after_backup

    cloud_configs, cloud_credentials = cloud_configs_aws

    app_units = get_app_units(juju, DATABASE_APP_NAME)
    zeroth_unit_name = app_units[0]

    primary_unit_name = get_mysql_primary_unit(juju, DATABASE_APP_NAME)
    non_primary_unit_names = [unit for unit in app_units if unit != primary_unit_name]

    # insert data into cluster before backup
    logger.info("Inserting value before backup")
    value_before_backup = generate_random_string(255)
    insert_mysql_test_data(
        juju,
        DATABASE_APP_NAME,
        TABLE_NAME,
        value_before_backup,
    )
    verify_mysql_test_data(
        juju,
        DATABASE_APP_NAME,
        TABLE_NAME,
        value_before_backup,
    )

    logger.info("Setting s3 config")
    juju.config(S3_INTEGRATOR, cloud_configs)
    logger.info("Syncing credentials")
    s3_unit_name = get_app_units(juju, S3_INTEGRATOR)[0]
    juju.run(
        unit=s3_unit_name,
        action="sync-s3-credentials",
        params=cloud_credentials,
    )

    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, DATABASE_APP_NAME, S3_INTEGRATOR
        ),
        timeout=TIMEOUT,
    )

    # list backups
    logger.info("Listing existing backup ids")

    results = juju.run(zeroth_unit_name, "list-backups").results
    output = results["backups"]
    backup_ids = [line.split("|")[0].strip() for line in output.split("\n")[2:]]

    # create backup
    logger.info("Creating backup")

    results = juju.run(non_primary_unit_names[0], "create-backup", wait=5 * MINUTE_SECS).results
    backup_id = results["backup-id"]

    # list backups again and ensure new backup id exists
    logger.info("Listing backup ids post backup")

    results = juju.run(zeroth_unit_name, "list-backups").results
    output = results["backups"]
    new_backup_ids = [line.split("|")[0].strip() for line in output.split("\n")[2:]]

    assert sorted(new_backup_ids) == sorted([*backup_ids, backup_id])

    # insert data into cluster after backup
    logger.info("Inserting value after backup")
    value_after_backup = generate_random_string(255)
    insert_mysql_test_data(
        juju,
        DATABASE_APP_NAME,
        TABLE_NAME,
        value_after_backup,
    )
    verify_mysql_test_data(
        juju,
        DATABASE_APP_NAME,
        TABLE_NAME,
        value_after_backup,
    )


@pytest.mark.abort_on_fail
def test_restore_on_same_cluster(juju: Juju, cloud_configs_aws) -> None:
    """Test to restore a backup to the same mysql cluster."""
    cloud_configs, cloud_credentials = cloud_configs_aws

    logger.info("Scaling mysql application to 1 unit")
    scale_app_units(juju, DATABASE_APP_NAME, 1)

    mysql_unit_name = get_app_units(juju, DATABASE_APP_NAME)[0]
    mysql_unit_address = get_unit_address(juju, DATABASE_APP_NAME, mysql_unit_name)

    # set the s3 config and credentials
    logger.info("Syncing credentials")

    juju.config(S3_INTEGRATOR, cloud_configs)
    s3_unit_name = get_app_units(juju, S3_INTEGRATOR)[0]
    juju.run(
        unit=s3_unit_name,
        action="sync-s3-credentials",
        params=cloud_credentials,
    )

    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, DATABASE_APP_NAME, S3_INTEGRATOR
        ),
        timeout=TIMEOUT,
    )

    # restore the backup
    logger.info(f"Restoring {backup_id=}")

    juju.run(mysql_unit_name, "restore", params={"backup-id": backup_id})

    # ensure the correct inserted values exist
    logger.info(
        "Ensuring that the pre-backup inserted value exists in database, "
        "while post-backup inserted value does not"
    )
    select_values_sql = [f"SELECT id FROM `{DATABASE_NAME}`.`{TABLE_NAME}`"]

    primary_unit_name = get_app_units(juju, DATABASE_APP_NAME)[0]
    credentials = get_mysql_server_credentials(juju, primary_unit_name)

    values = execute_queries_on_unit(
        mysql_unit_address,
        credentials["username"],
        credentials["password"],
        select_values_sql,
    )
    assert values == [value_before_backup]

    # insert data into cluster after restore
    logger.info("Inserting value after restore")
    value_after_restore = generate_random_string(255)
    insert_mysql_test_data(
        juju,
        DATABASE_APP_NAME,
        TABLE_NAME,
        value_after_restore,
    )
    verify_mysql_test_data(
        juju,
        DATABASE_APP_NAME,
        TABLE_NAME,
        value_after_restore,
    )

    logger.info("Ensuring that pre-backup and post-restore values exist in the database")

    values = execute_queries_on_unit(
        mysql_unit_address,
        credentials["username"],
        credentials["password"],
        select_values_sql,
    )
    assert value_before_backup
    assert sorted(values) == sorted([value_before_backup, value_after_restore])

    logger.info("Scaling mysql application to 3 units")
    juju.add_unit(DATABASE_APP_NAME, num_units=2)

    juju.wait(
        ready=lambda status: all((
            jubilant_backports.all_agents_idle(status, DATABASE_APP_NAME),
            *(
                wait_for_unit_status(DATABASE_APP_NAME, unit_name, "active")(status)
                for unit_name in status.get_units(DATABASE_APP_NAME)
            ),
        )),
        timeout=TIMEOUT,
    )

    logger.info("Ensuring inserted values before backup and after restore exist on all units")
    for unit_name in get_app_units(juju, DATABASE_APP_NAME):
        unit_address = get_unit_address(juju, DATABASE_APP_NAME, unit_name)

        values = execute_queries_on_unit(
            unit_address,
            credentials["username"],
            credentials["password"],
            select_values_sql,
        )

        assert sorted(values) == sorted([value_before_backup, value_after_restore])

    assert (
        juju.status().apps[DATABASE_APP_NAME].app_status.message
        == MOVE_RESTORED_CLUSTER_TO_ANOTHER_S3_REPOSITORY_ERROR
    ), "cluster should migrate to blocked status after restore"


@pytest.mark.abort_on_fail
def test_restore_on_new_cluster(juju: Juju, charm, cloud_configs_aws) -> None:
    """Test to restore a backup on a new mysql cluster."""
    cloud_configs, cloud_credentials = cloud_configs_aws

    logger.info("Deploying a new mysql cluster")

    new_mysql_application_name = "another-mysql-k8s"
    juju.deploy(
        charm,
        new_mysql_application_name,
        base="ubuntu@22.04",
        config={"cluster-name": CLUSTER_NAME, "profile": "testing"},
        num_units=1,
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        trust=True,
    )

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, new_mysql_application_name),
        timeout=TIMEOUT,
    )

    # relate to S3 integrator
    juju.integrate(new_mysql_application_name, S3_INTEGRATOR)

    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, new_mysql_application_name, S3_INTEGRATOR
        ),
        timeout=TIMEOUT,
    )

    # rotate all credentials
    logger.info("Rotating all mysql credentials")

    primary_unit_name = get_mysql_primary_unit(juju, new_mysql_application_name)
    primary_unit_address = get_unit_address(juju, new_mysql_application_name, primary_unit_name)

    rotate_mysql_server_credentials(
        juju, primary_unit_name, CLUSTER_ADMIN_USERNAME, CLUSTER_ADMIN_PASSWORD
    )
    rotate_mysql_server_credentials(
        juju, primary_unit_name, SERVER_CONFIG_USERNAME, SERVER_CONFIG_PASSWORD
    )
    rotate_mysql_server_credentials(juju, primary_unit_name, ROOT_USERNAME, ROOT_PASSWORD)

    server_config_credentials = get_mysql_server_credentials(juju, primary_unit_name)

    # set the s3 config and credentials
    logger.info("Syncing credentials")

    juju.config(S3_INTEGRATOR, cloud_configs)
    s3_unit_name = get_app_units(juju, S3_INTEGRATOR)[0]
    juju.run(
        unit=s3_unit_name,
        action="sync-s3-credentials",
        params=cloud_credentials,
    )

    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, new_mysql_application_name, S3_INTEGRATOR
        ),
        timeout=TIMEOUT,
    )

    logger.info("Waiting for blocked application status with another cluster S3 repository")
    juju.wait(  # Might take a few minutes to get past this
        ready=lambda status: status.apps[new_mysql_application_name].app_status.message
        == ANOTHER_S3_CLUSTER_REPOSITORY_ERROR_MESSAGE,
        timeout=TIMEOUT,
    )

    # restore the backup
    logger.info(f"Restoring {backup_id=}")

    juju.run(primary_unit_name, "restore", params={"backup-id": backup_id})

    # ensure the correct inserted values exist
    logger.info(
        "Ensuring that the pre-backup inserted value exists in database, while post-backup inserted value does not"
    )
    select_values_sql = [f"SELECT id FROM `{DATABASE_NAME}`.`{TABLE_NAME}`"]

    values = execute_queries_on_unit(
        primary_unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        select_values_sql,
    )
    assert values == [value_before_backup]

    # insert data into cluster after restore
    logger.info("Inserting value after restore")
    value_after_restore = generate_random_string(255)
    insert_mysql_test_data(
        juju,
        new_mysql_application_name,
        TABLE_NAME,
        value_after_restore,
    )
    verify_mysql_test_data(
        juju,
        new_mysql_application_name,
        TABLE_NAME,
        value_after_restore,
    )

    logger.info("Ensuring that pre-backup and post-restore values exist in the database")

    values = execute_queries_on_unit(
        primary_unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        select_values_sql,
    )
    assert value_before_backup
    assert sorted(values) == sorted([value_before_backup, value_after_restore])

    logger.info("Scaling mysql application to 3 units")
    juju.add_unit(new_mysql_application_name, num_units=2)
    juju.wait(
        ready=lambda status: all((
            jubilant_backports.all_agents_idle(status, new_mysql_application_name),
            *(
                wait_for_unit_status(new_mysql_application_name, unit_name, "active")(status)
                for unit_name in status.get_units(new_mysql_application_name)
            ),
        )),
        timeout=TIMEOUT,
    )

    logger.info("Ensuring inserted values before backup and after restore exist on all units")
    for unit_name in get_app_units(juju, new_mysql_application_name):
        unit_address = get_unit_address(juju, new_mysql_application_name, unit_name)

        values = execute_queries_on_unit(
            unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            select_values_sql,
        )

        assert sorted(values) == sorted([value_before_backup, value_after_restore])

    logger.info("Waiting for blocked application status after restore")
    juju.wait(
        ready=lambda status: status.apps[new_mysql_application_name].app_status.message
        == MOVE_RESTORED_CLUSTER_TO_ANOTHER_S3_REPOSITORY_ERROR,
        timeout=TIMEOUT,
    )
