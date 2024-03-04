# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import shutil
import zipfile
from pathlib import Path
from time import sleep
from typing import Union

import pytest
from pytest_operator.plugin import OpsTest

from .. import juju_
from ..helpers import (
    get_leader_unit,
    get_primary_unit,
    get_relation_data,
    get_unit_by_index,
    retrieve_database_variable_value,
)
from .high_availability_helpers import (
    METADATA,
    ensure_all_units_continuous_writes_incrementing,
    get_sts_partition,
    relate_mysql_and_application,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60

MYSQL_APP_NAME = "mysql-k8s"
TEST_APP_NAME = "test-app"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy_latest(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    await asyncio.gather(
        ops_test.model.deploy(
            MYSQL_APP_NAME,
            application_name=MYSQL_APP_NAME,
            num_units=3,
            channel="8.0/edge",
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
    await juju_.run_action(leader_unit, "pre-upgrade-check")

    logger.info("Assert slow shutdown is enabled")
    for unit in mysql_units:
        value = await retrieve_database_variable_value(ops_test, unit, "innodb_fast_shutdown")
        assert value == 0, f"innodb_fast_shutdown not 0 at {unit.name}"

    primary_unit = await get_primary_unit(ops_test, leader_unit, MYSQL_APP_NAME)

    assert primary_unit.name == f"{MYSQL_APP_NAME}/0", "Primary unit not set to unit 0"

    logger.info("Assert partition is set to 2")

    assert get_sts_partition(ops_test, MYSQL_APP_NAME) == 2, "Partition not set to 2"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_upgrade_from_edge(ops_test: OpsTest, continuous_writes) -> None:
    logger.info("Ensure continuous_writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

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
    while get_sts_partition(ops_test, MYSQL_APP_NAME) == 2:
        # resume action sometime fails in CI, no clear reason
        try:
            await juju_.run_action(leader_unit, "resume-upgrade")
        except AssertionError:
            # ignore action return error as it is expected when
            # the leader unit is the next one to be upgraded
            # due it being immediately rolled when the partition
            # is patched in the statefulset
            pass

    logger.info("Wait for upgrade to complete")
    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in application.units),
        timeout=TIMEOUT,
    )

    logger.info("Ensure continuous_writes")
    await ensure_all_units_continuous_writes_incrementing(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_fail_and_rollback(ops_test, continuous_writes, built_charm) -> None:
    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, MYSQL_APP_NAME)
    assert leader_unit is not None, "No leader unit found"

    logger.info("Run pre-upgrade-check action")
    await juju_.run_action(leader_unit, "pre-upgrade-check")

    if not built_charm:
        # on CI built charm is cached and returned with build_charm
        # by the pytest-operator-cache plugin
        local_charm = await ops_test.build_charm(".")
    else:
        # return the built charm from the test
        local_charm = built_charm
    fault_charm = Path("/tmp/", local_charm.name)
    shutil.copy(local_charm, fault_charm)

    logger.info("Inject dependency fault")
    await inject_dependency_fault(ops_test, MYSQL_APP_NAME, fault_charm)

    application = ops_test.model.applications[MYSQL_APP_NAME]

    logger.info("Refresh the charm")
    await application.refresh(path=fault_charm)

    logger.info("Get first upgrading unit")
    # highest ordinal unit always the first to upgrade
    unit = get_unit_by_index(MYSQL_APP_NAME, application.units, 2)

    logger.info("Wait for upgrade to fail on first upgrading unit")
    await ops_test.model.block_until(
        lambda: unit.workload_status == "blocked",
        timeout=TIMEOUT,
    )

    logger.info("Ensure continuous_writes while in failure state on remaining units")
    mysql_units = [unit_ for unit_ in application.units if unit_.name != unit.name]
    await ensure_all_units_continuous_writes_incrementing(ops_test, mysql_units)

    logger.info("Re-run pre-upgrade-check action")
    await juju_.run_action(leader_unit, "pre-upgrade-check")

    logger.info("Re-refresh the charm")
    await application.refresh(path=local_charm)

    logger.info("Wait for upgrade to complete on first upgrading unit")
    await ops_test.model.block_until(
        lambda: unit.workload_status_message == "upgrade completed", timeout=TIMEOUT
    )

    logger.info("Resume upgrade")
    while get_sts_partition(ops_test, MYSQL_APP_NAME) == 2:
        # resume action sometime fails in CI, no clear reason
        try:
            await juju_.run_action(leader_unit, "resume-upgrade")
            sleep(2)
        except AssertionError:
            # ignore action return error as it is expected when
            # the leader unit is the next one to be upgraded
            # due it being immediately rolled when the partition
            # is patched in the statefulset
            pass

    logger.info("Wait for application to recover")
    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in application.units),
        timeout=TIMEOUT,
    )

    logger.info("Ensure continuous_writes after rollback procedure")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    # remove fault charm file
    fault_charm.unlink()


async def inject_dependency_fault(
    ops_test: OpsTest, application_name: str, charm_file: Union[str, Path]
) -> None:
    """Inject a dependency fault into the mysql charm."""
    # Open dependency.json and load current charm version
    with open("src/dependency.json", "r") as dependency_file:
        current_charm_version = json.load(dependency_file)["charm"]["version"]

    # query running dependency to overwrite with incompatible version
    relation_data = await get_relation_data(ops_test, application_name, "upgrade")

    loaded_dependency_dict = json.loads(relation_data[0]["application-data"]["dependencies"])
    loaded_dependency_dict["charm"]["upgrade_supported"] = f">{current_charm_version}"
    loaded_dependency_dict["charm"]["version"] = "999.999.999"

    # Overwrite dependency.json with incompatible version
    with zipfile.ZipFile(charm_file, mode="a") as charm_zip:
        charm_zip.writestr("src/dependency.json", json.dumps(loaded_dependency_dict))
