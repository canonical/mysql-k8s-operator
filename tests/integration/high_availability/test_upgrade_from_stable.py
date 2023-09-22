# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from integration.helpers import (
    get_leader_unit,
    get_primary_unit,
    get_unit_by_index,
    retrieve_database_variable_value,
)
from integration.high_availability.high_availability_helpers import (
    METADATA,
    ensure_all_units_continuous_writes_incrementing,
    relate_mysql_and_application,
)
from lightkube import Client
from lightkube.resources.apps_v1 import StatefulSet
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60

MYSQL_APP_NAME = "mysql-k8s"
TEST_APP_NAME = "test-app"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy_stable(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    await asyncio.gather(
        ops_test.model.deploy(
            MYSQL_APP_NAME,
            application_name=MYSQL_APP_NAME,
            num_units=3,
            channel="8.0/stable",
            trust=True,
            config={"profile": "testing"},
        ),
        ops_test.model.deploy(
            f"mysql-{TEST_APP_NAME}",
            application_name=TEST_APP_NAME,
            num_units=1,
            channel="latest/edge",
        ),
    )
    await relate_mysql_and_application(ops_test, MYSQL_APP_NAME, TEST_APP_NAME)
    logger.info("Wait for applications to become active")
    await ops_test.model.wait_for_idle(
        apps=[MYSQL_APP_NAME, TEST_APP_NAME],
        status="active",
        timeout=TIMEOUT,
    )
    assert len(ops_test.model.applications[MYSQL_APP_NAME].units) == 3


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_pre_upgrade_check(ops_test: OpsTest) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    mysql_units = ops_test.model.applications[MYSQL_APP_NAME].units

    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, MYSQL_APP_NAME)
    assert leader_unit is not None, "No leader unit found"

    logger.info("Run pre-upgrade-check action")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()

    logger.info("Assert slow shutdown is enabled")
    for unit in mysql_units:
        value = await retrieve_database_variable_value(ops_test, unit, "innodb_fast_shutdown")
        assert value == 0, f"innodb_fast_shutdown not 0 at {unit.name}"

    primary_unit = await get_primary_unit(ops_test, leader_unit, MYSQL_APP_NAME)

    assert primary_unit.name == f"{MYSQL_APP_NAME}/0", "Primary unit not set to unit 0"

    logger.info("Assert partition is set to 2")
    client = Client()
    statefulset = client.get(
        res=StatefulSet, namespace=ops_test.model.info.name, name=MYSQL_APP_NAME
    )

    assert statefulset.spec.updateStrategy.rollingUpdate.partition == 2, "Partition not set to 2"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_upgrade_from_stable(ops_test: OpsTest):
    """Test updating from stable channel."""
    application = ops_test.model.applications[MYSQL_APP_NAME]
    logger.info("Build charm locally")
    charm = await ops_test.build_charm(".")

    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
    application = ops_test.model.applications[MYSQL_APP_NAME]

    logger.info("Build charm locally")
    charm = await ops_test.build_charm(".")

    logger.info("Refresh the charm")
    await application.refresh(path=charm, resources=resources)

    logger.info("Wait for upgrade to complete on first upgrading unit")
    # highest ordinal unit always the first to upgrade
    unit = get_unit_by_index(MYSQL_APP_NAME, application.units, 2)

    await ops_test.model.block_until(
        lambda: unit.workload_status_message == "upgrade completed", timeout=TIMEOUT
    )

    leader_unit = await get_leader_unit(ops_test, MYSQL_APP_NAME)
    assert leader_unit is not None, "No leader unit found"

    logger.info("Resume upgrade")
    action = await leader_unit.run_action("resume-upgrade")
    await action.wait()

    logger.info("Wait for upgrade to complete")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME], status="active", idle_period=30, timeout=TIMEOUT
        )

    logger.info("Ensure continuous_writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test)
