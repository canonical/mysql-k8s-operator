#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

DB_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
SCALE_APPS = 7
SCALE_UNITS = 3


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm and deploy 1 units to ensure a cluster is formed."""
    # Build and deploy charm from local source folder
    db_charm = await ops_test.build_charm(".")

    config = {"profile": "testing"}
    resources = {"mysql-image": DB_METADATA["resources"]["mysql-image"]["upstream-source"]}

    await ops_test.model.deploy(
        db_charm,
        application_name="mysql",
        config=config,
        num_units=1,
        resources=resources,
        series="jammy",
        trust=True,
    )

    for i in range(SCALE_APPS):
        config = {"database_name": f"database{i}", "sleep_interval": "2000"}
        await ops_test.model.deploy(
            "mysql-test-app",
            application_name=f"app{i}",
            num_units=1,
            channel="latest/edge",
            config=config,
            base="ubuntu@22.04",
        )
        await ops_test.model.deploy(
            "mysql-router-k8s",
            application_name=f"router{i}",
            num_units=1,
            channel="8.0/edge",
            trust=True,
            base="ubuntu@22.04",
        )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_relate_all(ops_test: OpsTest):
    """Relate all the applications to the database."""
    for i in range(SCALE_APPS):
        await ops_test.model.relate("mysql:database", f"router{i}:backend-database")
        await ops_test.model.relate(f"app{i}:database", f"router{i}:database")

    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in ops_test.model.units.values()),
        timeout=60 * 25,
        wait_period=5,
    )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_scale_out(ops_test: OpsTest):
    """Scale database and routers."""
    await ops_test.model.applications["mysql"].scale(SCALE_UNITS)
    for i in range(SCALE_APPS):
        await ops_test.model.applications[f"router{i}"].scale(SCALE_UNITS)
    expected_unit_sum = SCALE_UNITS + 4 * SCALE_APPS
    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in ops_test.model.units.values())
        and len(ops_test.model.units) == expected_unit_sum,
        timeout=60 * 30,
        wait_period=5,
    )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_scale_in(ops_test: OpsTest):
    """Scale database and routers."""
    await ops_test.model.applications["mysql"].scale(1)
    for i in range(SCALE_APPS):
        await ops_test.model.applications[f"router{i}"].scale(1)
    expected_unit_sum = 1 + 2 * SCALE_APPS
    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in ops_test.model.units.values())
        and len(ops_test.model.units) == expected_unit_sum,
        timeout=60 * 15,
        wait_period=5,
    )
