#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from mysql.connector.errors import ProgrammingError
from pytest_operator.plugin import OpsTest

from .. import juju_
from ..helpers import (
    execute_queries_on_unit,
    get_primary_unit,
    get_unit_address,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

DATABASE_APP_NAME = METADATA["name"]
INTEGRATOR_APP_NAME = "data-integrator"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm) -> None:
    """Simple test to ensure that the mysql and data-integrator charms get deployed."""
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    async with ops_test.fast_forward("10s"):
        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                application_name=DATABASE_APP_NAME,
                num_units=3,
                resources=resources,
                base="ubuntu@22.04",
                config={"profile": "testing"},
            ),
            ops_test.model.deploy(
                INTEGRATOR_APP_NAME,
                application_name=f"{INTEGRATOR_APP_NAME}1",
                base="ubuntu@24.04",
            ),
            ops_test.model.deploy(
                INTEGRATOR_APP_NAME,
                application_name=f"{INTEGRATOR_APP_NAME}2",
                base="ubuntu@24.04",
            ),
        )

    await ops_test.model.wait_for_idle(
        apps=[DATABASE_APP_NAME],
        status="active",
    )
    await ops_test.model.wait_for_idle(
        apps=[f"{INTEGRATOR_APP_NAME}1", f"{INTEGRATOR_APP_NAME}2"],
        status="blocked",
    )


@pytest.mark.abort_on_fail
async def test_charmed_dba_role(ops_test: OpsTest):
    """Test the database-level DBA role."""
    await ops_test.model.applications[f"{INTEGRATOR_APP_NAME}1"].set_config({
        "database-name": "preserved",
        "extra-user-roles": "",
    })
    await ops_test.model.add_relation(f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle(
        apps=[f"{INTEGRATOR_APP_NAME}1", DATABASE_APP_NAME],
        status="active",
    )

    await ops_test.model.applications[f"{INTEGRATOR_APP_NAME}2"].set_config({
        "database-name": "throwaway",
        "extra-user-roles": "charmed_dba_preserved_00",
    })
    await ops_test.model.add_relation(f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle(
        apps=[f"{INTEGRATOR_APP_NAME}2", DATABASE_APP_NAME],
        status="active",
    )

    mysql_unit = ops_test.model.applications[DATABASE_APP_NAME].units[0]
    primary_unit = await get_primary_unit(ops_test, mysql_unit, DATABASE_APP_NAME)
    primary_unit_address = await get_unit_address(ops_test, primary_unit.name)

    data_integrator_2_unit = ops_test.model.applications[f"{INTEGRATOR_APP_NAME}2"].units[0]
    results = await juju_.run_action(data_integrator_2_unit, "get-credentials")

    logger.info("Checking that the database-level DBA role cannot create new databases")
    with pytest.raises(ProgrammingError):
        execute_queries_on_unit(
            primary_unit_address,
            results["mysql"]["username"],
            results["mysql"]["password"],
            ["CREATE DATABASE IF NOT EXISTS test"],
            commit=True,
        )

    logger.info("Checking that the database-level DBA role can see all databases")
    execute_queries_on_unit(
        primary_unit_address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        ["SHOW DATABASES"],
        commit=True,
    )

    logger.info("Checking that the database-level DBA role can create a new table")
    execute_queries_on_unit(
        primary_unit_address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "CREATE TABLE preserved.test_table (`id` SERIAL PRIMARY KEY, `data` TEXT)",
        ],
        commit=True,
    )

    logger.info("Checking that the database-level DBA role can write into an existing table")
    execute_queries_on_unit(
        primary_unit_address,
        results["mysql"]["username"],
        results["mysql"]["password"],
        [
            "INSERT INTO preserved.test_table (`data`) VALUES ('test_data_1'), ('test_data_2')",
        ],
        commit=True,
    )

    logger.info("Checking that the database-level DBA role can read from an existing table")
    rows = execute_queries_on_unit(
        primary_unit_address,
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
