#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from collections.abc import Generator
from contextlib import suppress

import jubilant
import jubilant_backports
import pytest
from jubilant_backports import Juju

from .. import architecture
from ..markers import juju3
from .high_availability_helpers_new import (
    CHARM_METADATA,
    check_mysql_units_writes_increment,
    get_app_leader,
    get_app_units,
    get_k8s_stateful_set_partitions,
    get_mysql_max_written_value,
    get_mysql_primary_unit,
    get_mysql_variable_value,
    get_unit_by_number,
    wait_for_apps_status,
    wait_for_unit_message,
)

MYSQL_APP_1 = "db1"
MYSQL_APP_2 = "db2"
MYSQL_TEST_APP_NAME = "mysql-test-app"

MINUTE_SECS = 60

logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


@pytest.fixture(scope="module")
def first_model(juju: Juju, request: pytest.FixtureRequest) -> Generator:
    """Creates and return the first model."""
    yield juju.model


@pytest.fixture(scope="module")
def second_model(juju: Juju, request: pytest.FixtureRequest) -> Generator:
    """Creates and returns the second model."""
    model_name = f"{juju.model}-other"

    logging.info(f"Creating model: {model_name}")
    juju.add_model(model_name)

    yield model_name
    if request.config.getoption("--keep-models"):
        return

    logging.info(f"Destroying model: {model_name}")
    juju.destroy_model(model_name, destroy_storage=True, force=True)


@pytest.fixture()
def continuous_writes(first_model: str) -> Generator:
    """Starts continuous writes to the MySQL cluster for a test and clear the writes at the end."""
    model_1 = Juju(model=first_model)
    model_1_test_app_leader = get_app_leader(model_1, MYSQL_TEST_APP_NAME)

    logging.info("Clearing continuous writes")
    model_1.run(model_1_test_app_leader, "clear-continuous-writes")
    logging.info("Starting continuous writes")
    model_1.run(model_1_test_app_leader, "start-continuous-writes")

    yield

    logging.info("Clearing continuous writes")
    model_1.run(model_1_test_app_leader, "clear-continuous-writes")


@juju3
@pytest.mark.abort_on_fail
def test_build_and_deploy(first_model: str, second_model: str, charm: str) -> None:
    """Simple test to ensure that the MySQL application charms get deployed."""
    configuration = {"profile": "testing"}
    constraints = {"arch": architecture.architecture}
    resources = {"mysql-image": CHARM_METADATA["resources"]["mysql-image"]["upstream-source"]}

    logging.info("Deploying mysql clusters")
    model_1 = Juju(model=first_model)
    model_1.deploy(
        charm=charm,
        app=MYSQL_APP_1,
        base="ubuntu@22.04",
        config={**configuration, "cluster-name": "lima"},
        constraints=constraints,
        resources=resources,
        num_units=3,
    )
    model_2 = Juju(model=second_model)
    model_2.deploy(
        charm=charm,
        app=MYSQL_APP_2,
        base="ubuntu@22.04",
        config={**configuration, "cluster-name": "cuzco"},
        constraints=constraints,
        resources=resources,
        num_units=3,
    )

    logging.info("Waiting for the applications to settle")
    model_1.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_1),
        timeout=10 * MINUTE_SECS,
    )
    model_2.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_2),
        timeout=10 * MINUTE_SECS,
    )


@juju3
@pytest.mark.abort_on_fail
def test_async_relate(first_model: str, second_model: str) -> None:
    """Relate the two MySQL clusters."""
    logging.info("Creating offers in first model")
    model_1 = Juju(model=first_model)
    model_1.offer(MYSQL_APP_1, endpoint="replication-offer")

    logging.info("Consuming offer in second model")
    model_2 = Juju(model=second_model)
    model_2.consume(f"{first_model}.{MYSQL_APP_1}")

    logging.info("Relating the two mysql clusters")
    model_2.integrate(
        f"{MYSQL_APP_1}",
        f"{MYSQL_APP_2}:replication",
    )

    logging.info("Waiting for the applications to settle")
    model_1.wait(
        ready=wait_for_apps_status(jubilant_backports.any_blocked, MYSQL_APP_1),
        timeout=5 * MINUTE_SECS,
    )
    model_2.wait(
        ready=wait_for_apps_status(jubilant_backports.any_waiting, MYSQL_APP_2),
        timeout=5 * MINUTE_SECS,
    )


@juju3
@pytest.mark.abort_on_fail
def test_deploy_test_app(first_model: str) -> None:
    """Deploy the test application."""
    logging.info("Deploying the test application")
    model_1 = Juju(model=first_model)
    model_1.deploy(
        charm=MYSQL_TEST_APP_NAME,
        app=MYSQL_TEST_APP_NAME,
        base="ubuntu@22.04",
        channel="latest/edge",
        num_units=1,
    )

    logging.info("Relating the test application")
    model_1.integrate(
        f"{MYSQL_APP_1}:database",
        f"{MYSQL_TEST_APP_NAME}:database",
    )

    model_1.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_TEST_APP_NAME),
        timeout=10 * MINUTE_SECS,
    )


