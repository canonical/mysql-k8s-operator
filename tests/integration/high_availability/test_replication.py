#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import lightkube
import pytest
import yaml
from helpers import get_cluster_status, get_primary_unit
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.high_availability.high_availability_helpers import (
    get_max_written_value_in_database,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MYSQL_APP_NAME = METADATA["name"]
APPLICATION_APP_NAME = "application"
CLUSTER_NAME = "test_cluster"
TIMEOUT = 15 * 60


@pytest.mark.order(1)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build, deploy and relate the mysql and test applications."""
    mysql_charm = await ops_test.build_charm(".")
    application_charm = await ops_test.build_charm(
        "./tests/integration/high_availability/application_charm/"
    )

    mysql_config = {"cluster-name": CLUSTER_NAME}
    mysql_resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}

    async with ops_test.fast_forward():
        await ops_test.model.deploy(
            mysql_charm,
            application_name=MYSQL_APP_NAME,
            config=mysql_config,
            resources=mysql_resources,
            num_units=3,
        )

        await ops_test.model.deploy(
            application_charm,
            application_name=APPLICATION_APP_NAME,
            num_units=1,
        )

        await ops_test.model.relate(
            f"{MYSQL_APP_NAME}:database", f"{APPLICATION_APP_NAME}:database"
        )

        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME, APPLICATION_APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        assert len(ops_test.model.applications[MYSQL_APP_NAME].units) == 3
        assert len(ops_test.model.applications[APPLICATION_APP_NAME].units) == 1


@pytest.mark.order(2)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_kill_primary_check_reelection(ops_test: OpsTest) -> None:
    """Test to kill the primary under load and ensure re-election of primary."""
    application_unit = ops_test.model.applications[APPLICATION_APP_NAME].units[0]
    mysql_unit = ops_test.model.applications[MYSQL_APP_NAME].units[0]

    clear_writes_action = await application_unit.run_action("clear-continuous-writes")
    await clear_writes_action.wait()

    start_writes_action = await application_unit.run_action("start-continuous-writes")
    await start_writes_action.wait()

    primary = await get_primary_unit(ops_test, mysql_unit, MYSQL_APP_NAME)
    primary_name = primary.name

    last_written_value = await get_max_written_value_in_database(ops_test, primary)

    client = lightkube.Client()
    client.delete(Pod, primary.name.replace("/", "-"), namespace=ops_test.model.info.name)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        mysql_unit = ops_test.model.applications[MYSQL_APP_NAME].units[0]
        new_primary = await get_primary_unit(ops_test, mysql_unit, MYSQL_APP_NAME)
        new_primary_name = new_primary.name

        assert primary_name != new_primary_name

        try:
            for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(10)):
                with attempt:
                    cluster_status = await get_cluster_status(ops_test, mysql_unit)
                    online_members = [
                        label
                        for label, member in cluster_status["defaultreplicaset"][
                            "topology"
                        ].items()
                        if member["status"] == "online"
                    ]
                    assert len(online_members) == 3
                    break
        except RetryError:
            assert False, "Old primary has not come back online after being killed"

    for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(3)):
        with attempt:
            for unit in ops_test.model.applications[MYSQL_APP_NAME].units:
                written_value = await get_max_written_value_in_database(ops_test, unit)
                assert written_value > last_written_value, "Continuous writes not incrementing"

                last_written_value = written_value
