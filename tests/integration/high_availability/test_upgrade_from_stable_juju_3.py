#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from contextlib import suppress

import jubilant_backports
import pytest
from jubilant_backports import Juju, TaskError

from .high_availability_helpers_new import (
    CHARM_METADATA,
    check_mysql_units_writes_increment,
    get_app_leader,
    get_app_units,
    get_k8s_stateful_set_partitions,
    get_mysql_primary_unit,
    get_mysql_variable_value,
    get_unit_by_index,
    wait_for_apps_status,
    wait_for_unit_message,
)

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_TEST_APP_NAME = "mysql-test-app"

MINUTE_SECS = 60

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


@pytest.mark.abort_on_fail
def test_deploy_stable(juju: Juju) -> None:
    """Simple test to ensure that the MySQL and application charms get deployed."""
    logging.info("Deploying MySQL cluster")
    juju.deploy(
        charm=MYSQL_APP_NAME,
        app=MYSQL_APP_NAME,
        base="ubuntu@22.04",
        channel="8.0/stable",
        config={"profile": "testing"},
        num_units=3,
        trust=True,
    )
    juju.deploy(
        charm=MYSQL_TEST_APP_NAME,
        app=MYSQL_TEST_APP_NAME,
        base="ubuntu@22.04",
        channel="latest/edge",
        num_units=1,
        trust=False,
    )

    juju.integrate(
        f"{MYSQL_APP_NAME}:database",
        f"{MYSQL_TEST_APP_NAME}:database",
    )

    logging.info("Wait for applications to become active")
    juju.wait(
        ready=wait_for_apps_status(
            jubilant_backports.all_active, MYSQL_APP_NAME, MYSQL_TEST_APP_NAME
        ),
        error=jubilant_backports.any_blocked,
        timeout=20 * MINUTE_SECS,
    )


@pytest.mark.abort_on_fail
def test_pre_upgrade_check(juju: Juju) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    mysql_leader = get_app_leader(juju, MYSQL_APP_NAME)
    mysql_units = get_app_units(juju, MYSQL_APP_NAME)

    logging.info("Run pre-upgrade-check action")
    task = juju.run(unit=mysql_leader, action="pre-upgrade-check")
    task.raise_on_failure()

    logging.info("Assert slow shutdown is enabled")
    for unit_name in mysql_units:
        value = get_mysql_variable_value(juju, MYSQL_APP_NAME, unit_name, "innodb_fast_shutdown")
        assert value == 0

    logging.info("Assert primary is set to leader")
    mysql_primary = get_mysql_primary_unit(juju, MYSQL_APP_NAME)
    assert mysql_primary == f"{MYSQL_APP_NAME}/0", "Primary unit not set to unit 0"

    logging.info("Assert partition is set to 2")
    assert get_k8s_stateful_set_partitions(juju, MYSQL_APP_NAME) == 2, "Partition not set to 2"


@pytest.mark.abort_on_fail
def test_upgrade_from_stable(juju: Juju, charm: str, continuous_writes) -> None:
    """Update the second cluster."""
    logging.info("Ensure continuous writes are incrementing")
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)

    logging.info("Refresh the charm")
    juju.refresh(
        app=MYSQL_APP_NAME,
        path=charm,
        resources={"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]},
    )

    mysql_app_leader = get_app_leader(juju, MYSQL_APP_NAME)
    mysql_upgrade_unit = get_unit_by_index(juju, MYSQL_APP_NAME, 2)

    logging.info("Wait for upgrade to complete on first upgrading unit")
    juju.wait(
        ready=wait_for_unit_message(MYSQL_APP_NAME, mysql_upgrade_unit, "upgrade completed"),
        timeout=10 * MINUTE_SECS,
    )

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

    logging.info("Ensure continuous writes are incrementing")
    check_mysql_units_writes_increment(juju, MYSQL_APP_NAME)
