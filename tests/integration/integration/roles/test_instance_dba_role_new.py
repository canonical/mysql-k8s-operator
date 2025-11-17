#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.


import jubilant_backports
import pytest
from jubilant_backports import Juju

from ...helpers_ha import (
    CHARM_METADATA,
    execute_queries_on_unit,
    get_app_units,
    get_mysql_primary_unit,
    get_mysql_server_credentials,
    get_unit_address,
    wait_for_apps_status,
)

DATABASE_APP_NAME = CHARM_METADATA["name"]
INTEGRATOR_APP_NAME = "data-integrator"


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Simple test to ensure that the mysql and data-integrator charms get deployed."""
    juju.deploy(
        charm,
        DATABASE_APP_NAME,
        num_units=3,
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
        base="ubuntu@22.04",
        config={"profile": "testing"},
    )
    juju.deploy(
        INTEGRATOR_APP_NAME,
        base="ubuntu@24.04",
    )

    juju.wait(ready=wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME))
    juju.wait(ready=wait_for_apps_status(jubilant_backports.all_blocked, INTEGRATOR_APP_NAME))


@pytest.mark.abort_on_fail
def test_charmed_dba_role(juju: Juju):
    """Test the DBA predefined role."""
    juju.config(
        INTEGRATOR_APP_NAME,
        {
            "database-name": "charmed_dba_db",
            "extra-user-roles": "charmed_dba",
        },
    )
    juju.integrate(INTEGRATOR_APP_NAME, DATABASE_APP_NAME)
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, INTEGRATOR_APP_NAME, DATABASE_APP_NAME
        )
    )

    primary_unit_name = next(
        unit_name
        for unit_name in get_app_units(juju, DATABASE_APP_NAME)
        if unit_name == get_mysql_primary_unit(juju, DATABASE_APP_NAME)
    )
    primary_unit_address = get_unit_address(juju, DATABASE_APP_NAME, primary_unit_name)
    server_config_credentials = get_mysql_server_credentials(juju, primary_unit_name)

    execute_queries_on_unit(
        primary_unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        ["CREATE DATABASE IF NOT EXISTS test"],
        commit=True,
    )

    data_integrator_unit_name = get_app_units(juju, INTEGRATOR_APP_NAME)[0]
    results = juju.run(data_integrator_unit_name, "get-credentials").results

    rows = execute_queries_on_unit(
        primary_unit_address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        ["SHOW DATABASES"],
        commit=True,
    )

    assert "test" in rows, "Database is not visible to DBA user"
