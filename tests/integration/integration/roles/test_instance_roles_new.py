#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant_backports
import pytest
from jubilant_backports import Juju
from mysql.connector.errors import ProgrammingError

from ...helpers_ha import (
    CHARM_METADATA,
    execute_queries_on_unit,
    get_app_units,
    get_mysql_primary_unit,
    get_mysql_server_credentials,
    get_unit_address,
    wait_for_apps_status,
)

logger = logging.getLogger(__name__)

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
        f"{INTEGRATOR_APP_NAME}1",
        base="ubuntu@24.04",
    )
    juju.deploy(
        INTEGRATOR_APP_NAME,
        f"{INTEGRATOR_APP_NAME}2",
        base="ubuntu@22.04",
    )

    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, DATABASE_APP_NAME),
    )
    juju.wait(
        ready=wait_for_apps_status(
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
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME
        ),
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
        [
            "CREATE TABLE charmed_read_db.test_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
            "INSERT INTO charmed_read_db.test_table (`data`) VALUES ('test_data_1'), ('test_data_2')",
        ],
        commit=True,
    )

    data_integrator_unit_name = get_app_units(juju, f"{INTEGRATOR_APP_NAME}1")[0]
    results = juju.run(data_integrator_unit_name, "get-credentials").results

    logger.info("Checking that the charmed_read role can read from an existing table")
    rows = execute_queries_on_unit(
        primary_unit_address,
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
            primary_unit_address,
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
            primary_unit_address,
            results["mysql"]["username"],
            results["mysql"]["password"],
            [
                "CREATE TABLE charmed_read_db.new_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
            ],
            commit=True,
        )

    juju.remove_relation(f"{DATABASE_APP_NAME}:database", f"{INTEGRATOR_APP_NAME}1:mysql")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_blocked, f"{INTEGRATOR_APP_NAME}1"),
    )


@pytest.mark.abort_on_fail
def test_charmed_dml_role(juju: Juju):
    """Test the charmed_dml role."""
    juju.config(
        f"{INTEGRATOR_APP_NAME}1", {"database-name": "charmed_dml_db", "extra-user-roles": ""}
    )
    juju.integrate(f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME)
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME
        ),
    )

    juju.config(
        f"{INTEGRATOR_APP_NAME}2",
        {"database-name": "throwaway", "extra-user-roles": "charmed_dml"},
    )
    juju.integrate(f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME)
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME
        ),
    )

    mysql_unit_name = get_app_units(juju, DATABASE_APP_NAME)[0]
    primary_unit_name = next(
        unit_name
        for unit_name in get_app_units(juju, DATABASE_APP_NAME)
        if unit_name == get_mysql_primary_unit(juju, DATABASE_APP_NAME, mysql_unit_name)
    )
    primary_unit_address = get_unit_address(juju, DATABASE_APP_NAME, primary_unit_name)
    data_integrator_1_unit_name = get_app_units(juju, f"{INTEGRATOR_APP_NAME}1")[0]
    results = juju.run(data_integrator_1_unit_name, "get-credentials").results

    logger.info("Checking that when no role is specified the created user can do everything")
    rows = execute_queries_on_unit(
        primary_unit_address,
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

    data_integrator_2_unit_name = get_app_units(juju, f"{INTEGRATOR_APP_NAME}2")[0]
    results = juju.run(data_integrator_2_unit_name, "get-credentials").results

    logger.info("Checking that the charmed_dml role can read from an existing table")
    rows = execute_queries_on_unit(
        primary_unit_address,
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
        primary_unit_address,
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
            primary_unit_address,
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
        ready=wait_for_apps_status(
            jubilant_backports.all_blocked, f"{INTEGRATOR_APP_NAME}1", f"{INTEGRATOR_APP_NAME}2"
        ),
    )
