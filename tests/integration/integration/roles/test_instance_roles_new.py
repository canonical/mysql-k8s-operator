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

from ...helpers_ha import (
    execute_queries_on_unit,
    get_mysql_primary_unit,
    get_mysql_server_credentials,
    wait_for_apps_status,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

DATABASE_APP_NAME = METADATA["name"]
INTEGRATOR_APP_NAME = "data-integrator"


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm) -> None:
    """Simple test to ensure that the mysql and data-integrator charms get deployed."""
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    juju.deploy(
        charm,
        DATABASE_APP_NAME,
        num_units=3,
        resources=resources,
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
        base="ubuntu@22.04",
    )

    juju.wait(
        wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME),
    )
    juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_blocked, f"{INTEGRATOR_APP_NAME}1", f"{INTEGRATOR_APP_NAME}2"
        ),
    )


@pytest.mark.abort_on_fail
def test_charmed_read_role(juju: Juju):
    """Test the charmed_read predefined role."""
    juju.config(
        f"{INTEGRATOR_APP_NAME}1",
        {"database-name": "charmed_read_db", "extra-user-roles": "charmed_read"},
    )
    juju.integrate(f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME)
    status = juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME
        ),
    )

    primary_unit_name, primary_unit = next(
        (unit_name, unit)
        for (unit_name, unit) in status.apps[DATABASE_APP_NAME].units.items()
        if unit_name == get_mysql_primary_unit(juju, DATABASE_APP_NAME)
    )
    server_config_credentials = get_mysql_server_credentials(juju, primary_unit_name)

    execute_queries_on_unit(
        primary_unit.address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        [
            "CREATE TABLE charmed_read_db.test_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
            "INSERT INTO charmed_read_db.test_table (`data`) VALUES ('test_data_1'), ('test_data_2')",
        ],
        commit=True,
    )

    data_integrator_unit_name = next(iter(status.apps[f"{INTEGRATOR_APP_NAME}1"].units.keys()))
    results = juju.run(data_integrator_unit_name, "get-credentials").results

    logger.info("Checking that the charmed_read role can read from an existing table")
    rows = execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "SELECT `data` FROM charmed_read_db.test_table",
        ],
        commit=True,
    )
    assert sorted(rows) == sorted([
        "test_data_1",
        "test_data_2",
    ]), "Unexpected data in charmed_read_db with charmed_read role"

    logger.info("Checking that the charmed_read role cannot write into an existing table")
    with pytest.raises(ProgrammingError):
        execute_queries_on_unit(
            primary_unit.address,
            results["mysql"]["username"],
            results["mysql"]["password"],
            [
                "INSERT INTO charmed_read_db.test_table (`data`) VALUES ('test_data_3')",
            ],
            commit=True,
        )

    logger.info("Checking that the charmed_read role cannot create a new table")
    with pytest.raises(ProgrammingError):
        execute_queries_on_unit(
            primary_unit.address,
            results["mysql"]["username"],
            results["mysql"]["password"],
            [
                "CREATE TABLE charmed_read_db.new_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
            ],
            commit=True,
        )

    juju.remove_relation(f"{DATABASE_APP_NAME}:database", f"{INTEGRATOR_APP_NAME}1:mysql")
    juju.wait(
        wait_for_apps_status(jubilant_backports.all_blocked, f"{INTEGRATOR_APP_NAME}1"),
    )


@pytest.mark.abort_on_fail
def test_charmed_dml_role(juju: Juju):
    """Test the charmed_dml role."""
    juju.config(
        f"{INTEGRATOR_APP_NAME}1", {"database-name": "charmed_dml_db", "extra-user-roles": ""}
    )
    juju.integrate(f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME)
    juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME
        ),
    )

    juju.config(
        f"{INTEGRATOR_APP_NAME}2",
        {"database-name": "throwaway", "extra-user-roles": "charmed_dml"},
    )
    juju.integrate(f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME)
    status = juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME
        ),
    )

    mysql_unit_name = next(iter(status.apps[DATABASE_APP_NAME].units.keys()))
    primary_unit = next(
        unit
        for (unit_name, unit) in status.apps[DATABASE_APP_NAME].units.items()
        if unit_name == get_mysql_primary_unit(juju, DATABASE_APP_NAME, mysql_unit_name)
    )
    data_integrator_1_unit_name = next(iter(status.apps[f"{INTEGRATOR_APP_NAME}1"].units.keys()))
    results = juju.run(data_integrator_1_unit_name, "get-credentials").results

    logger.info("Checking that when no role is specified the created user can do everything")
    rows = execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "CREATE TABLE charmed_dml_db.test_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
            "INSERT INTO charmed_dml_db.test_table (`data`) VALUES ('test_data_1'), ('test_data_2')",
            "SELECT `data` FROM charmed_dml_db.test_table",
        ],
        commit=True,
    )
    assert sorted(rows) == sorted([
        "test_data_1",
        "test_data_2",
    ]), "Unexpected data in charmed_dml_db with charmed_dml role"

    data_integrator_2_unit_name = next(iter(status.apps[f"{INTEGRATOR_APP_NAME}2"].units.keys()))
    results = juju.run(data_integrator_2_unit_name, "get-credentials").results

    logger.info("Checking that the charmed_dml role can read from an existing table")
    rows = execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "SELECT `data` FROM charmed_dml_db.test_table",
        ],
        commit=True,
    )
    assert sorted(rows) == sorted([
        "test_data_1",
        "test_data_2",
    ]), "Unexpected data in charmed_dml_db with charmed_dml role"

    logger.info("Checking that the charmed_dml role can write into an existing table")
    execute_queries_on_unit(
        primary_unit.address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "INSERT INTO charmed_dml_db.test_table (`data`) VALUES ('test_data_3')",
        ],
        commit=True,
    )

    logger.info("Checking that the charmed_dml role cannot create a new table")
    with pytest.raises(ProgrammingError):
        execute_queries_on_unit(
            primary_unit.address,
            results["mysql"]["username"],
            results["mysql"]["password"],
            [
                "CREATE TABLE charmed_dml_db.new_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
            ],
            commit=True,
        )

    juju.remove_relation(
        f"{DATABASE_APP_NAME}:database",
        f"{INTEGRATOR_APP_NAME}1:mysql",
    )
    juju.remove_relation(
        f"{DATABASE_APP_NAME}:database",
        f"{INTEGRATOR_APP_NAME}2:mysql",
    )
    juju.wait(
        wait_for_apps_status(
            jubilant_backports.all_blocked, f"{INTEGRATOR_APP_NAME}1", f"{INTEGRATOR_APP_NAME}2"
        ),
    )
