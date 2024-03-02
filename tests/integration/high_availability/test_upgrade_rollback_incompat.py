# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import pathlib
import shutil
import subprocess
from time import sleep
from zipfile import ZipFile

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from .. import juju_
from ..helpers import get_leader_unit, get_unit_by_index
from .high_availability_helpers import get_sts_partition

logger = logging.getLogger(__name__)

TIMEOUT = 20 * 60
MYSQL_APP_NAME = "mysql-k8s"

METADATA = yaml.safe_load(pathlib.Path("./metadata.yaml").read_text())


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    charm = await charm_local_build(ops_test)

    config = {"profile": "testing"}
    # MySQL 8.0.34 image, last known minor version incompatible
    resources = {
        "mysql-image": "ghcr.io/canonical/charmed-mysql@sha256:0f5fe7d7679b1881afde24ecfb9d14a9daade790ec787087aa5d8de1d7b00b21"
    }
    async with ops_test.fast_forward("10s"):
        await ops_test.model.deploy(
            charm,
            application_name=MYSQL_APP_NAME,
            config=config,
            num_units=3,
            resources=resources,
            trust=True,
        )

        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME],
            status="active",
            timeout=TIMEOUT,
        )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_pre_upgrade_check(ops_test: OpsTest) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, MYSQL_APP_NAME)

    assert leader_unit is not None, "No leader unit found"
    logger.info("Run pre-upgrade-check action")
    await juju_.run_action(leader_unit, "pre-upgrade-check")


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_upgrade_to_failling(ops_test: OpsTest) -> None:
    application = ops_test.model.applications[MYSQL_APP_NAME]
    logger.info("Build charm locally")

    sub_regex_failing_rejoin = (
        's/logger.debug("Recovering unit")'
        '/self.charm._mysql.set_instance_offline_mode(True); raise RetryError("dummy")/'
    )
    src_patch(sub_regex=sub_regex_failing_rejoin, file_name="src/upgrade.py")
    new_charm = await charm_local_build(ops_test, refresh=True)
    src_patch(revert=True)

    logger.info("Refresh the charm")
    # Current MySQL Image > 8.0.34
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
    await application.refresh(path=new_charm, resources=resources)

    logger.info("Wait for upgrade to start")
    await ops_test.model.block_until(
        lambda: "waiting" in {unit.workload_status for unit in application.units},
        timeout=TIMEOUT,
    )
    logger.info("Get first upgrading unit")
    upgrading_unit = get_unit_by_index(MYSQL_APP_NAME, application.units, 2)

    assert upgrading_unit is not None, "No upgrading unit found"

    logger.info("Wait for upgrade to fail on upgrading unit")
    await ops_test.model.block_until(
        lambda: upgrading_unit.workload_status == "blocked",
        timeout=TIMEOUT,
        wait_period=5,
    )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_rollback(ops_test) -> None:
    application = ops_test.model.applications[MYSQL_APP_NAME]

    charm = await charm_local_build(ops_test, refresh=True)

    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, MYSQL_APP_NAME)

    assert leader_unit is not None, "No leader unit found"

    logger.info("Run pre-upgrade-check action")
    await juju_.run_action(leader_unit, "pre-upgrade-check")

    logger.info("Refresh with previous charm")
    # MySQL 8.0.34 image
    resources = {
        "mysql-image": "ghcr.io/canonical/charmed-mysql@sha256:0f5fe7d7679b1881afde24ecfb9d14a9daade790ec787087aa5d8de1d7b00b21"
    }
    await application.refresh(path=charm, resources=resources)

    logger.info("Wait for upgrade to start")
    await ops_test.model.block_until(
        lambda: "waiting" in {unit.workload_status for unit in application.units},
        timeout=TIMEOUT,
    )

    unit = get_unit_by_index(MYSQL_APP_NAME, application.units, 2)
    logger.info("Wait for upgrade to complete on first upgrading unit")
    await ops_test.model.block_until(
        lambda: unit.workload_status_message == "upgrade completed",
        timeout=TIMEOUT,
        wait_period=5,
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


def src_patch(sub_regex: str = "", file_name: str = "", revert: bool = False) -> None:
    """Apply a patch to the source code."""
    if revert:
        cmd = "git checkout src/"  # revert changes on src/ dir
        logger.info("Reverting patch on source")
    else:
        cmd = f"sed -i -e '{sub_regex}' {file_name}"
        logger.info("Applying patch to source")
    subprocess.run([cmd], shell=True, check=True)


async def charm_local_build(ops_test: OpsTest, refresh: bool = False):
    """Wrapper for a local charm build zip file updating."""
    local_charms = pathlib.Path().glob("local-*.charm")
    for lc in local_charms:
        # clean up local charms from previous runs to avoid
        # pytest_operator_cache globbing them
        lc.unlink()

    charm = await ops_test.build_charm(".")

    if os.environ.get("CI") == "true":
        # CI will get charm from common cache
        # make local copy and update charm zip

        update_files = ["src/constants.py", "src/upgrade.py"]

        charm = pathlib.Path(shutil.copy(charm, f"local-{charm.stem}.charm"))

        for path in update_files:
            with open(path, "r") as f:
                content = f.read()

            with ZipFile(charm, mode="a") as charm_zip:
                charm_zip.writestr(path, content)

    if refresh:
        # when refreshing, return posix path
        return charm
    # when deploying, return prefixed full path
    return f"local:{charm.resolve()}"
