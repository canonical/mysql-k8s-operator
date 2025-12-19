#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
import urllib3
from jubilant_backports import Juju
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from constants import CLUSTER_ADMIN_USERNAME, PASSWORD_LENGTH, ROOT_USERNAME
from utils import generate_random_password

from ..helpers import execute_queries_on_unit, generate_random_string
from ..helpers_ha import (
    CHARM_METADATA,
    MINUTE_SECS,
    get_app_units,
    get_mysql_cluster_status,
    get_mysql_primary_unit,
    get_mysql_server_credentials,
    get_mysql_variable_value,
    get_unit_address,
    rotate_mysql_server_credentials,
    scale_app_units,
    wait_for_apps_status,
)

logger = logging.getLogger(__name__)

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)

APP_NAME = CHARM_METADATA["name"]
CLUSTER_NAME = "test_cluster"
TIMEOUT = 15 * MINUTE_SECS


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Build the mysql charm and deploy it."""
    logger.info(f"Deploying {APP_NAME}")
    resources = {"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]}
    config = {"cluster-name": CLUSTER_NAME, "profile": "testing"}
    juju.deploy(
        charm,
        APP_NAME,
        resources=resources,
        base="ubuntu@22.04",
        config=config,
        num_units=3,
        trust=True,
    )

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, APP_NAME),
        timeout=TIMEOUT,
    )

    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[0]
    server_config_credentials = get_mysql_server_credentials(juju, random_unit_name)

    count_group_replication_members_sql = [
        "SELECT count(*) FROM performance_schema.replication_group_members where MEMBER_STATE='ONLINE';",
    ]

    for unit_name in app_units:
        unit_address = get_unit_address(juju, APP_NAME, unit_name)
        output = execute_queries_on_unit(
            unit_address,
            server_config_credentials["username"],
            server_config_credentials["password"],
            count_group_replication_members_sql,
        )
        assert output[0] == 3


@pytest.mark.abort_on_fail
def test_consistent_data_replication_across_cluster(juju: Juju) -> None:
    """Confirm that data is replicated from the primary node to all the replicas."""
    # Insert values into a table on the primary unit
    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[0]
    server_config_credentials = get_mysql_server_credentials(juju, random_unit_name)

    primary_unit_name = get_mysql_primary_unit(juju, APP_NAME)
    primary_unit_address = get_unit_address(juju, APP_NAME, primary_unit_name)

    random_chars = generate_random_string(40)
    create_records_sql = [
        "CREATE DATABASE IF NOT EXISTS test",
        "CREATE TABLE IF NOT EXISTS test.data_replication_table (id varchar(40), primary key(id))",
        f"INSERT INTO test.data_replication_table VALUES ('{random_chars}')",
    ]

    execute_queries_on_unit(
        primary_unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        create_records_sql,
        commit=True,
    )

    select_data_sql = [
        f"SELECT * FROM test.data_replication_table WHERE id = '{random_chars}'",
    ]

    # Retry
    try:
        for attempt in Retrying(stop=stop_after_delay(5 * MINUTE_SECS), wait=wait_fixed(3)):
            with attempt:
                # Confirm that the values are available on all units
                for unit_name in app_units:
                    unit_address = get_unit_address(juju, APP_NAME, unit_name)

                    output = execute_queries_on_unit(
                        unit_address,
                        server_config_credentials["username"],
                        server_config_credentials["password"],
                        select_data_sql,
                    )
                    assert random_chars in output
    except RetryError:
        assert False


@pytest.mark.abort_on_fail
def test_scale_up_and_down(juju: Juju) -> None:
    """Confirm that a new primary is elected when the current primary is torn down."""
    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[0]

    logger.info("Scaling up to 5 units")
    scale_app_units(juju, APP_NAME, 5)

    cluster_status = get_mysql_cluster_status(juju, random_unit_name)
    online_member_addresses = [
        member["address"]
        for _, member in cluster_status["defaultreplicaset"]["topology"].items()
        if member["status"] == "online"
    ]
    assert len(online_member_addresses) == 5

    logger.info("Scale down to one unit")
    scale_app_units(juju, APP_NAME, 1)

    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[0]
    cluster_status = get_mysql_cluster_status(juju, random_unit_name)
    online_member_addresses = [
        member["address"]
        for _, member in cluster_status["defaultreplicaset"]["topology"].items()
        if member["status"] == "online"
    ]
    assert len(online_member_addresses) == 1

    not_online_member_addresses = [
        member["address"]
        for _, member in cluster_status["defaultreplicaset"]["topology"].items()
        if member["status"] != "online"
    ]
    assert len(not_online_member_addresses) == 0


@pytest.mark.abort_on_fail
def test_scale_up_after_scale_down(juju: Juju) -> None:
    """Confirm storage reuse works."""
    logger.info("Scaling up to 3 units")
    scale_app_units(juju, APP_NAME, 3)

    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[0]

    cluster_status = get_mysql_cluster_status(juju, random_unit_name)
    online_member_addresses = [
        member["address"]
        for _, member in cluster_status["defaultreplicaset"]["topology"].items()
        if member["status"] == "online"
    ]
    assert len(online_member_addresses) == 3


@pytest.mark.abort_on_fail
def test_scale_up_from_zero(juju: Juju) -> None:
    """Ensure scaling down to zero and back up works."""
    logger.info("Scaling down to 0 units")
    scale_app_units(juju, APP_NAME, 0)

    juju.wait(
        ready=lambda status: len(status.apps[APP_NAME].units) == 0,
        timeout=TIMEOUT,
    )

    logger.info("Scaling back up to 3 units")
    scale_app_units(juju, APP_NAME, 3)

    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[0]
    cluster_status = get_mysql_cluster_status(juju, random_unit_name)
    online_member_addresses = [
        member["address"]
        for _, member in cluster_status["defaultreplicaset"]["topology"].items()
        if member["status"] == "online"
    ]
    assert len(online_member_addresses) == 3


@pytest.mark.abort_on_fail
def test_password_rotation(juju: Juju):
    """Rotate password and confirm changes."""
    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[-1]

    old_credentials = get_mysql_server_credentials(juju, random_unit_name, CLUSTER_ADMIN_USERNAME)

    # get primary unit first, need that to invoke set-password action
    primary_unit_name = get_mysql_primary_unit(juju, APP_NAME)
    primary_unit_address = get_unit_address(juju, APP_NAME, primary_unit_name)
    logger.debug(
        f"Test succeeded Primary unit detected before password rotation is {primary_unit_address}"
    )

    new_password = generate_random_password(PASSWORD_LENGTH)

    rotate_mysql_server_credentials(juju, primary_unit_name, CLUSTER_ADMIN_USERNAME, new_password)

    updated_credentials = get_mysql_server_credentials(
        juju, random_unit_name, CLUSTER_ADMIN_USERNAME
    )
    assert updated_credentials["password"] != old_credentials["password"]
    assert updated_credentials["password"] == new_password

    # verify that the new password actually works
    # since get_mysql_primary_unit (and this get_mysql_cluster_status) use the cluster admin credentials
    primary_unit_name = get_mysql_primary_unit(juju, APP_NAME)
    primary_unit_address = get_unit_address(juju, APP_NAME, primary_unit_name)
    logger.debug(
        f"Test succeeded Primary unit detected after password rotation is {primary_unit_address}"
    )


@pytest.mark.abort_on_fail
def test_password_rotation_silent(juju: Juju):
    """Rotate password and confirm changes."""
    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[-1]

    old_credentials = get_mysql_server_credentials(juju, random_unit_name, CLUSTER_ADMIN_USERNAME)

    # get primary unit first, need that to invoke set-password action
    primary_unit_name = get_mysql_primary_unit(juju, APP_NAME)
    primary_unit_address = get_unit_address(juju, APP_NAME, primary_unit_name)
    logger.debug(
        f"Test succeeded Primary unit detected before password rotation is {primary_unit_address}"
    )

    rotate_mysql_server_credentials(juju, primary_unit_name, CLUSTER_ADMIN_USERNAME)

    updated_credentials = get_mysql_server_credentials(
        juju, random_unit_name, CLUSTER_ADMIN_USERNAME
    )
    assert updated_credentials["password"] != old_credentials["password"]

    # verify that the new password actually works
    # since get_mysql_primary_unit (and this get_mysql_cluster_status) use the cluster admin credentials
    primary_unit_name = get_mysql_primary_unit(juju, APP_NAME)
    primary_unit_address = get_unit_address(juju, APP_NAME, primary_unit_name)
    logger.debug(
        f"Test succeeded Primary unit detected after password rotation is {primary_unit_address}"
    )


@pytest.mark.abort_on_fail
def test_password_rotation_root_user_implicit(juju: Juju):
    """Rotate password and confirm changes."""
    app_units = get_app_units(juju, APP_NAME)
    random_unit_name = app_units[-1]

    root_credentials = get_mysql_server_credentials(juju, random_unit_name, ROOT_USERNAME)

    old_credentials = get_mysql_server_credentials(juju, random_unit_name, ROOT_USERNAME)
    assert old_credentials["password"] == root_credentials["password"]

    # get primary unit first, need that to invoke set-password action
    primary_unit_name = get_mysql_primary_unit(juju, APP_NAME)
    primary_unit_address = get_unit_address(juju, APP_NAME, primary_unit_name)
    logger.debug(
        f"Test succeeded Primary unit detected before password rotation is {primary_unit_address}"
    )

    rotate_mysql_server_credentials(juju, primary_unit_name, ROOT_USERNAME)

    updated_credentials = get_mysql_server_credentials(juju, random_unit_name, ROOT_USERNAME)
    assert updated_credentials["password"] != old_credentials["password"]

    updated_root_credentials = get_mysql_server_credentials(juju, random_unit_name, ROOT_USERNAME)
    assert updated_credentials["password"] == updated_root_credentials["password"]


@pytest.mark.abort_on_fail
def test_exporter_endpoints(juju: Juju) -> None:
    """Test that endpoints are running."""
    app_units = get_app_units(juju, APP_NAME)
    http = urllib3.PoolManager()

    for unit_name in app_units:
        # Start mysqld exporter pebble service
        juju.ssh(
            command="pebble start mysqld_exporter",
            target=unit_name,
            container="mysql",
        )

        unit_address = get_unit_address(juju, APP_NAME, unit_name)
        mysql_exporter_url = f"http://{unit_address}:9104/metrics"

        resp = http.request("GET", mysql_exporter_url)

        assert resp.status == 200, "Can't get metrics from mysql_exporter"
        assert "mysql_exporter_last_scrape_error 0" in resp.data.decode("utf8"), (
            "Scrape error in mysql_exporter"
        )


@pytest.mark.abort_on_fail
def test_custom_variables(juju: Juju) -> None:
    """Query database for custom variables."""
    app_units = get_app_units(juju, APP_NAME)

    custom_vars = {}
    custom_vars["max_connections"] = 100
    custom_vars["innodb_buffer_pool_size"] = 20971520
    custom_vars["innodb_buffer_pool_chunk_size"] = 1048576
    custom_vars["group_replication_message_cache_size"] = 134217728

    for unit_name in app_units:
        for k, v in custom_vars.items():
            logger.info(f"Checking that {k} is set to {v} on {unit_name}")
            value = get_mysql_variable_value(juju, APP_NAME, unit_name, k)
            assert int(value) == v, f"Variable {k} is not set to {v}"