@juju3
@pytest.mark.abort_on_fail
def test_create_replication(first_model: str, second_model: str) -> None:
    """Run the create-replication action and wait for the applications to settle."""
    model_1 = Juju(model=first_model)
    model_2 = Juju(model=second_model)

    logging.info("Running create replication action")
    task = model_1.run(
        unit=get_app_leader(model_1, MYSQL_APP_1),
        action="create-replication",
        wait=5 * MINUTE_SECS,
    )
    task.raise_on_failure()

    logging.info("Waiting for the applications to settle")
    model_1.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_1),
        timeout=5 * MINUTE_SECS,
    )
    model_2.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_2),
        timeout=5 * MINUTE_SECS,
    )


@juju3
@pytest.mark.abort_on_fail
def test_upgrade_from_edge(
    first_model: str, second_model: str, charm: str, continuous_writes
) -> None:
    """Upgrade the two MySQL clusters."""
    model_1 = Juju(model=first_model)
    model_2 = Juju(model=second_model)

    run_pre_upgrade_checks(model_1, MYSQL_APP_1)
    run_upgrade_from_edge(model_1, MYSQL_APP_1, charm)

    run_pre_upgrade_checks(model_2, MYSQL_APP_2)
    run_upgrade_from_edge(model_2, MYSQL_APP_2, charm)


@juju3
@pytest.mark.abort_on_fail
def test_data_replication(first_model: str, second_model: str, continuous_writes) -> None:
    """Test to write to primary, and read the same data back from replicas."""
    logging.info("Testing data replication")
    results = get_mysql_max_written_values(first_model, second_model)

    assert len(results) == 6
    assert all(results[0] == x for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"


def get_mysql_max_written_values(first_model: str, second_model: str) -> list[int]:
    """Return list with max written value from all units."""
    model_1 = Juju(model=first_model)
    model_2 = Juju(model=second_model)

    logging.info("Stopping continuous writes")
    stopping_task = model_1.run(
        unit=get_app_leader(model_1, MYSQL_TEST_APP_NAME),
        action="stop-continuous-writes",
        params={},
    )
    stopping_task.raise_on_failure()

    time.sleep(5)
    results = []

    logging.info(f"Querying max value on all {MYSQL_APP_1} units")
    for unit_name in get_app_units(model_1, MYSQL_APP_1):
        unit_max_value = get_mysql_max_written_value(model_1, MYSQL_APP_1, unit_name)
        results.append(unit_max_value)

    logging.info(f"Querying max value on all {MYSQL_APP_2} units")
    for unit_name in get_app_units(model_2, MYSQL_APP_2):
        unit_max_value = get_mysql_max_written_value(model_2, MYSQL_APP_2, unit_name)
        results.append(unit_max_value)

    return results


def run_pre_upgrade_checks(juju: Juju, app_name: str) -> None:
    """Run the pre-upgrade-check actions."""
    app_leader = get_app_leader(juju, app_name)
    app_units = get_app_units(juju, app_name)

    logging.info("Run pre-upgrade-check action")
    task = juju.run(unit=app_leader, action="pre-upgrade-check")
    task.raise_on_failure()

    logging.info("Assert slow shutdown is enabled")
    for unit_name in app_units:
        value = get_mysql_variable_value(juju, app_name, unit_name, "innodb_fast_shutdown")
        assert value == 0

    logging.info("Assert primary is set to leader")
    mysql_primary = get_mysql_primary_unit(juju, app_name)
    assert mysql_primary == f"{app_name}/0", "Primary unit not set to unit 0"

    logging.info("Assert partition is set to 2")
    assert get_k8s_stateful_set_partitions(juju, app_name) == 2, "Partition not set to 2"


def run_upgrade_from_edge(juju: Juju, app_name: str, charm: str) -> None:
    """Update the second cluster."""
    logging.info("Ensure continuous writes are incrementing")
    check_mysql_units_writes_increment(juju, app_name)

    logging.info("Refresh the charm")
    juju.refresh(app=app_name, path=charm)

    app_leader = get_app_leader(juju, app_name)
    upgrade_unit = get_unit_by_number(juju, app_name, 2)

    logging.info("Wait for upgrade to complete on first upgrading unit")
    juju.wait(
        ready=wait_for_unit_message(app_name, upgrade_unit, "upgrade completed"),
        timeout=10 * MINUTE_SECS,
    )

    logging.info("Resume upgrade")
    while get_k8s_stateful_set_partitions(juju, app_name) == 2:
        # ignore action return error as it is expected when
        # the leader unit is the next one to be upgraded
        # due it being immediately rolled when the partition
        # is patched in the stateful set
        with suppress(jubilant.TaskError, jubilant_backports.TaskError):
            task = juju.run(unit=app_leader, action="resume-upgrade")
            task.raise_on_failure()

    logging.info("Wait for upgrade to complete")
    juju.wait(
        ready=lambda status: jubilant_backports.all_active(status, app_name),
        timeout=20 * MINUTE_SECS,
    )

    logging.info("Ensure continuous writes are incrementing")
    check_mysql_units_writes_increment(juju, app_name)
