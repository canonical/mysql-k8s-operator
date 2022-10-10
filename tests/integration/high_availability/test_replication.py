#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import lightkube
import pytest
from helpers import get_cluster_status, get_primary_unit
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.high_availability.high_availability_helpers import (
    get_max_written_value_in_database,
    high_availability_test_setup,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


@pytest.mark.order(1)
@pytest.mark.abort_on_fail
@pytest.mark.replication_tests
async def test_kill_primary_check_reelection(ops_test: OpsTest) -> None:
    """Test to kill the primary under load and ensure re-election of primary."""
    mysql_application_name, _ = await high_availability_test_setup(ops_test)

    mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
    primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
    primary_name = primary.name

    last_written_value = await get_max_written_value_in_database(ops_test, primary)

    client = lightkube.Client()
    client.delete(Pod, primary.name.replace("/", "-"), namespace=ops_test.model.info.name)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[mysql_application_name],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        )

        mysql_unit = ops_test.model.applications[mysql_application_name].units[0]
        new_primary = await get_primary_unit(ops_test, mysql_unit, mysql_application_name)
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
            for unit in ops_test.model.applications[mysql_application_name].units:
                written_value = await get_max_written_value_in_database(ops_test, unit)
                assert written_value > last_written_value, "Continuous writes not incrementing"

                last_written_value = written_value
