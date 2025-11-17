#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import jubilant_backports
import pytest
import yaml
from jubilant_backports import Juju
from mysql.connector.errors import ProgrammingError

from ...helpers_ha import execute_queries_on_unit, get_mysql_primary_unit, wait_for_apps_status

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

DATABASE_APP_NAME = METADATA["name"]
INTEGRATOR_APP_NAME = "data-integrator"


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Simple test to ensure that the mysql and data-integrator charms get deployed."""
    juju.deploy(
        charm,
        DATABASE_APP_NAME,
        num_units=3,
        resources={"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]},
        base="ubuntu@22.04",
        config={"profile": "testing"},
    )
    juju.deploy(
        INTEGRATOR_APP_NAME,
        f"{INTEGRATOR_APP_NAME}1",
        base="ubuntu@24.04",
    )
    juju.deploy(
        INTEGRATOR_APP_NAME,
        f"{INTEGRATOR_APP_NAME}2",
        base="ubuntu@24.04",
    )

    juju.wait(wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME))
    juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_blocked, f"{INTEGRATOR_APP_NAME}1", f"{INTEGRATOR_APP_NAME}2"
        )
    )


@pytest.mark.abort_on_fail
def test_charmed_dba_role(juju: Juju):
    """Test the database-level DBA role."""
    juju.config(
        f"{INTEGRATOR_APP_NAME}1",
        {
            "database-name": "preserved",
            "extra-user-roles": "",
        },
    )
    juju.integrate(f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME)
    juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME
        )
    )

    juju.config(
        f"{INTEGRATOR_APP_NAME}2",
        {
            "database-name": "throwaway",
            "extra-user-roles": "charmed_dba_preserved_00",
        },
    )
    juju.integrate(f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME)
    status = juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME
        )
    )

    primary_unit_name, primary_unit = next(
        (unit_name, unit)
        for (unit_name, unit) in status.apps[DATABASE_APP_NAME].units.items()
        if unit_name == get_mysql_primary_unit(juju, DATABASE_APP_NAME)
    )

    data_integrator_2_unit_name = next(iter(status.apps[f"{INTEGRATOR_APP_NAME}2"].units.keys()))
    results = juju.run(data_integrator_2_unit_name, "get-credentials").results

    logger.info("Checking that the database-level DBA role cannot create new databases")
    with pytest.raises(ProgrammingError):
        execute_queries_on_unit(
            primary_unit.address,
            results["mysql"]["username"],
            results["mysql"]["password"],
            ["CREATE DATABASE IF NOT EXISTS test"],
            commit=True,
        )

    logger.info("Checking that the database-level DBA role can see all databases")
    execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        ["SHOW DATABASES"],
        commit=True,
    )

    logger.info("Checking that the database-level DBA role can create a new table")
    execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "CREATE TABLE preserved.test_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
        ],
        commit=True,
    )

    logger.info("Checking that the database-level DBA role can write into an existing table")
    execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "INSERT INTO preserved.test_table (`data`) VALUES ('test_data_1'), ('test_data_2')",
        ],
        commit=True,
    )

    logger.info("Checking that the database-level DBA role can read from an existing table")
    rows = execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "SELECT `data` FROM preserved.test_table",
        ],
        commit=True,
    )
    assert sorted(rows) == sorted([
        "test_data_1",
        "test_data_2",
    ]), "Unexpected data in preserved with charmed_dba_preserved_00 role"
