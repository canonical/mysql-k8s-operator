#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from collections.abc import Generator

import jubilant_backports
import pytest
from jubilant_backports import Juju

from constants import CONTAINER_NAME

from .. import architecture
from ..markers import juju3
from .high_availability_helpers_new import (
    CHARM_METADATA,
    exec_k8s_container_command,
    get_app_leader,
    get_app_units,
    get_mysql_cluster_status,
    get_mysql_max_written_value,
    wait_for_apps_status,
)

MYSQL_APP_1 = "db1"
MYSQL_APP_2 = "db2"
MYSQL_ROUTER_NAME = "mysql-router-k8s"
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
def test_deploy_router_and_app(first_model: str) -> None:
    """Deploy the router and the test application."""
    logging.info("Deploying the router and test application")
    model_1 = Juju(model=first_model)
    model_1.deploy(
        charm=MYSQL_ROUTER_NAME,
        app=MYSQL_ROUTER_NAME,
        base="ubuntu@22.04",
        channel="8.0/edge",
        num_units=1,
        trust=True,
    )
    model_1.deploy(
        charm=MYSQL_TEST_APP_NAME,
        app=MYSQL_TEST_APP_NAME,
        base="ubuntu@22.04",
        channel="latest/edge",
        num_units=1,
        trust=False,
    )

    logging.info("Relating the router and test application")
    model_1.integrate(
        f"{MYSQL_ROUTER_NAME}:database",
        f"{MYSQL_TEST_APP_NAME}:database",
    )
    model_1.integrate(
        f"{MYSQL_ROUTER_NAME}:backend-database",
        f"{MYSQL_APP_1}:database",
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
def test_data_replication(first_model: str, second_model: str, continuous_writes) -> None:
    """Test to write to primary, and read the same data back from replicas."""
    logging.info("Testing data replication")
    results = get_mysql_max_written_values(first_model, second_model)

    assert len(results) == 6
    assert all(results[0] == x for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"


@juju3
@pytest.mark.abort_on_fail
def test_standby_promotion(first_model: str, second_model: str, continuous_writes) -> None:
    """Test graceful promotion of a standby cluster to primary."""
    model_2 = Juju(model=second_model)
    model_2_mysql_leader = get_app_leader(model_2, MYSQL_APP_2)

    logging.info("Promoting standby cluster to primary")
    promotion_task = model_2.run(
        unit=model_2_mysql_leader,
        action="promote-to-primary",
        params={"scope": "cluster"},
    )
    promotion_task.raise_on_failure()

    results = get_mysql_max_written_values(first_model, second_model)
    assert len(results) == 6
    assert all(results[0] == x for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"

    cluster_set_status = get_mysql_cluster_status(
        juju=model_2,
        unit=model_2_mysql_leader,
        cluster_set=True,
    )

    assert cluster_set_status["clusters"]["cuzco"]["clusterrole"] == "primary", (
        "standby not promoted to primary"
    )


@juju3
@pytest.mark.abort_on_fail
def test_failover(first_model: str, second_model: str) -> None:
    """Test switchover on primary cluster fail."""
    logging.info("Freezing mysqld on primary cluster units")
    model_2 = Juju(model=second_model)
    model_2_mysql_units = get_app_units(model_2, MYSQL_APP_2)

    # Simulating a failure on the primary cluster
    for unit_name in model_2_mysql_units:
        exec_k8s_container_command(
            juju=model_2,
            unit_name=unit_name,
            container_name=CONTAINER_NAME,
            command="pkill -f mysqld --signal SIGSTOP",
        )

    logging.info("Promoting standby cluster to primary with force flag")
    model_1 = Juju(model=first_model)
    model_1_mysql_leader = get_app_leader(model_1, MYSQL_APP_1)

    promotion_task = model_1.run(
        unit=model_1_mysql_leader,
        action="promote-to-primary",
        params={"scope": "cluster", "force": True},
        wait=5 * MINUTE_SECS,
    )
    promotion_task.raise_on_failure()

    logging.info("Checking clusters statuses")
    cluster_set_status = get_mysql_cluster_status(
        juju=model_1,
        unit=model_1_mysql_leader,
        cluster_set=True,
    )

    assert cluster_set_status["clusters"]["lima"]["clusterrole"] == "primary", (
        "standby not promoted to primary",
    )
    assert cluster_set_status["clusters"]["cuzco"]["globalstatus"] == "invalidated", (
        "old primary not invalidated"
    )

    # Restore mysqld process
    logging.info("Unfreezing mysqld on primary cluster units")
    for unit_name in model_2_mysql_units:
        exec_k8s_container_command(
            juju=model_2,
            unit_name=unit_name,
            container_name=CONTAINER_NAME,
            command="pkill -f mysqld --signal SIGCONT",
        )


@juju3
@pytest.mark.abort_on_fail
def test_rejoin_invalidated_cluster(
    first_model: str, second_model: str, continuous_writes
) -> None:
    """Test rejoin invalidated cluster with."""
    model_1 = Juju(model=first_model)
    model_1_mysql_leader = get_app_leader(model_1, MYSQL_APP_1)

    task = model_1.run(
        unit=model_1_mysql_leader,
        action="rejoin-cluster",
        params={"cluster-name": "cuzco"},
        wait=5 * MINUTE_SECS,
    )
    task.raise_on_failure()

    results = get_mysql_max_written_values(first_model, second_model)
    assert len(results) == 6
    assert all(results[0] == x for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"


@juju3
@pytest.mark.abort_on_fail
def test_unrelate_and_relate(first_model: str, second_model: str, continuous_writes) -> None:
    """Test removing and re-relating the two mysql clusters."""
    model_1 = Juju(model=first_model)
    model_2 = Juju(model=second_model)

    logging.info("Remove async relation")
    model_2.remove_relation(
        f"{MYSQL_APP_1}",
        f"{MYSQL_APP_2}:replication",
    )

    logging.info("Waiting for the applications to settle")
    model_1.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_1),
        timeout=10 * MINUTE_SECS,
    )
    model_2.wait(
        ready=wait_for_apps_status(jubilant_backports.all_blocked, MYSQL_APP_2),
        timeout=10 * MINUTE_SECS,
    )

    logging.info("Re relating the two mysql clusters")
    model_2.integrate(
        f"{MYSQL_APP_1}",
        f"{MYSQL_APP_2}:replication",
    )
    model_1.wait(
        ready=wait_for_apps_status(jubilant_backports.any_blocked, MYSQL_APP_1),
        timeout=5 * MINUTE_SECS,
    )

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
        timeout=10 * MINUTE_SECS,
    )
    model_2.wait(
        ready=wait_for_apps_status(jubilant_backports.all_active, MYSQL_APP_2),
        timeout=10 * MINUTE_SECS,
    )

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
