#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
import subprocess
from asyncio import gather
from pathlib import Path
from time import sleep
from typing import Optional

import pytest
import yaml
from juju.model import Model
from pytest_operator.plugin import OpsTest

from .. import architecture, juju_, markers
from ..helpers import (
    execute_queries_on_unit,
    get_cluster_status,
    get_leader_unit,
    get_unit_address,
)
from .high_availability_helpers import (
    DATABASE_NAME,
    TABLE_NAME,
    send_signal_to_pod_container_process,
)

logger = logging.getLogger(__name__)
MYSQL_APP1 = "db1"
MYSQL_APP2 = "db2"
MYSQL_ROUTER_APP_NAME = "mysql-router-k8s"
APPLICATION_APP_NAME = "mysql-test-app"

MYSQL_CONTAINER_NAME = "mysql"
MYSQLD_PROCESS_NAME = "mysqld"

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MINUTE = 60


@pytest.fixture(scope="module")
def first_model(ops_test: OpsTest) -> Optional[Model]:
    """Return the first model."""
    first_model = ops_test.model
    return first_model


@pytest.fixture(scope="module")
async def second_model(ops_test: OpsTest, first_model, request) -> Model:  # pyright: ignore [reportInvalidTypeForm]
    """Create and return the second model."""
    second_model_name = f"{first_model.info.name}-other"
    await ops_test._controller.add_model(second_model_name)
    subprocess.run(["juju", "switch", second_model_name], check=True)
    subprocess.run(
        ["juju", "set-model-constraints", f"arch={architecture.architecture}"], check=True
    )
    subprocess.run(["juju", "switch", first_model.info.name], check=True)
    second_model = Model()
    await second_model.connect(model_name=second_model_name)
    yield second_model  # pyright: ignore [reportReturnType]

    if request.config.getoption("--keep-models"):
        return
    logger.info("Destroying second model")
    await ops_test._controller.destroy_model(second_model_name, destroy_storage=True)


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_build_and_deploy(
    ops_test: OpsTest, first_model: Model, second_model: Model
) -> None:
    """Simple test to ensure that the mysql and application charms get deployed."""
    logger.info("Build mysql charm")
    charm = await ops_test.build_charm(".")

    config = {"cluster-name": "lima", "profile": "testing"}
    resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    logger.info("Deploying mysql clusters")
    await first_model.deploy(
        charm,
        application_name=MYSQL_APP1,
        num_units=3,
        config=config,
        resources=resources,
        trust=True,
    )
    config["cluster-name"] = "cuzco"
    await second_model.deploy(
        charm,
        application_name=MYSQL_APP2,
        num_units=3,
        config=config,
        resources=resources,
        trust=True,
    )

    logger.info("Waiting for the applications to settle")
    await gather(
        first_model.wait_for_idle(
            apps=[MYSQL_APP1],
            status="active",
            timeout=10 * MINUTE,
        ),
        second_model.wait_for_idle(
            apps=[MYSQL_APP2],
            status="active",
            timeout=10 * MINUTE,
        ),
    )


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_async_relate(first_model: Model, second_model: Model) -> None:
    """Relate the two mysql clusters."""
    logger.info("Creating offers in first model")
    await first_model.create_offer(f"{MYSQL_APP1}:replication-offer")

    logger.info("Consume offer in second model")
    await second_model.consume(endpoint=f"admin/{first_model.info.name}.{MYSQL_APP1}")

    logger.info("Relating the two mysql clusters")
    await second_model.integrate(f"{MYSQL_APP1}", f"{MYSQL_APP2}:replication")

    logger.info("Waiting for the applications to settle")
    await gather(
        first_model.block_until(
            lambda: any(
                unit.workload_status == "blocked"
                for unit in first_model.applications[MYSQL_APP1].units
            ),
            timeout=5 * MINUTE,
        ),
        second_model.block_until(
            lambda: all(
                unit.workload_status == "waiting"
                for unit in second_model.applications[MYSQL_APP2].units
            ),
            timeout=5 * MINUTE,
        ),
    )


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_create_replication(first_model: Model, second_model: Model) -> None:
    """Run the create replication and wait for the applications to settle."""
    logger.info("Running create replication action")
    leader_unit = await get_leader_unit(None, MYSQL_APP1, first_model)
    assert leader_unit is not None, "No leader unit found"

    await juju_.run_action(
        leader_unit,
        "create-replication",
        **{"--wait": "5m"},
    )

    logger.info("Waiting for the applications to settle")
    await gather(
        first_model.wait_for_idle(
            apps=[MYSQL_APP1],
            status="active",
            timeout=5 * MINUTE,
        ),
        second_model.wait_for_idle(
            apps=[MYSQL_APP2],
            status="active",
            timeout=5 * MINUTE,
        ),
    )


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_deploy_router_and_app(first_model: Model) -> None:
    """Deploy the router and the test application."""
    logger.info("Deploying router and application")
    await first_model.deploy(
        MYSQL_ROUTER_APP_NAME,
        application_name=MYSQL_ROUTER_APP_NAME,
        series="jammy",
        channel="8.0/edge",
        num_units=1,
        trust=True,
    )
    await first_model.deploy(
        APPLICATION_APP_NAME,
        application_name=APPLICATION_APP_NAME,
        series="jammy",
        channel="latest/edge",
        num_units=1,
    )

    logger.info("Relate app and router")
    await first_model.integrate(
        APPLICATION_APP_NAME,
        MYSQL_ROUTER_APP_NAME,
    )
    logger.info("Relate router and db")
    await first_model.integrate(MYSQL_ROUTER_APP_NAME, MYSQL_APP1)

    await first_model.wait_for_idle(
        apps=[MYSQL_ROUTER_APP_NAME, APPLICATION_APP_NAME],
        timeout=10 * MINUTE,
        raise_on_error=False,
    )


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_data_replication(
    first_model: Model, second_model: Model, continuous_writes
) -> None:
    """Test to write to primary, and read the same data back from replicas."""
    results = await get_max_written_value(first_model, second_model)
    assert len(results) == 6, f"Expected 6 results, got {len(results)}"
    assert all(x == results[0] for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_standby_promotion(
    ops_test: OpsTest, first_model: Model, second_model: Model, continuous_writes
) -> None:
    """Test graceful promotion of a standby cluster to primary."""
    leader_unit = await get_leader_unit(None, MYSQL_APP2, second_model)

    assert leader_unit is not None, "No leader unit found on standby cluster"

    logger.info("Promoting standby cluster to primary")
    await juju_.run_action(
        leader_unit,
        "promote-to-primary",
    )

    results = await get_max_written_value(first_model, second_model)
    assert len(results) == 6, f"Expected 6 results, got {len(results)}"
    assert all(x == results[0] for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"

    cluster_set_status = await get_cluster_status(leader_unit, cluster_set=True)
    assert (
        cluster_set_status["clusters"]["cuzco"]["clusterrole"] == "primary"
    ), "standby not promoted to primary"


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_failover(ops_test: OpsTest, first_model: Model, second_model: Model) -> None:
    """Test switchover on primary cluster fail."""
    logger.info("Freezing mysqld on primary cluster units")
    second_model_units = second_model.applications[MYSQL_APP2].units

    # simulating a failure on the primary cluster
    for unit in second_model_units:
        await send_signal_to_pod_container_process(
            second_model.info.name, unit.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME, "SIGSTOP"
        )

    logger.info("Promoting standby cluster to primary with force flag")
    leader_unit = await get_leader_unit(None, MYSQL_APP1, first_model)
    assert leader_unit is not None, "No leader unit found"
    await juju_.run_action(
        leader_unit,
        "promote-to-primary",
        **{"--wait": "5m", "force": True},
    )

    cluster_set_status = await get_cluster_status(leader_unit, cluster_set=True)
    assert (
        cluster_set_status["clusters"]["lima"]["clusterrole"] == "primary"
    ), "standby not promoted to primary"
    assert (
        cluster_set_status["clusters"]["cuzco"]["globalstatus"] == "invalidated"
    ), "old primary not invalidated"

    # restore mysqld process
    for unit in second_model_units:
        await send_signal_to_pod_container_process(
            second_model.info.name, unit.name, MYSQL_CONTAINER_NAME, MYSQLD_PROCESS_NAME, "SIGCONT"
        )


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_rejoin_invalidated_cluster(
    first_model: Model, second_model: Model, continuous_writes
) -> None:
    """Test rejoin invalidated cluster with."""
    leader_unit = await get_leader_unit(None, MYSQL_APP1, first_model)
    assert leader_unit is not None, "No leader unit found"
    await juju_.run_action(
        leader_unit,
        "rejoin-cluster",
        **{"--wait": "5m", "cluster-name": "cuzco"},
    )
    results = await get_max_written_value(first_model, second_model)
    assert len(results) == 6, f"Expected 6 results, got {len(results)}"
    assert all(x == results[0] for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"


@pytest.mark.group(1)
@markers.juju3
@markers.amd64_only  # TODO: remove after mysql-router-k8s arm64 stable release
@pytest.mark.abort_on_fail
async def test_remove_relation_and_relate(
    first_model: Model, second_model: Model, continuous_writes
) -> None:
    """Test removing and re-relating the two mysql clusters."""
    logger.info("Stopping continuous writes after 5s")
    # part 1/2 of workaround for https://github.com/canonical/mysql-k8s-operator/issues/399
    # sleep is need to ensure there is enough time for the `continuous_writes` database be
    # created/populated (by the fixture) before stopping the continuous writes
    sleep(5)
    application_unit = first_model.applications[APPLICATION_APP_NAME].units[0]
    await juju_.run_action(application_unit, "stop-continuous-writes")

    logger.info("Remove async relation")
    await second_model.applications[MYSQL_APP2].remove_relation(
        f"{MYSQL_APP2}:replication", MYSQL_APP1
    )

    second_model_units = second_model.applications[MYSQL_APP2].units
    logger.info("waiting for units to be blocked")
    await second_model.block_until(
        lambda: all(unit.workload_status == "blocked" for unit in second_model_units),
        timeout=10 * MINUTE,
    )

    logger.info("Waiting for the applications to settle")
    await gather(
        first_model.wait_for_idle(
            apps=[MYSQL_APP1],
            status="active",
            timeout=10 * MINUTE,
        ),
        second_model.wait_for_idle(
            apps=[MYSQL_APP2],
            status="blocked",
            timeout=10 * MINUTE,
        ),
    )

    logger.info("Re relating the two mysql clusters")
    await second_model.integrate(f"{MYSQL_APP1}", f"{MYSQL_APP2}:replication")

    logger.info("Waiting for the applications to settle")
    await first_model.block_until(
        lambda: any(
            unit.workload_status == "blocked"
            for unit in first_model.applications[MYSQL_APP1].units
        ),
        timeout=5 * MINUTE,
    )

    logger.info("Running create replication action")
    leader_unit = await get_leader_unit(None, MYSQL_APP1, first_model)
    assert leader_unit is not None, "No leader unit found"

    await juju_.run_action(
        leader_unit,
        "create-replication",
        **{"--wait": "5m"},
    )

    logger.info("Waiting for the applications to settle")
    await gather(
        first_model.wait_for_idle(
            apps=[MYSQL_APP1],
            status="active",
            timeout=10 * MINUTE,
        ),
        second_model.wait_for_idle(
            apps=[MYSQL_APP2],
            status="active",
            timeout=10 * MINUTE,
        ),
    )

    # part 2/2 of workaround for https://github.com/canonical/mysql-k8s-operator/issues/399
    await juju_.run_action(application_unit, "start-continuous-writes")

    results = await get_max_written_value(first_model, second_model)
    assert len(results) == 6, f"Expected 6 results, got {len(results)}"
    assert all(x == results[0] for x in results), "Data is not consistent across units"
    assert results[0] > 1, "No data was written to the database"


async def get_max_written_value(first_model: Model, second_model: Model) -> list[int]:
    """Return list with max written value from all units."""
    select_max_written_value_sql = [f"SELECT MAX(number) FROM `{DATABASE_NAME}`.`{TABLE_NAME}`;"]
    logger.info("Testing data replication")
    first_model_units = first_model.applications[MYSQL_APP1].units
    second_model_units = second_model.applications[MYSQL_APP2].units
    credentials = await juju_.run_action(
        first_model_units[0], "get-password", username="serverconfig"
    )

    logger.info("Stopping continuous writes and wait (5s) for replication")
    application_unit = first_model.applications[APPLICATION_APP_NAME].units[0]
    await juju_.run_action(application_unit, "stop-continuous-writes")

    sleep(5)
    results = []

    logger.info("Querying max value on all units")
    for unit in first_model_units + second_model_units:
        address = await get_unit_address(None, unit.name, unit.model)
        values = await execute_queries_on_unit(
            address, credentials["username"], credentials["password"], select_max_written_value_sql
        )
        results.append(values[0])

    return results
