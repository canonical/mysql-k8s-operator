#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path
from time import sleep

import mysql.connector
import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

UNIT_IDS = [0, 1, 2]


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, num_units=1)

    # issuing dummy update_status just to trigger an event
    await ops_test.model.set_config({"update-status-hook-interval": "60s"})

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=True,
        timeout=1000,
    )
    assert len(ops_test.model.applications[APP_NAME].units) == 1
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_scale_to_ha(ops_test: OpsTest):
    """Scale the charm to HA."""
    await ops_test.model.applications[APP_NAME].scale(3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)

    assert len(ops_test.model.applications[APP_NAME].units) == 3


async def test_replicated_write_n_read(ops_test: OpsTest):
    """Write on primary and read on secondary."""
    # get the cluster admin password
    root_password = await get_password(ops_test, "root-password")
    # Primary will be ID 0, since the unit is deployed first
    host_ip = await get_pod_ip(ops_test, f"{APP_NAME}/0")
    # connect to the MySQL server
    cnx = db_connect(host_ip, root_password)
    cursor = cnx.cursor()
    # ensure cleanup (when running with --no-deploy)
    cursor.execute("DROP TABLE IF EXISTS mysql.charmtest;")
    # create a table
    cursor.execute("CREATE TABLE mysql.charmtest (test_field VARCHAR(255) PRIMARY KEY);")
    # insert a row
    cursor.execute("INSERT INTO mysql.charmtest VALUES ('hello');")
    # commit the changes
    cnx.commit()
    cursor.close()
    cnx.close()
    # replication take a little time
    sleep(1)
    # get secondary address
    secondary_host_ip = await get_pod_ip(ops_test, f"{APP_NAME}/1")
    cnx = db_connect(secondary_host_ip, root_password)
    cursor = cnx.cursor()
    # Query the table
    cursor.execute("SELECT * FROM mysql.charmtest;")
    # fetch the result
    result = cursor.fetchall()
    assert result[0][0] == "hello"


async def get_password(ops_test: OpsTest, password_key: str) -> str:
    """Get password using the action.

    Args:
        password_key: one of ["cluster-admin-password", "root-password", "server-admin-password"]
    Returns:
        str: user password
    """
    unit = ops_test.model.units.get(f"{APP_NAME}/0")
    action = await unit.run_action("get-generated-passwords")
    result = await action.wait()
    return result.results[password_key]


def db_connect(host: str, root_password: str):
    """Create a connection to the MySQL server.

    uses root user to connect to the MySQL server.

    Returns:
        MySQLConnection: connection to the MySQL server
    """
    cnx = mysql.connector.connect(user="root", password=root_password, host=host)
    return cnx


async def get_pod_ip(ops_test: OpsTest, unit_name: str) -> str:
    """Get the pod IP address for the given unit.

    Args:
        ops_test: test fixture
        unit_name: unit name
    Returns:
        str: pod IP address
    """
    status = await ops_test.model.get_status()
    for _, unit in status["applications"][APP_NAME]["units"].items():
        if unit["provider-id"] == unit_name.replace("/", "-"):
            pod_ip = unit["address"]
            break

    return pod_ip
