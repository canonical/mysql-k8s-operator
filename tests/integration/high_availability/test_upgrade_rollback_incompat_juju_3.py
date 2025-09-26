#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import shutil
import time
import zipfile
from contextlib import suppress
from pathlib import Path

import jubilant_backports
import pytest
from jubilant_backports import Juju, TaskError

from ..markers import amd64_only
from .high_availability_helpers_new import (
    CHARM_METADATA,
    get_app_leader,
    get_k8s_stateful_set_partitions,
    get_model_debug_logs,
    get_unit_by_index,
    wait_for_apps_status,
    wait_for_unit_message,
    wait_for_unit_status,
)

MYSQL_APP_NAME = "mysql-k8s"

MINUTE_SECS = 60

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


# TODO: remove AMD64 marker after next incompatible MySQL server version is released in our snap
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@amd64_only
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: Juju, charm: str) -> None:
    """Simple test to ensure that the MySQL and application charms get deployed."""
    juju.deploy(
        charm=charm,
        app=MYSQL_APP_NAME,
        base="ubuntu@22.04",
        config={"profile": "testing", "plugin-audit-enabled": "false"},
        resources={
            # MySQL 8.0.34 image, last known minor version incompatible
            "mysql-image": "ghcr.io/canonical/charmed-mysql@sha256:0f5fe7d7679b1881afde24ecfb9d14a9daade790ec787087aa5d8de1d7b00b21",
        },
        num_units=3,
        trust=True,
    )

    logging.info("Wait for applications to become active")
    juju.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_NAME),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )


# TODO: remove AMD64 marker after next incompatible MySQL server version is released in our snap
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@amd64_only
@pytest.mark.abort_on_fail
def test_pre_upgrade_check(juju: Juju) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    mysql_leader = get_app_leader(juju, MYSQL_APP_NAME)

    logging.info("Run pre-upgrade-check action")
    task = juju.run(unit=mysql_leader, action="pre-upgrade-check")
    task.raise_on_failure()


# TODO: remove AMD64 marker after next incompatible MySQL server version is released in our snap
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@amd64_only
@pytest.mark.abort_on_fail
def test_upgrade_to_failing(juju: Juju, charm: str) -> None:
    with InjectFailure(
        path="src/upgrade.py",
        original_str="self.charm.recover_unit_after_restart()",
        replace_str="raise MySQLServiceNotRunningError",
    ):
        logging.info("Build charm with failure injected")
        new_charm = get_locally_built_charm(charm)

    logging.info("Refresh the charm")
    juju.refresh(
        app=MYSQL_APP_NAME,
        path=new_charm,
        resources={
            # Current MySQL Image > 8.0.34
            "mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"],
        },
    )

    logging.info("Wait for upgrade to start")
    juju.wait(
        ready=lambda status: jubilant_backports.any_maintenance(status, MYSQL_APP_NAME),
        timeout=10 * MINUTE_SECS,
    )

    logging.info("Get first upgrading unit")
    upgrade_unit = get_unit_by_index(juju, MYSQL_APP_NAME, 2)

    logging.info("Wait for upgrade to fail on upgrading unit")
    juju.wait(
        ready=wait_for_unit_status(MYSQL_APP_NAME, upgrade_unit, "blocked"),
        timeout=10 * MINUTE_SECS,
    )


# TODO: remove AMD64 marker after next incompatible MySQL server version is released in our snap
# (details: https://github.com/canonical/mysql-operator/pull/472#discussion_r1659300069)
@amd64_only
@pytest.mark.abort_on_fail
def test_rollback(juju: Juju, charm: str) -> None:
    """Test upgrade rollback to a healthy revision."""
    mysql_app_leader = get_app_leader(juju, MYSQL_APP_NAME)
    mysql_upgrade_unit = get_unit_by_index(juju, MYSQL_APP_NAME, 2)

    time.sleep(10)

    logging.info("Run pre-upgrade-check action")
    task = juju.run(unit=mysql_app_leader, action="pre-upgrade-check")
    task.raise_on_failure()

    time.sleep(20)

    logging.info("Refresh with previous charm")
    juju.refresh(
        app=MYSQL_APP_NAME,
        path=charm,
        resources={
            # MySQL 8.0.34 image
            "mysql-image": "ghcr.io/canonical/charmed-mysql@sha256:0f5fe7d7679b1881afde24ecfb9d14a9daade790ec787087aa5d8de1d7b00b21",
        },
    )

    logging.info("Wait for upgrade to start")
    juju.wait(
        ready=lambda status: jubilant_backports.any_maintenance(status, MYSQL_APP_NAME),
        timeout=10 * MINUTE_SECS,
    )

    logging.info("Wait for upgrade to complete on first upgrading unit")
    juju.wait(
        ready=wait_for_unit_message(MYSQL_APP_NAME, mysql_upgrade_unit, "upgrade completed"),
        timeout=10 * MINUTE_SECS,
    )

    logging.info("Ensure rollback has taken place")
    unit_status_logs = get_model_debug_logs(juju, "WARNING", 100)
    assert "Downgrade is incompatible. Resetting workload" in unit_status_logs

    logging.info("Resume upgrade")
    while get_k8s_stateful_set_partitions(juju, MYSQL_APP_NAME) == 2:
        # ignore action return error as it is expected when
        # the leader unit is the next one to be upgraded
        # due it being immediately rolled when the partition
        # is patched in the stateful set
        with suppress(TaskError):
            task = juju.run(unit=mysql_app_leader, action="resume-upgrade")
            task.raise_on_failure()

    logging.info("Wait for upgrade to complete")
    juju.wait(
        ready=lambda status: jubilant_backports.all_active(status, MYSQL_APP_NAME),
        timeout=20 * MINUTE_SECS,
    )


class InjectFailure:
    def __init__(self, path: str, original_str: str, replace_str: str):
        self.path = path
        self.original_str = original_str
        self.replace_str = replace_str
        with open(path) as file:
            self.original_content = file.read()

    def __enter__(self):
        logging.info("Injecting failure")
        assert self.original_str in self.original_content, "replace content not found"
        new_content = self.original_content.replace(self.original_str, self.replace_str)
        assert self.original_str not in new_content, "original string not replaced"
        with open(self.path, "w") as file:
            file.write(new_content)

    def __exit__(self, exc_type, exc_value, traceback):
        logging.info("Reverting failure")
        with open(self.path, "w") as file:
            file.write(self.original_content)


def get_locally_built_charm(charm: str) -> str:
    """Wrapper for a local charm build zip file updating."""
    local_charm_paths = Path().glob("local-*.charm")

    # Clean up local charms from previous runs
    # to avoid pytest_operator_cache globbing them
    for charm_path in local_charm_paths:
        charm_path.unlink()

    # Create a copy of the charm to avoid modifying the original
    local_charm_path = shutil.copy(charm, f"local-{Path(charm).stem}.charm")
    local_charm_path = Path(local_charm_path)

    for path in ["src/constants.py", "src/upgrade.py"]:
        with open(path) as f:
            content = f.read()
        with zipfile.ZipFile(local_charm_path, mode="a") as charm_zip:
            charm_zip.writestr(path, content)

    return f"{local_charm_path.resolve()}"
