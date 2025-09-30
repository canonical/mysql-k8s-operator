# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import pathlib
import shutil
from time import sleep
from zipfile import ZipFile

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from .. import juju_, markers
from ..helpers import get_leader_unit, get_model_logs, get_unit_by_number
from .high_availability_helpers import get_sts_partition

logger = logging.getLogger(__name__)

TIMEOUT = 20 * 60
MYSQL_APP_NAME = "mysql-k8s"

METADATA = yaml.safe_load(pathlib.Path("./metadata.yaml").read_text())


# TODO: remove after next incompatible MySQL server version released in our snap
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@markers.amd64_only
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    config = {"profile": "testing", "plugin-audit-enabled": "false"}
    # MySQL 8.0.34 image, last known minor version incompatible
    resources = {
        "mysql-image": "ghcr.io/canonical/charmed-mysql@sha256:0f5fe7d7679b1881afde24ecfb9d14a9daade790ec787087aa5d8de1d7b00b21"
    }
    await ops_test.model.deploy(
        charm,
        application_name=MYSQL_APP_NAME,
        config=config,
        num_units=3,
        resources=resources,
        trust=True,
        base="ubuntu@22.04",
    )

    async with ops_test.fast_forward("30s"):
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME],
            status="active",
            timeout=TIMEOUT,
            raise_on_error=False,
        )


# TODO: remove after next incompatible MySQL server version released in our snap
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@markers.amd64_only
@pytest.mark.abort_on_fail
async def test_pre_upgrade_check(ops_test: OpsTest) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, MYSQL_APP_NAME)

    assert leader_unit is not None, "No leader unit found"
    logger.info("Run pre-upgrade-check action")
    await juju_.run_action(leader_unit, "pre-upgrade-check")


# TODO: remove after next incompatible MySQL server version released in our snap
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@markers.amd64_only
@pytest.mark.abort_on_fail
async def test_upgrade_to_failling(ops_test: OpsTest, charm) -> None:
    assert ops_test.model
    application = ops_test.model.applications[MYSQL_APP_NAME]

    with InjectFailure(
        path="src/upgrade.py",
        original_str="self.charm.recover_unit_after_restart()",
        replace_str="raise MySQLServiceNotRunningError",
    ):
        logger.info("Build charm with failure injected")
        new_charm = await charm_local_build(ops_test, charm, refresh=True)

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
    upgrading_unit = get_unit_by_number(MYSQL_APP_NAME, application.units, 2)

    assert upgrading_unit is not None, "No upgrading unit found"

    logger.info("Wait for upgrade to fail on upgrading unit")
    await ops_test.model.block_until(
        lambda: upgrading_unit.workload_status == "blocked",
        timeout=TIMEOUT,
        wait_period=5,
    )


# TODO: remove after next incompatible MySQL server version released in our rock
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@markers.amd64_only
@pytest.mark.abort_on_fail
async def test_rollback(ops_test, charm) -> None:
    application = ops_test.model.applications[MYSQL_APP_NAME]

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

    unit = get_unit_by_number(MYSQL_APP_NAME, application.units, 2)
    logger.info("Wait for upgrade to complete on first upgrading unit")
    await ops_test.model.block_until(
        lambda: unit.workload_status_message == "upgrade completed",
        timeout=TIMEOUT,
        wait_period=5,
    )

    logger.info("Ensure rollback has taken place")
    message = "Downgrade is incompatible. Resetting workload"
    warnings = await get_model_logs(ops_test, log_level="WARNING")
    assert message in warnings

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


class InjectFailure:
    def __init__(self, path: str, original_str: str, replace_str: str):
        self.path = path
        self.original_str = original_str
        self.replace_str = replace_str
        with open(path) as file:
            self.original_content = file.read()

    def __enter__(self):
        logger.info("Injecting failure")
        assert self.original_str in self.original_content, "replace content not found"
        new_content = self.original_content.replace(self.original_str, self.replace_str)
        assert self.original_str not in new_content, "original string not replaced"
        with open(self.path, "w") as file:
            file.write(new_content)

    def __exit__(self, exc_type, exc_value, traceback):
        logger.info("Reverting failure")
        with open(self.path, "w") as file:
            file.write(self.original_content)


async def charm_local_build(ops_test: OpsTest, charm, refresh: bool = False):
    """Wrapper for a local charm build zip file updating."""
    local_charms = pathlib.Path().glob("local-*.charm")
    for lc in local_charms:
        # clean up local charms from previous runs to avoid
        # pytest_operator_cache globbing them
        lc.unlink()

    # update charm zip

    update_files = ["src/constants.py", "src/upgrade.py"]

    charm = pathlib.Path(shutil.copy(charm, f"local-{pathlib.Path(charm).stem}.charm"))

    for path in update_files:
        with open(path) as f:
            content = f.read()

        with ZipFile(charm, mode="a") as charm_zip:
            charm_zip.writestr(path, content)

    if refresh:
        # when refreshing, return posix path
        return charm
    # when deploying, return prefixed full path
    return f"local:{charm.resolve()}"
